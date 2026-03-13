"""
Integration layer for LangGraph agent with Django chat APIs.
Provides adapters for REST API, WebSocket, and management commands.
"""
import logging
from typing import Dict, Any, Optional
from django.conf import settings
from chats.models import Session, ChatMessage
from chats.ip_resolver import IPResolver
from chats.session_manager import SessionManager
from agents.langgraph_agent.agent import LangGraphAgent

logger = logging.getLogger(__name__)


class ChatAPIIntegration:
    """
    Integration layer for LangGraph agent with chat APIs.
    Provides unified interface for REST API, WebSocket, and other consumers.
    """
    
    @staticmethod
    def process_message(session_id: str, user_message: str) -> Dict[str, Any]:
        """
        Process a user message and return agent response.
        
        This is the main entry point for all chat APIs (REST, WebSocket, etc.)
        
        Args:
            session_id: The session ID (UUID)
            user_message: The user's message text
            
        Returns:
            Dictionary with agent response and metadata
            
        Raises:
            Session.DoesNotExist: If session not found
            ValueError: If session is invalid
        """
        try:
            # Get session
            session = Session.objects.get(id=session_id)
            
            # Validate session
            if not session.is_active:
                raise ValueError("Session is not active")
            
            if session.status == Session.Status.INACTIVE:
                raise ValueError("Session has expired")
            
            # If session is SNOOZED, reactivate it when user sends a message
            if session.status == Session.Status.SNOOZED:
                session.status = Session.Status.ACTIVE
                session.save(update_fields=['status'])
                logger.info(f"[INTEGRATION] Reactivated SNOOZED session: {session_id}")
            
            # Create agent
            agent = LangGraphAgent(session)
            
            # Process message
            response = agent.handle_message(user_message)
            
            logger.info(f"[INTEGRATION] Message processed for session {session_id}")
            
            return response
            
        except Session.DoesNotExist:
            logger.error(f"[INTEGRATION] Session not found: {session_id}")
            raise
        except Exception as e:
            logger.error(f"[INTEGRATION] Error processing message: {str(e)}", exc_info=True)
            raise
    
    @staticmethod
    def get_session_state(session_id: str) -> Dict[str, Any]:
        """
        Get current session state and conversation data.
        
        Args:
            session_id: The session ID (UUID)
            
        Returns:
            Dictionary with session state
        """
        try:
            session = Session.objects.get(id=session_id)
            
            return {
                'session_id': str(session.id),
                'is_active': session.is_active,
                'is_inactive': session.status == Session.Status.INACTIVE,
                'conversation_data': session.conversation_data or {},
                'message_count': ChatMessage.objects.filter(
                    session=session,
                    is_deleted=False
                ).count(),
                'created_at': session.created_at.isoformat(),
                'expires_at': session.expires_at.isoformat() if session.expires_at else None,
            }
        except Session.DoesNotExist:
            logger.error(f"[INTEGRATION] Session not found: {session_id}")
            raise
    
    @staticmethod
    def get_conversation_history(session_id: str, limit: int = 10) -> list:
        """
        Get conversation history for a session.
        
        Args:
            session_id: The session ID (UUID)
            limit: Maximum number of messages to return
            
        Returns:
            List of messages with role and content
        """
        try:
            messages = ChatMessage.objects.filter(
                session_id=session_id,
                is_deleted=False,
                role__in=['user', 'assistant']
            ).order_by('-timestamp')[:limit]
            
            history = []
            for msg in reversed(messages):
                history.append({
                    'role': msg.role,
                    'content': msg.message,
                    'timestamp': msg.timestamp.isoformat(),
                    'id': str(msg.id)
                })
            
            return history
        except Exception as e:
            logger.error(f"[INTEGRATION] Error getting conversation history: {str(e)}")
            return []
    
    @staticmethod
    def end_session(session_id: str) -> Dict[str, Any]:
        """
        End a session gracefully.
        
        Args:
            session_id: The session ID (UUID)
            
        Returns:
            Dictionary with end status
        """
        try:
            session = Session.objects.get(id=session_id)
            
            conversation_data = session.conversation_data or {}
            conversation_data['step'] = 'complete'
            
            session.conversation_data = conversation_data
            session.is_active = False
            session.save(update_fields=['conversation_data', 'is_active'])
            
            logger.info(f"[INTEGRATION] Session ended: {session_id}")
            
            return {
                'success': True,
                'session_id': str(session.id),
                'message': 'Session ended successfully'
            }
        except Session.DoesNotExist:
            logger.error(f"[INTEGRATION] Session not found: {session_id}")
            raise
    
    @staticmethod
    def collect_user_info(session_id: str, name: Optional[str] = None,
                         email: Optional[str] = None, phone: Optional[str] = None) -> Dict[str, Any]:
        """
        Collect and store user information on the Visitor model.
        
        Args:
            session_id: The session ID (UUID)
            name: User's name (optional)
            email: User's email (optional)
            phone: User's phone (optional)
            
        Returns:
            Dictionary with collected information
        """
        try:
            session = Session.objects.get(id=session_id)
            visitor = session.visitor
            
            # Store profile data on Visitor model instead of session
            if name:
                visitor.name = name
            if email:
                visitor.email = email
            if phone:
                visitor.phone = phone
            
            # Save visitor with updated profile data
            update_fields = []
            if name:
                update_fields.append('name')
            if email:
                update_fields.append('email')
            if phone:
                update_fields.append('phone')
            
            if update_fields:
                visitor.save(update_fields=update_fields)
            
            logger.info(f"[INTEGRATION] User info collected for visitor {visitor.id} in session {session_id}")
            
            return {
                'success': True,
                'collected': {
                    'name': visitor.name,
                    'email': visitor.email,
                    'phone': visitor.phone
                }
            }
        except Session.DoesNotExist:
            logger.error(f"[INTEGRATION] Session not found: {session_id}")
            raise
    
    @staticmethod
    def create_session_for_ip(request_or_scope, is_websocket: bool = False) -> Dict[str, Any]:
        """
        Create a new session for a visitor resolved from IP address.
        
        Args:
            request_or_scope: Django request object or WebSocket scope
            is_websocket: Whether this is a WebSocket request
            
        Returns:
            Dictionary with session information
        """
        try:
            # Extract IP and resolve visitor
            if is_websocket:
                client_ip = IPResolver.extract_websocket_ip(request_or_scope)
            else:
                client_ip = IPResolver.extract_client_ip(request_or_scope)
            
            visitor = IPResolver.get_or_create_visitor_from_ip(client_ip)
            
            # Check for existing active session first
            existing_session = SessionManager.get_active_session(visitor)
            if existing_session:
                logger.info(f"[INTEGRATION] Found existing active session {existing_session.id} for visitor {visitor.id} (IP: {client_ip})")
                return {
                    'success': True,
                    'session_id': str(existing_session.id),
                    'visitor_id': str(visitor.id),
                    'visitor_profile': {
                        'name': visitor.name,
                        'email': visitor.email,
                        'phone': visitor.phone
                    },
                    'existing_session': True
                }
            
            # Create new session using SessionManager
            session = SessionManager.create_session(visitor)
            
            logger.info(f"[INTEGRATION] Created session {session.id} for visitor {visitor.id} (IP: {client_ip})")
            
            return {
                'success': True,
                'session_id': str(session.id),
                'visitor_id': str(visitor.id),
                'visitor_profile': {
                    'name': visitor.name,
                    'email': visitor.email,
                    'phone': visitor.phone
                },
                'existing_session': False
            }
        except Exception as e:
            logger.error(f"[INTEGRATION] Error creating session: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }


class RESTAPIAdapter:
    """
    Adapter for REST API endpoints.
    Converts REST requests to agent calls and formats responses.
    """
    
    @staticmethod
    def create_session(request) -> Dict[str, Any]:
        """
        Create a new session for REST API with IP-based visitor resolution.
        
        Args:
            request: Django request object (for IP extraction)
            
        Returns:
            Formatted response with session information
        """
        return ChatAPIIntegration.create_session_for_ip(request, is_websocket=False)
    
    @staticmethod
    def handle_chat_request(request, session_id: str, message: str) -> Dict[str, Any]:
        """
        Handle REST API chat request with IP-based visitor resolution.
        
        Args:
            request: Django request object (for IP extraction)
            session_id: The session ID
            message: The user's message
            
        Returns:
            Formatted response for REST API
        """
        try:
            # Extract client IP and resolve visitor
            client_ip = IPResolver.extract_client_ip(request)
            visitor = IPResolver.get_or_create_visitor_from_ip(client_ip)
            
            # Get session and validate it belongs to the resolved visitor
            session = Session.objects.get(id=session_id)
            
            if session.visitor.id != visitor.id:
                return {
                    'success': False,
                    'error': f"Session does not belong to the visitor resolved from IP {client_ip}"
                }
            
            # Ensure session is active - reactivate if snoozed
            if session.status == Session.Status.SNOOZED:
                SessionManager.reactivate_session(session)
                logger.info(f"[REST_API] Reactivated snoozed session {session_id}")
            elif session.status == Session.Status.INACTIVE:
                return {
                    'success': False,
                    'error': "Session is inactive and cannot be used"
                }
            
            # Process message
            response = ChatAPIIntegration.process_message(session_id, message)
            
            return {
                'success': True,
                'response': response['message'],
                'session_id': session_id,
                'needs_info': response.get('needs_info'),
                'suggestions': response.get('suggestions', []),
                'complete': response.get('complete', False),
                'knowledge_results': response.get('knowledge_results', []),
                'metadata': response.get('metadata', {}),
                'visitor_profile': {
                    'name': visitor.name,
                    'email': visitor.email,
                    'phone': visitor.phone
                }
            }
        except Exception as e:
            logger.error(f"[REST_API] Error handling chat request: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }


class WebSocketAdapter:
    """
    Adapter for WebSocket consumers.
    Converts WebSocket messages to agent calls and formats responses.
    """
    
    @staticmethod
    def create_session(scope) -> Dict[str, Any]:
        """
        Create a new session for WebSocket with IP-based visitor resolution.
        
        Args:
            scope: WebSocket scope (for IP extraction)
            
        Returns:
            Formatted response with session information
        """
        return ChatAPIIntegration.create_session_for_ip(scope, is_websocket=True)
    
    @staticmethod
    def handle_websocket_message(scope, session_id: str, message: str) -> Dict[str, Any]:
        """
        Handle WebSocket message with IP-based visitor resolution.
        
        Args:
            scope: WebSocket scope (for IP extraction)
            session_id: The session ID
            message: The user's message
            
        Returns:
            Formatted response for WebSocket
        """
        try:
            # Extract client IP and resolve visitor
            client_ip = IPResolver.extract_websocket_ip(scope)
            visitor = IPResolver.get_or_create_visitor_from_ip(client_ip)
            
            # Get session and validate it belongs to the resolved visitor
            session = Session.objects.get(id=session_id)
            
            if session.visitor.id != visitor.id:
                return {
                    'type': 'error',
                    'error': f"Session does not belong to the visitor resolved from IP {client_ip}"
                }
            
            # Ensure session is active - reactivate if snoozed
            if session.status == Session.Status.SNOOZED:
                SessionManager.reactivate_session(session)
                logger.info(f"[WEBSOCKET] Reactivated snoozed session {session_id}")
            elif session.status == Session.Status.INACTIVE:
                return {
                    'type': 'error',
                    'error': "Session is inactive and cannot be used"
                }
            
            # Process message
            response = ChatAPIIntegration.process_message(session_id, message)
            
            return {
                'type': 'complete',
                'message': response['message'],
                'session_id': session_id,
                'needs_info': response.get('needs_info'),
                'suggestions': response.get('suggestions', []),
                'complete': response.get('complete', False),
                'knowledge_results': response.get('knowledge_results', []),
                'metadata': response.get('metadata', {}),
                'visitor_profile': {
                    'name': visitor.name,
                    'email': visitor.email,
                    'phone': visitor.phone
                }
            }
        except Exception as e:
            logger.error(f"[WEBSOCKET] Error handling message: {str(e)}", exc_info=True)
            return {
                'type': 'error',
                'error': str(e)
            }
    
    @staticmethod
    def format_streaming_chunk(chunk: str, done: bool = False) -> Dict[str, Any]:
        """
        Format a streaming chunk for WebSocket.
        
        Args:
            chunk: The chunk text
            done: Whether streaming is complete
            
        Returns:
            Formatted chunk message
        """
        return {
            'type': 'chunk',
            'chunk': chunk,
            'done': done
        }


def use_langgraph_agent() -> bool:
    """
    Check if LangGraph agent should be used.
    
    Returns:
        True if LangGraph agent is enabled, False otherwise
    """
    return getattr(settings, 'USE_LANGGRAPH_AGENT', False)


def get_agent_class():
    """
    Get the appropriate agent class based on configuration.
    
    Returns:
        Agent class (LangGraphAgent or UnifiedAgent)
    """
    if use_langgraph_agent():
        return LangGraphAgent
    else:
        from agents.unified_agent import UnifiedAgent
        return UnifiedAgent
