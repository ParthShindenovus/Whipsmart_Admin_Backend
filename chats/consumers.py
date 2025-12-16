"""
WebSocket consumer for streaming chat messages.
"""
import json
import logging
import asyncio
import random
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import Session, Visitor, ChatMessage
from agents.unified_agent import UnifiedAgent
from agents.session_manager import session_manager

logger = logging.getLogger(__name__)

# Class-level dictionaries to track active WebSocket connections and shared idle timeout state per session
# Key: (session_id, visitor_id), Value: list of ChatConsumer instances
_active_connections = {}

# Shared idle timeout state per session
# Key: (session_id, visitor_id), Value: dict with 'last_activity_time', 'idle_task', 'idle_warning_sent'
_session_idle_state = {}


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time streaming chat.
    Handles chat messages and streams responses similar to SSE endpoint.
    Includes idle timeout functionality with Australian-accented messages.
    
    All messages follow a consistent schema:
    {
        "type": "chunk" | "complete" | "idle_warning" | "session_end" | "error" | "connected",
        "session_id": "uuid",
        "message_id": "uuid" | null,  // User message ID
        "response_id": "uuid" | null,  // Assistant message ID
        "message": "string" | null,    // Full message text (for complete messages)
        "chunk": "string" | null,      // Chunk text (for streaming)
        "done": boolean,               // Whether streaming is done
        "complete": boolean,           // Whether session is complete
        "conversation_data": {},       // Session conversation data
        "needs_info": boolean | null, // Whether more info is needed
        "suggestions": [],            // Suggested responses
        "error": "string" | null,     // Error message (if error)
        "metadata": {}                // Additional metadata
    }
    """
    
    # Idle timeout constants (in seconds)
    IDLE_WARNING_TIMEOUT = 120  # 2 minutes - send "Are you there?" message
    IDLE_SESSION_END_TIMEOUT = 240  # 4 minutes total - end session
    
    def format_message(self, message_type, **kwargs):
        """
        Format a standardized WebSocket message.
        
        Args:
            message_type: One of 'chunk', 'complete', 'idle_warning', 'session_end', 'error', 'connected'
            **kwargs: Additional fields to include in the message
        
        Returns:
            dict: Standardized message object
        """
        base_message = {
            'type': message_type,
            'session_id': self.session_id,
            'message_id': kwargs.get('message_id'),
            'response_id': kwargs.get('response_id'),
            'message': kwargs.get('message'),
            'chunk': kwargs.get('chunk'),
            'done': kwargs.get('done', False),
            'complete': kwargs.get('complete', False),
            'conversation_data': kwargs.get('conversation_data'),
            'needs_info': kwargs.get('needs_info'),
            'suggestions': kwargs.get('suggestions', []),
            'error': kwargs.get('error'),
            'metadata': kwargs.get('metadata', {})
        }
        
        # Remove None values to keep messages clean, but always include 'done' and 'complete' booleans
        cleaned_message = {}
        for k, v in base_message.items():
            if v is not None:
                cleaned_message[k] = v
            elif k in ('done', 'complete'):
                cleaned_message[k] = v  # Always include boolean flags even if False
        
        # Handle session_id override (for cases where we want to send None)
        if 'session_id' in kwargs:
            cleaned_message['session_id'] = kwargs['session_id']
        
        return cleaned_message
    
    async def connect(self):
        """Handle WebSocket connection."""
        self.session_id = None
        self.visitor_id = None
        self.session = None
        self.session_complete = False  # Track if session is complete
        
        # Extract query parameters from WebSocket URL if provided
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        if query_string:
            from urllib.parse import parse_qs
            params = parse_qs(query_string)
            self.session_id = params.get('session_id', [None])[0]
            self.visitor_id = params.get('visitor_id', [None])[0]
            if self.session_id:
                logger.info(f"[WEBSOCKET] Connection with session_id: {self.session_id}")
            if self.visitor_id:
                logger.info(f"[WEBSOCKET] Connection with visitor_id: {self.visitor_id}")
        
        # Accept the connection
        await self.accept()
        logger.info("[WEBSOCKET] Client connected")
        
        # Validate session and visitor if provided
        if self.session_id and self.visitor_id:
            validation = await self.validate_session_and_visitor(self.session_id, self.visitor_id)
            if not validation.get('valid'):
                error_message = validation.get('error', 'Validation failed')
                logger.warning(f"[WEBSOCKET] Validation failed: {error_message}")
                await self.send_error(error_message)
                await self.close()
                return
            
            # Store validated session
            self.session = validation.get('session')
            
            # Register this connection (allow multiple connections per session)
            connection_key = (self.session_id, self.visitor_id)
            if connection_key not in _active_connections:
                _active_connections[connection_key] = []
            _active_connections[connection_key].append(self)
            logger.info(f"[WEBSOCKET] Connection registered for session: {self.session_id} (total connections: {len(_active_connections[connection_key])})")
            
            # Initialize or reuse shared idle timeout state for this session
            if connection_key not in _session_idle_state:
                _session_idle_state[connection_key] = {
                    'last_activity_time': asyncio.get_event_loop().time(),
                    'idle_task': None,
                    'idle_warning_sent': False,
                    'session_complete': False
                }
                # Start idle monitoring task for this session
                _session_idle_state[connection_key]['idle_task'] = asyncio.create_task(
                    self.monitor_idle_timeout_shared(connection_key)
                )
                logger.info(f"[WEBSOCKET] Started shared idle monitoring for session: {self.session_id}")
            else:
                logger.info(f"[WEBSOCKET] Reusing existing idle timeout state for session: {self.session_id}")
            
            # Send connection confirmation with standardized schema
            try:
                def get_session_data():
                    try:
                        session = Session.objects.get(id=self.session_id)
                        return session.conversation_data
                    except Session.DoesNotExist:
                        return None
                
                conversation_data = await database_sync_to_async(get_session_data)()
                connected_message = self.format_message(
                    'connected',
                    message=None,
                    conversation_data=conversation_data,
                    metadata={'status': 'connected', 'reused_connection': connection_key in _session_idle_state}
                )
            except Exception:
                connected_message = self.format_message(
                    'connected',
                    message=None,
                    metadata={'status': 'connected'}
                )
        else:
            connected_message = self.format_message(
                'connected',
                session_id=None,
                message=None,
                metadata={'status': 'connected', 'warning': 'No session_id provided'}
            )
        
        await self.send(text_data=json.dumps(connected_message))
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        # Remove from active connections
        if self.session_id and self.visitor_id:
            connection_key = (self.session_id, self.visitor_id)
            if connection_key in _active_connections:
                try:
                    _active_connections[connection_key].remove(self)
                    logger.info(f"[WEBSOCKET] Removed connection from session: {self.session_id} (remaining: {len(_active_connections[connection_key])})")
                    
                    # If no more connections, clean up idle state
                    if len(_active_connections[connection_key]) == 0:
                        del _active_connections[connection_key]
                        if connection_key in _session_idle_state:
                            idle_state = _session_idle_state[connection_key]
                            if idle_state['idle_task']:
                                idle_state['idle_task'].cancel()
                            del _session_idle_state[connection_key]
                            logger.info(f"[WEBSOCKET] Cleaned up idle state for session: {self.session_id}")
                except ValueError:
                    # Connection not in list (already removed)
                    pass
        
        logger.info(f"[WEBSOCKET] Client disconnected with code: {close_code}")
    
    async def receive(self, text_data):
        """
        Handle incoming WebSocket messages.
        Expected message format:
        {
            "type": "chat_message",
            "message": "user message text",
            "session_id": "uuid",
            "visitor_id": "uuid"
        }
        """
        # Update shared idle timer on any message and restart monitoring
        if self.session_id and self.visitor_id:
            connection_key = (self.session_id, self.visitor_id)
            if connection_key in _session_idle_state:
                # Cancel existing idle task
                idle_state = _session_idle_state[connection_key]
                if idle_state['idle_task']:
                    idle_state['idle_task'].cancel()
                
                # Reset activity time and warning flag
                idle_state['last_activity_time'] = asyncio.get_event_loop().time()
                idle_state['idle_warning_sent'] = False
                
                # Restart idle monitoring task
                idle_state['idle_task'] = asyncio.create_task(
                    self.monitor_idle_timeout_shared(connection_key)
                )
                logger.info(f"[WEBSOCKET] Restarted idle monitoring for session: {self.session_id}")
        
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'chat_message':
                await self.handle_chat_message(data)
            elif message_type == 'pong' or message_type == 'ping':
                # Handle ping/pong for keepalive
                pass
            else:
                await self.send_error("Invalid message type. Expected 'chat_message'")
                
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON format")
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error receiving message: {str(e)}", exc_info=True)
            await self.send_error("An error occurred while processing your request")
    
    async def handle_chat_message(self, data):
        """Handle chat message and stream response."""
        message = data.get('message')
        session_id = data.get('session_id')
        visitor_id = data.get('visitor_id')
        
        # Validate required fields
        if not message:
            await self.send_error("message is required")
            return
        
        if not session_id:
            await self.send_error("session_id is required")
            return
        
        if not visitor_id:
            await self.send_error("visitor_id is required")
            return
        
        # Validate session and visitor
        validation_result = await self.validate_session_and_visitor(session_id, visitor_id)
        if not validation_result['valid']:
            await self.send_error(validation_result['error'])
            return
        
        session = validation_result['session']
        visitor = validation_result['visitor']
        
        # Store session reference for idle timeout
        self.session = session
        
        # Reset idle warning flag when user sends a message
        self.idle_warning_sent = False
        
        try:
            logger.info("=" * 80)
            logger.info(f"[WEBSOCKET] CHAT MESSAGE - Session: {session_id}")
            logger.info(f"[MSG] User Message: {message}")
            logger.info("=" * 80)
            
            # Save user message to database
            await self.save_user_message(session_id, message)
            
            # Get user message ID
            user_message = await self.get_last_user_message(session_id)
            
            # Process message and stream response
            await self.process_and_stream_response(session, message, user_message_obj=user_message)
            
            # Update shared idle timer after processing message and restart monitoring
            if self.session_id and self.visitor_id:
                connection_key = (self.session_id, self.visitor_id)
                if connection_key in _session_idle_state:
                    # Cancel existing idle task
                    idle_state = _session_idle_state[connection_key]
                    if idle_state['idle_task']:
                        idle_state['idle_task'].cancel()
                    
                    # Reset activity time and warning flag
                    idle_state['last_activity_time'] = asyncio.get_event_loop().time()
                    idle_state['idle_warning_sent'] = False
                    
                    # Restart idle monitoring task
                    idle_state['idle_task'] = asyncio.create_task(
                        self.monitor_idle_timeout_shared(connection_key)
                    )
                    logger.info(f"[WEBSOCKET] Restarted idle monitoring for session: {self.session_id} after message")
            
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error handling chat message: {str(e)}", exc_info=True)
            await self.send_error("An error occurred while processing your request")
    
    async def validate_session_and_visitor(self, session_id, visitor_id):
        """Validate session and visitor asynchronously."""
        try:
            # Use select_related to eagerly load visitor to avoid async database access
            def get_session():
                return Session.objects.select_related('visitor').get(id=session_id)
            
            session = await database_sync_to_async(get_session)()
            
            if not session.is_active:
                return {'valid': False, 'error': 'Session is not active'}
            
            # Check if session is expired (wrap in try-except in case method fails)
            def check_expired():
                return session.is_expired()
            
            try:
                is_expired = await database_sync_to_async(check_expired)()
                if is_expired:
                    return {'valid': False, 'error': 'Session has expired'}
            except Exception as e:
                logger.warning(f"[WEBSOCKET] Error checking session expiration: {str(e)}")
                # Continue validation if expiration check fails
            
            # Get visitor - session.visitor is already loaded via select_related
            visitor = session.visitor
            
            # Compare visitor IDs (both should be loaded now)
            if str(visitor.id) != str(visitor_id):
                return {'valid': False, 'error': f"Visitor ID '{visitor_id}' does not match the session's visitor ID '{visitor.id}'"}
            
            # Verify visitor exists separately (double-check)
            def get_visitor():
                return Visitor.objects.get(id=visitor_id)
            
            try:
                visitor_check = await database_sync_to_async(get_visitor)()
            except Visitor.DoesNotExist:
                return {'valid': False, 'error': f"Visitor with ID '{visitor_id}' does not exist"}
            
            # Update visitor last_seen_at
            try:
                await database_sync_to_async(visitor.update_last_seen)()
            except Exception as e:
                logger.warning(f"[WEBSOCKET] Error updating visitor last_seen: {str(e)}")
                # Continue even if update fails
            
            return {'valid': True, 'session': session, 'visitor': visitor}
            
        except Session.DoesNotExist:
            return {'valid': False, 'error': f'Session not found: {session_id}'}
        except Visitor.DoesNotExist:
            return {'valid': False, 'error': f"Visitor with ID '{visitor_id}' does not exist"}
        except ValueError as e:
            logger.error(f"[WEBSOCKET] Invalid UUID format: {str(e)}")
            return {'valid': False, 'error': f'Invalid ID format: {str(e)}'}
        except Exception as e:
            logger.error(f"[WEBSOCKET] Validation error: {str(e)}", exc_info=True)
            return {'valid': False, 'error': f'Validation failed: {str(e)}'}
    
    async def save_user_message(self, session_id, message):
        """Save user message to database asynchronously."""
        await database_sync_to_async(session_manager.save_user_message)(session_id, message)
    
    async def get_last_user_message(self, session_id):
        """Get last user message asynchronously."""
        def _get_message():
            return ChatMessage.objects.filter(
                session_id=session_id,
                role='user',
                is_deleted=False
            ).order_by('-timestamp').first()
        
        return await database_sync_to_async(_get_message)()
    
    async def process_and_stream_response(self, session, user_message_text, user_message_obj):
        """Process message using UnifiedAgent and stream response."""
        try:
            # Use UnifiedAgent to process the message
            agent = UnifiedAgent(session)
            
            # Process message synchronously (UnifiedAgent is synchronous)
            result = await database_sync_to_async(agent.handle_message)(user_message_text)
            
            assistant_message_text = result.get('message', '')
            
            # Stream the response preserving ALL formatting (newlines \n, markdown **, spaces, etc.)
            # Stream character-by-character in small chunks to preserve exact formatting
            full_response = ""
            chunk_buffer = ""
            chunk_size = 10  # Send chunks of 10 characters for balance between smoothness and efficiency
            
            for i, char in enumerate(assistant_message_text):
                full_response += char
                chunk_buffer += char
                
                # Send chunk when buffer reaches chunk_size or at end of message
                if len(chunk_buffer) >= chunk_size or i == len(assistant_message_text) - 1:
                    if chunk_buffer:  # Only send if buffer has content
                        chunk_message = self.format_message(
                            'chunk',
                            message_id=str(user_message_obj.id) if user_message_obj else None,
                            chunk=chunk_buffer,
                            done=False
                        )
                        await self.send(text_data=json.dumps(chunk_message))
                        chunk_buffer = ""
                        # Small delay for streaming effect
                        await asyncio.sleep(0.02)  # Small delay for character-by-character streaming
            
            # Send final chunk with done flag
            final_chunk_message = self.format_message(
                'chunk',
                message_id=str(user_message_obj.id) if user_message_obj else None,
                chunk='',
                done=True
            )
            await self.send(text_data=json.dumps(final_chunk_message))
            
            # Save complete assistant message to database (same as REST API)
            # Use session_manager to ensure consistency with REST API
            await database_sync_to_async(session_manager.save_assistant_message)(
                str(session.id),
                assistant_message_text.strip(),
                metadata=result.get('metadata') or {}
            )
            
            # Update session's last_message and last_message_at (same as REST API)
            def update_session():
                session.refresh_from_db()
                session.last_message = assistant_message_text.strip()[:500]  # Truncate for preview
                session.last_message_at = timezone.now()
                session.save(update_fields=['last_message', 'last_message_at'])
            
            await database_sync_to_async(update_session)()
            
            # Refresh session to get updated conversation_data
            await database_sync_to_async(session.refresh_from_db)()
            
            # Get the saved assistant message ID
            assistant_message = await self.get_last_assistant_message(str(session.id))
            
            # Check if session is complete
            is_complete = result.get('complete', False)
            self.session_complete = is_complete
            
            # Mark session as complete in shared idle state
            if self.session_id and self.visitor_id:
                connection_key = (self.session_id, self.visitor_id)
                if connection_key in _session_idle_state:
                    _session_idle_state[connection_key]['session_complete'] = True
                    # Cancel idle task
                    if _session_idle_state[connection_key]['idle_task']:
                        _session_idle_state[connection_key]['idle_task'].cancel()
                        _session_idle_state[connection_key]['idle_task'] = None
                    logger.info(f"[WEBSOCKET] Session marked as complete - idle monitoring stopped")
            
            # Send final response with standardized schema
            complete_message = self.format_message(
                'complete',
                message_id=str(user_message_obj.id) if user_message_obj else None,
                response_id=str(assistant_message.id) if assistant_message else None,
                message=assistant_message_text.strip(),
                conversation_data=session.conversation_data,
                complete=is_complete,
                needs_info=result.get('needs_info'),
                suggestions=result.get('suggestions', []),
                metadata=result.get('metadata', {})
            )
            await self.send(text_data=json.dumps(complete_message))
            
            logger.info("=" * 80)
            logger.info(f"[WEBSOCKET] Response streamed and saved successfully")
            logger.info(f"[WEBSOCKET] Complete: {is_complete}, Needs Info: {result.get('needs_info')}")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error processing response: {str(e)}", exc_info=True)
            await self.send_error("An error occurred while generating the response")
    
    async def get_last_assistant_message(self, session_id):
        """Get last assistant message asynchronously."""
        def _get_message():
            return ChatMessage.objects.filter(
                session_id=session_id,
                role='assistant',
                is_deleted=False
            ).order_by('-timestamp').first()
        
        return await database_sync_to_async(_get_message)()
    
    async def send_error(self, error_message, message_id=None):
        """Send error message to client with standardized schema."""
        error_data = self.format_message(
            'error',
            message_id=message_id,
            error=error_message,
            metadata={'error_type': 'processing_error'}
        )
        await self.send(text_data=json.dumps(error_data))
    
    def reset_idle_timer(self):
        """Reset the idle timer and restart monitoring."""
        # Don't start monitoring if session is complete
        if self.session_complete:
            return
        
        # Don't start monitoring if session is not active (check synchronously if session is loaded)
        if self.session and not self.session.is_active:
            logger.info(f"[WEBSOCKET] Session {self.session_id} is not active - skipping idle timer reset")
            return
        
        # Cancel existing task if any
        if self.idle_task:
            self.idle_task.cancel()
        
        # Update last activity time (use event loop time for consistency with monitor_idle_timeout)
        self.last_activity_time = asyncio.get_event_loop().time()
        
        # Reset warning flag
        self.idle_warning_sent = False
        
        # Start new idle monitoring task
        self.idle_task = asyncio.create_task(self.monitor_idle_timeout())
    
    async def monitor_idle_timeout(self):
        """Monitor idle timeout and send warnings/end session."""
        try:
            # Don't monitor if session is already complete
            if self.session_complete:
                logger.info("[WEBSOCKET] Session is complete - skipping idle monitoring")
                return
            
            # Check if session is active
            if not await self.is_session_active():
                logger.info("[WEBSOCKET] Session is not active - skipping idle monitoring")
                return
            
            # Store the activity time when timer starts
            timer_start_time = self.last_activity_time
            
            # Wait for first timeout (2 minutes)
            await asyncio.sleep(self.IDLE_WARNING_TIMEOUT)
            
            # Check if session became complete during wait
            if self.session_complete:
                logger.info("[WEBSOCKET] Session completed during idle wait - stopping monitoring")
                return
            
            # Check if session is still active
            if not await self.is_session_active():
                logger.info("[WEBSOCKET] Session became inactive during idle wait - stopping monitoring")
                return
            
            # Check if still idle (no activity since timer started)
            if timer_start_time and self.last_activity_time == timer_start_time and self.session_id:
                # Still idle - send warning
                if not self.idle_warning_sent:
                    await self.send_idle_warning()
                    self.idle_warning_sent = True
                    
                    # Wait for second timeout (another 2 minutes)
                    await asyncio.sleep(self.IDLE_WARNING_TIMEOUT)
                    
                    # Check if session became complete during wait
                    if self.session_complete:
                        logger.info("[WEBSOCKET] Session completed during idle warning wait - stopping monitoring")
                        return
                    
                    # Check if session is still active
                    if not await self.is_session_active():
                        logger.info("[WEBSOCKET] Session became inactive during idle warning wait - stopping monitoring")
                        return
                    
                    # Check if still idle after warning
                    if self.last_activity_time == timer_start_time:
                        # Still no activity - end the session
                        await self.end_session_idle()
                        
        except asyncio.CancelledError:
            # Task was cancelled (user sent a message, connection closed, or session completed)
            pass
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error in idle monitoring: {str(e)}", exc_info=True)
    
    async def is_session_active(self):
        """Check if the session is active."""
        if not self.session_id:
            return False
        
        try:
            def check_active():
                try:
                    session = Session.objects.get(id=self.session_id)
                    return session.is_active
                except Session.DoesNotExist:
                    return False
            
            return await database_sync_to_async(check_active)()
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error checking session active status: {str(e)}", exc_info=True)
            return False
    
    async def is_session_active_by_id(self, session_id):
        """Check if the session is active by session ID."""
        try:
            def check_active():
                try:
                    session = Session.objects.get(id=session_id)
                    return session.is_active
                except Session.DoesNotExist:
                    return False
            
            return await database_sync_to_async(check_active)()
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error checking session active status: {str(e)}", exc_info=True)
            return False
    
    async def monitor_idle_timeout_shared(self, connection_key):
        """Monitor idle timeout shared across all connections for a session."""
        session_id, visitor_id = connection_key
        try:
            # Get shared idle state
            idle_state = _session_idle_state.get(connection_key)
            if not idle_state:
                logger.warning(f"[WEBSOCKET] No idle state found for {session_id}")
                return
            
            # Don't monitor if session is already complete
            if idle_state.get('session_complete'):
                logger.info(f"[WEBSOCKET] Session {session_id} is complete - skipping idle monitoring")
                return
            
            # Check if session is active
            if not await self.is_session_active_by_id(session_id):
                logger.info(f"[WEBSOCKET] Session {session_id} is not active - skipping idle monitoring")
                return
            
            # Store the activity time when timer starts
            timer_start_time = idle_state['last_activity_time']
            logger.info(f"[WEBSOCKET] Starting idle monitoring for session {session_id}, timer_start_time: {timer_start_time}")
            
            # Wait for first timeout (2 minutes)
            await asyncio.sleep(self.IDLE_WARNING_TIMEOUT)
            
            # Re-check idle state (it might have changed)
            idle_state = _session_idle_state.get(connection_key)
            if not idle_state:
                logger.info(f"[WEBSOCKET] Idle state removed for {session_id} during wait")
                return
            
            # Check if session became complete during wait
            if idle_state.get('session_complete'):
                logger.info(f"[WEBSOCKET] Session {session_id} completed during idle wait - stopping monitoring")
                return
            
            # Check if session is still active
            if not await self.is_session_active_by_id(session_id):
                logger.info(f"[WEBSOCKET] Session {session_id} became inactive during idle wait - stopping monitoring")
                return
            
            # Check if still idle (no activity since timer started)
            current_activity_time = idle_state['last_activity_time']
            logger.info(f"[WEBSOCKET] Checking idle status for {session_id}: timer_start={timer_start_time}, current={current_activity_time}")
            
            if timer_start_time and current_activity_time == timer_start_time:
                # Still idle - send warning to all connections
                if not idle_state['idle_warning_sent']:
                    logger.info(f"[WEBSOCKET] Session {session_id} is idle - sending warning")
                    await self.send_idle_warning_shared(connection_key)
                    idle_state['idle_warning_sent'] = True
                    
                    # Wait for second timeout (another 2 minutes)
                    await asyncio.sleep(self.IDLE_WARNING_TIMEOUT)
                    
                    # Re-check idle state again
                    idle_state = _session_idle_state.get(connection_key)
                    if not idle_state:
                        logger.info(f"[WEBSOCKET] Idle state removed for {session_id} during warning wait")
                        return
                    
                    # Check if session became complete during wait
                    if idle_state.get('session_complete'):
                        logger.info(f"[WEBSOCKET] Session {session_id} completed during idle warning wait - stopping monitoring")
                        return
                    
                    # Check if session is still active
                    if not await self.is_session_active_by_id(session_id):
                        logger.info(f"[WEBSOCKET] Session {session_id} became inactive during idle warning wait - stopping monitoring")
                        return
                    
                    # Check if still idle after warning
                    current_activity_time = idle_state['last_activity_time']
                    if current_activity_time == timer_start_time:
                        # Still no activity - end the session
                        logger.info(f"[WEBSOCKET] Session {session_id} still idle after warning - ending session")
                        await self.end_session_idle_shared(connection_key)
                    else:
                        logger.info(f"[WEBSOCKET] Session {session_id} had activity after warning - timer was reset")
            else:
                logger.info(f"[WEBSOCKET] Session {session_id} had activity during idle wait - timer was reset")
                        
        except asyncio.CancelledError:
            # Task was cancelled (user sent a message, connection closed, or session completed)
            logger.info(f"[WEBSOCKET] Idle monitoring cancelled for {session_id}")
            pass
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error in shared idle monitoring for {session_id}: {str(e)}", exc_info=True)
    
    async def send_idle_warning_shared(self, connection_key):
        """Send idle warning message to all connections for a session."""
        session_id, visitor_id = connection_key
        
        # Check if session is active before sending warning
        if not await self.is_session_active_by_id(session_id):
            logger.info(f"[WEBSOCKET] Session {session_id} is not active - skipping idle warning")
            return
        
        warning_messages = [
            "Are you still there? I'm here if you need anything!",
            "Are you still around? Let me know if you need help!",
            "Just checking in - are you there? I'm ready to help when you are!",
            "Still here? Feel free to ask me anything!",
        ]
        
        warning_message = random.choice(warning_messages)
        
        try:
            # Save warning message to database using session_manager (same as REST API)
            await database_sync_to_async(session_manager.save_assistant_message)(
                session_id,
                warning_message,
                metadata={'type': 'idle_warning'}
            )
            
            # Update session's last_message and last_message_at
            def update_session():
                try:
                    session = Session.objects.get(id=session_id)
                    session.refresh_from_db()
                    session.last_message = warning_message[:500]  # Truncate for preview
                    session.last_message_at = timezone.now()
                    session.save(update_fields=['last_message', 'last_message_at'])
                except Session.DoesNotExist:
                    pass
            
            await database_sync_to_async(update_session)()
            
            # Get the saved message ID
            assistant_message = await self.get_last_assistant_message(session_id)
            
            # Send warning message to all active connections for this session
            connections = _active_connections.get(connection_key, [])
            for consumer in connections[:]:  # Copy list to avoid modification during iteration
                try:
                    warning_data = consumer.format_message(
                        'idle_warning',
                        message=warning_message,
                        response_id=str(assistant_message.id) if assistant_message else None,
                        metadata={'type': 'idle_warning', 'timeout_seconds': self.IDLE_WARNING_TIMEOUT}
                    )
                    await consumer.send(text_data=json.dumps(warning_data))
                except Exception as e:
                    logger.warning(f"[WEBSOCKET] Error sending idle warning to connection: {str(e)}")
                    # Remove dead connection
                    try:
                        connections.remove(consumer)
                    except ValueError:
                        pass
            
            logger.info(f"[WEBSOCKET] Sent idle warning for session: {session_id} to {len(connections)} connections")
            
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error sending idle warning: {str(e)}", exc_info=True)
    
    async def end_session_idle(self):
        """End session due to idle timeout."""
        if not self.session_id or not self.session:
            return
        
        try:
            # End session message - simple and professional
            end_messages = [
                "I'll end this session for now. Feel free to come back anytime if you need help!",
                "I'll close this session. Chat again soon if you need anything!",
                "I'll end this session. Come back whenever you're ready!",
            ]
            
            end_message = random.choice(end_messages)
            
            # Save end message to database using session_manager (same as REST API)
            await database_sync_to_async(session_manager.save_assistant_message)(
                self.session_id,
                end_message,
                metadata={'type': 'session_end', 'reason': 'idle_timeout'}
            )
            
            # Update session's last_message and last_message_at, then deactivate
            def deactivate_session():
                self.session.refresh_from_db()
                self.session.last_message = end_message[:500]  # Truncate for preview
                self.session.last_message_at = timezone.now()
                self.session.is_active = False
                self.session.save(update_fields=['last_message', 'last_message_at', 'is_active'])
            
            await database_sync_to_async(deactivate_session)()
            
            # Get the saved message ID
            assistant_message = await self.get_last_assistant_message(self.session_id)
            
            # Refresh session to get updated conversation_data
            await database_sync_to_async(self.session.refresh_from_db)()
            
            # Send session end message with standardized schema
            end_data = self.format_message(
                'session_end',
                message=end_message,
                response_id=str(assistant_message.id) if assistant_message else None,
                complete=True,
                conversation_data=self.session.conversation_data,
                metadata={'type': 'session_end', 'reason': 'idle_timeout', 'timeout_seconds': self.IDLE_SESSION_END_TIMEOUT}
            )
            await self.send(text_data=json.dumps(end_data))
            
            logger.info(f"[WEBSOCKET] Ended session due to idle timeout: {self.session_id}")
            
            # Close WebSocket connection
            await self.close()
            
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error ending session: {str(e)}", exc_info=True)
    
    async def end_session_idle_shared(self, connection_key):
        """End session due to idle timeout - send to all connections."""
        session_id, visitor_id = connection_key
        
        try:
            # End session message - simple and professional
            end_messages = [
                "I'll end this session for now. Feel free to come back anytime if you need help!",
                "I'll close this session. Chat again soon if you need anything!",
                "I'll end this session. Come back whenever you're ready!",
            ]
            
            end_message = random.choice(end_messages)
            
            # Save end message to database using session_manager (same as REST API)
            await database_sync_to_async(session_manager.save_assistant_message)(
                session_id,
                end_message,
                metadata={'type': 'session_end', 'reason': 'idle_timeout'}
            )
            
            # Update session's last_message and last_message_at, then deactivate
            def deactivate_session():
                try:
                    session = Session.objects.get(id=session_id)
                    session.refresh_from_db()
                    session.last_message = end_message[:500]  # Truncate for preview
                    session.last_message_at = timezone.now()
                    session.is_active = False
                    session.save(update_fields=['last_message', 'last_message_at', 'is_active'])
                    return session.conversation_data
                except Session.DoesNotExist:
                    return {}
            
            conversation_data = await database_sync_to_async(deactivate_session)()
            
            # Mark session as complete in idle state
            if connection_key in _session_idle_state:
                _session_idle_state[connection_key]['session_complete'] = True
            
            # Get the saved message ID
            assistant_message = await self.get_last_assistant_message(session_id)
            
            # Send session end message to all active connections for this session
            connections = _active_connections.get(connection_key, [])
            closed_count = 0
            for consumer in connections[:]:  # Copy list to avoid modification during iteration
                try:
                    end_data = consumer.format_message(
                        'session_end',
                        message=end_message,
                        response_id=str(assistant_message.id) if assistant_message else None,
                        complete=True,
                        conversation_data=conversation_data,
                        metadata={'type': 'session_end', 'reason': 'idle_timeout', 'timeout_seconds': self.IDLE_SESSION_END_TIMEOUT}
                    )
                    await consumer.send(text_data=json.dumps(end_data))
                    await consumer.close()
                    closed_count += 1
                except Exception as e:
                    logger.warning(f"[WEBSOCKET] Error sending session end to connection: {str(e)}")
                    # Remove dead connection
                    try:
                        connections.remove(consumer)
                    except ValueError:
                        pass
            
            logger.info(f"[WEBSOCKET] Ended session due to idle timeout: {session_id} (closed {closed_count} connections)")
            
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error ending session: {str(e)}", exc_info=True)
    
    async def save_assistant_message(self, session_id, message):
        """Save assistant message to database asynchronously."""
        def _save_message():
            from django.utils import timezone
            return ChatMessage.objects.create(
                session_id=session_id,
                message=message,
                role='assistant',
                metadata={},
                timestamp=timezone.now()
            )
        
        return await database_sync_to_async(_save_message)()

