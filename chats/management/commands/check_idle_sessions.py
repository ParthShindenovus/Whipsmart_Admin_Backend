"""
Django management command to check and handle idle sessions.

This command:
1. Checks all active sessions for inactivity
2. Sends idle warnings after 2 minutes of inactivity
3. Ends sessions after 4 minutes of inactivity
4. Sends messages via WebSocket if connections exist

Run this command periodically (e.g., every minute) via cronjob.
For Heroku, use Heroku Scheduler addon.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from chats.models import Session, ChatMessage
from agents.session_manager import session_manager
import logging
import json
import random

logger = logging.getLogger(__name__)

# Import WebSocket connection tracking from consumers
# We'll need to access this to send messages to active connections
try:
    from chats.consumers import _active_connections
except ImportError:
    _active_connections = {}
    logger.warning("Could not import _active_connections from consumers.py")


class Command(BaseCommand):
    help = 'Check idle sessions and send warnings/end sessions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without making changes (for testing)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        now = timezone.now()
        two_minutes_ago = now - timedelta(minutes=2)
        four_minutes_ago = now - timedelta(minutes=4)
        
        # Get all active sessions
        active_sessions = Session.objects.filter(is_active=True)
        
        self.stdout.write(f'Checking {active_sessions.count()} active sessions...')
        
        idle_warnings_sent = 0
        sessions_ended = 0
        
        for session in active_sessions:
            # Skip if no last_message_at (new session with no messages)
            if not session.last_message_at:
                continue
            
            # Get idle warning status from metadata
            metadata = session.metadata or {}
            idle_warning_sent = metadata.get('idle_warning_sent', False)
            idle_warning_sent_at = metadata.get('idle_warning_sent_at')
            
            # Check if session is idle for 4 minutes (should end session)
            if session.last_message_at <= four_minutes_ago:
                if not dry_run:
                    self._end_session_idle(session)
                sessions_ended += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'Ended session {session.id} (idle for 4+ minutes)'
                    )
                )
            
            # Check if session is idle for 2 minutes (should send warning)
            elif session.last_message_at <= two_minutes_ago and not idle_warning_sent:
                if not dry_run:
                    self._send_idle_warning(session)
                idle_warnings_sent += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'Sent idle warning to session {session.id} (idle for 2+ minutes)'
                    )
                )
            
            # Reset warning flag if activity occurred after warning was sent
            elif idle_warning_sent and idle_warning_sent_at:
                try:
                    from django.utils.dateparse import parse_datetime
                    warning_sent_time = parse_datetime(idle_warning_sent_at)
                    if warning_sent_time and session.last_message_at > warning_sent_time:
                        if not dry_run:
                            metadata['idle_warning_sent'] = False
                            metadata.pop('idle_warning_sent_at', None)
                            session.metadata = metadata
                            session.save(update_fields=['metadata'])
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Reset idle warning flag for session {session.id} (activity detected after warning)'
                            )
                        )
                except (ValueError, TypeError) as e:
                    # If parsing fails, reset the flag anyway
                    if not dry_run:
                        metadata['idle_warning_sent'] = False
                        metadata.pop('idle_warning_sent_at', None)
                        session.metadata = metadata
                        session.save(update_fields=['metadata'])
                    logger.warning(f"Error parsing idle_warning_sent_at for session {session.id}: {str(e)}")
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nSummary: {idle_warnings_sent} warnings sent, {sessions_ended} sessions ended'
            )
        )

    def _send_idle_warning(self, session):
        """Send idle warning message to session."""
        warning_messages = [
            "Are you still there? I'm here if you need anything!",
            "Are you still around? Let me know if you need help!",
            "Just checking in - are you there? I'm ready to help when you are!",
            "Still here? Feel free to ask me anything!",
        ]
        
        warning_message = random.choice(warning_messages)
        
        try:
            # Save warning message to database
            session_manager.save_assistant_message(
                str(session.id),
                warning_message,
                metadata={'type': 'idle_warning'}
            )
            
            # Update session's last_message and last_message_at
            session.refresh_from_db()
            session.last_message = warning_message[:500]
            session.last_message_at = timezone.now()
            
            # Mark warning as sent in metadata
            metadata = session.metadata or {}
            metadata['idle_warning_sent'] = True
            metadata['idle_warning_sent_at'] = timezone.now().isoformat()
            session.metadata = metadata
            
            session.save(update_fields=['last_message', 'last_message_at', 'metadata'])
            
            # Send via WebSocket if connections exist
            self._send_websocket_message(session, 'idle_warning', warning_message)
            
            logger.info(f"[IDLE_TIMER] Sent idle warning to session: {session.id}")
            
        except Exception as e:
            logger.error(f"[IDLE_TIMER] Error sending idle warning to session {session.id}: {str(e)}", exc_info=True)

    def _end_session_idle(self, session):
        """End session due to idle timeout."""
        end_message = "I'll end this conversation due to no response from your end for sometime. Please feel free to reach out to us anytime if you want to know more about WhipSmart"
        
        try:
            # Save end message to database
            session_manager.save_assistant_message(
                str(session.id),
                end_message,
                metadata={'type': 'session_end', 'reason': 'idle_timeout'}
            )
            
            # Update session
            session.refresh_from_db()
            session.last_message = end_message[:500]
            session.last_message_at = timezone.now()
            session.is_active = False
            
            # Clear idle warning metadata
            metadata = session.metadata or {}
            metadata.pop('idle_warning_sent', None)
            metadata.pop('idle_warning_sent_at', None)
            session.metadata = metadata
            
            session.save(update_fields=['last_message', 'last_message_at', 'is_active', 'metadata'])
            
            # Send via WebSocket if connections exist
            self._send_websocket_message(session, 'session_end', end_message, complete=True)
            
            logger.info(f"[IDLE_TIMER] Ended session due to idle timeout: {session.id}")
            
        except Exception as e:
            logger.error(f"[IDLE_TIMER] Error ending session {session.id}: {str(e)}", exc_info=True)

    def _send_websocket_message(self, session, message_type, message, complete=False):
        """Send message to all WebSocket connections for this session using channel layer."""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            
            channel_layer = get_channel_layer()
            if not channel_layer:
                logger.warning(f"[IDLE_TIMER] Channel layer not available - cannot send WebSocket message for session: {session.id}")
                return
            
            # Get the saved message ID
            assistant_message = ChatMessage.objects.filter(
                session=session,
                role='assistant',
                is_deleted=False
            ).order_by('-timestamp').first()
            
            # Prepare message data
            if message_type == 'idle_warning':
                event_data = {
                    'type': 'idle_warning',
                    'message': message,
                    'response_id': str(assistant_message.id) if assistant_message else None,
                    'metadata': {'type': 'idle_warning', 'timeout_seconds': 120}
                }
            elif message_type == 'session_end':
                event_data = {
                    'type': 'session_end',
                    'message': message,
                    'response_id': str(assistant_message.id) if assistant_message else None,
                    'complete': True,
                    'conversation_data': session.conversation_data,
                    'metadata': {'type': 'session_end', 'reason': 'idle_timeout', 'timeout_seconds': 240}
                }
            else:
                return
            
            # Send to channel group for this session
            group_name = f"session_{session.id}"
            try:
                async_to_sync(channel_layer.group_send)(group_name, event_data)
                logger.info(f"[IDLE_TIMER] Successfully sent {message_type} to channel group {group_name} for session: {session.id}")
            except Exception as e:
                logger.error(f"[IDLE_TIMER] Error sending to channel group {group_name}: {str(e)}", exc_info=True)
                
        except Exception as e:
            logger.error(f"[IDLE_TIMER] Error sending WebSocket message via channel layer: {str(e)}", exc_info=True)

