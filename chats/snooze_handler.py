"""
SnoozeHandler service for managing automatic session snoozing based on inactivity.
Handles the 4-minute inactivity timeout logic for transitioning sessions to SNOOZED state.
"""
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from .models import Session
from .session_manager import SessionManager
import logging

logger = logging.getLogger(__name__)


class SnoozeHandler:
    """
    Service class for managing automatic session snoozing based on inactivity.
    Handles the 4-minute inactivity timeout logic.
    """
    
    # 4-minute inactivity timeout as specified in requirements
    SNOOZE_TIMEOUT = timedelta(minutes=4)
    
    @staticmethod
    def check_and_snooze_inactive_sessions() -> int:
        """
        Check for sessions inactive > 4 minutes and snooze them.
        Only processes ACTIVE sessions that have been inactive for more than 4 minutes.
        
        Returns:
            int: Count of sessions that were snoozed
        """
        try:
            # Calculate the cutoff time (4 minutes ago)
            cutoff_time = timezone.now() - SnoozeHandler.SNOOZE_TIMEOUT
            
            # Find ACTIVE sessions that have been inactive for more than 4 minutes
            # Use last_message_at if available, otherwise fall back to created_at
            sessions_to_snooze = Session.objects.filter(
                status=Session.Status.ACTIVE
            ).extra(
                where=[
                    "COALESCE(last_message_at, created_at) < %s"
                ],
                params=[cutoff_time]
            )
            
            snoozed_count = 0
            
            # Process each session individually to handle any potential errors
            for session in sessions_to_snooze:
                try:
                    if SnoozeHandler.should_snooze(session):
                        with transaction.atomic():
                            SessionManager.transition_to_snoozed(session)
                            snoozed_count += 1
                            logger.info(f"Snoozed session {session.id} due to inactivity")
                except Exception as e:
                    logger.error(f"Failed to snooze session {session.id}: {e}")
                    # Continue processing other sessions even if one fails
                    continue
            
            if snoozed_count > 0:
                logger.info(f"Successfully snoozed {snoozed_count} inactive sessions")
            else:
                logger.debug("No sessions required snoozing")
            
            return snoozed_count
            
        except Exception as e:
            logger.error(f"Error in check_and_snooze_inactive_sessions: {e}")
            raise
    
    @staticmethod
    def should_snooze(session: Session) -> bool:
        """
        Check if session should be snoozed based on last activity.
        
        Args:
            session: The Session instance to check
            
        Returns:
            bool: True if session should be snoozed, False otherwise
        """
        try:
            # Only ACTIVE sessions can be snoozed
            if session.status != Session.Status.ACTIVE:
                logger.debug(f"Session {session.id} has status {session.status}, cannot snooze")
                return False
            
            # Calculate the cutoff time (4 minutes ago)
            cutoff_time = timezone.now() - SnoozeHandler.SNOOZE_TIMEOUT
            
            # Determine the last activity time
            # Use last_message_at if available, otherwise fall back to created_at
            last_activity = session.last_message_at or session.created_at
            
            # Check if session has been inactive for more than 4 minutes
            should_snooze = last_activity < cutoff_time
            
            if should_snooze:
                logger.debug(f"Session {session.id} should be snoozed (last activity: {last_activity}, cutoff: {cutoff_time})")
            else:
                logger.debug(f"Session {session.id} should not be snoozed (last activity: {last_activity}, cutoff: {cutoff_time})")
            
            return should_snooze
            
        except Exception as e:
            logger.error(f"Error checking if session {session.id} should be snoozed: {e}")
            # In case of error, err on the side of caution and don't snooze
            return False
    
    @staticmethod
    def get_snooze_candidates() -> 'QuerySet[Session]':
        """
        Get sessions that are candidates for snoozing.
        Returns ACTIVE sessions that have been inactive for more than 4 minutes.
        
        Returns:
            QuerySet[Session]: Sessions eligible for snoozing
        """
        try:
            cutoff_time = timezone.now() - SnoozeHandler.SNOOZE_TIMEOUT
            
            # Find ACTIVE sessions that have been inactive for more than 4 minutes
            candidates = Session.objects.filter(
                status=Session.Status.ACTIVE
            ).extra(
                where=[
                    "COALESCE(last_message_at, created_at) < %s"
                ],
                params=[cutoff_time]
            )
            
            logger.debug(f"Found {candidates.count()} sessions eligible for snoozing")
            return candidates
            
        except Exception as e:
            logger.error(f"Error getting snooze candidates: {e}")
            # Return empty queryset in case of error
            return Session.objects.none()