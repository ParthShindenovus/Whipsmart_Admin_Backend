"""
SessionManager service for managing session lifecycle and state transitions.
This is separate from the existing DjangoSessionManager which handles message persistence.
"""
from typing import Optional
from django.utils import timezone
from .models import Session, Visitor
import logging

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Service class for managing session lifecycle and state transitions.
    Handles session creation, status transitions, and lifecycle management.
    """
    
    @staticmethod
    def create_session(visitor: Visitor) -> Session:
        """
        Create new ACTIVE session for visitor.
        
        Args:
            visitor: The Visitor instance to create a session for
            
        Returns:
            Session: Newly created session with ACTIVE status
        """
        try:
            session = Session.objects.create(
                visitor=visitor,
                status=Session.Status.ACTIVE
            )
            logger.info(f"Created new ACTIVE session {session.id} for visitor {visitor.id}")
            return session
        except Exception as e:
            logger.error(f"Failed to create session for visitor {visitor.id}: {e}")
            raise
    
    @staticmethod
    def get_active_session(visitor: Visitor) -> Optional[Session]:
        """
        Get visitor's current ACTIVE session if exists.
        
        Args:
            visitor: The Visitor instance to find active session for
            
        Returns:
            Optional[Session]: Active session if found, None otherwise
        """
        try:
            session = Session.objects.filter(
                visitor=visitor,
                status=Session.Status.ACTIVE
            ).first()
            
            if session:
                logger.debug(f"Found active session {session.id} for visitor {visitor.id}")
            else:
                logger.debug(f"No active session found for visitor {visitor.id}")
                
            return session
        except Exception as e:
            logger.error(f"Failed to get active session for visitor {visitor.id}: {e}")
            raise
    
    @staticmethod
    def transition_to_snoozed(session: Session) -> None:
        """
        Transition session to SNOOZED state.
        
        Args:
            session: The Session instance to transition
        """
        try:
            if session.status != Session.Status.ACTIVE:
                logger.warning(f"Attempting to snooze session {session.id} with status {session.status}")
            
            session.status = Session.Status.SNOOZED
            session.save(update_fields=['status'])
            
            logger.info(f"Transitioned session {session.id} to SNOOZED status")
        except Exception as e:
            logger.error(f"Failed to transition session {session.id} to SNOOZED: {e}")
            raise
    
    @staticmethod
    def reactivate_session(session: Session) -> None:
        """
        Transition SNOOZED session back to ACTIVE.
        Updates the last_message_at timestamp to current time.
        
        Args:
            session: The Session instance to reactivate
        """
        try:
            if session.status != Session.Status.SNOOZED:
                logger.warning(f"Attempting to reactivate session {session.id} with status {session.status}")
            
            session.status = Session.Status.ACTIVE
            session.last_message_at = timezone.now()
            session.save(update_fields=['status', 'last_message_at'])
            
            logger.info(f"Reactivated session {session.id} from SNOOZED to ACTIVE status")
        except Exception as e:
            logger.error(f"Failed to reactivate session {session.id}: {e}")
            raise
    
    @staticmethod
    def transition_to_inactive(session: Session) -> None:
        """
        Transition session to INACTIVE state.
        
        Args:
            session: The Session instance to transition
        """
        try:
            if session.status == Session.Status.INACTIVE:
                logger.debug(f"Session {session.id} is already INACTIVE")
                return
            
            session.status = Session.Status.INACTIVE
            session.is_active = False  # Sync is_active field for backward compatibility
            session.save(update_fields=['status', 'is_active'])
            
            logger.info(f"Transitioned session {session.id} to INACTIVE status")
        except Exception as e:
            logger.error(f"Failed to transition session {session.id} to INACTIVE: {e}")
            raise