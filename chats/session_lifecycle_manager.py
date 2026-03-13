"""
SessionLifecycleManager service for batch session state updates.
Handles automated session lifecycle management including snooze and inactive timeouts.
"""
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from .models import Session
import logging

logger = logging.getLogger(__name__)


class SessionLifecycleManager:
    """
    Service class for batch session lifecycle management.
    Handles automated transitions for snooze timeout (4 minutes) and inactive timeout (24 hours).
    """
    
    # Timeout constants as specified in requirements
    SNOOZE_TIMEOUT = timedelta(minutes=4)  # 4 minutes of inactivity triggers SNOOZED
    INACTIVE_TIMEOUT = timedelta(hours=24)  # 24 hours from creation triggers INACTIVE
    
    @classmethod
    def update_session_states(cls) -> dict:
        """
        Batch update session states based on timeouts.
        
        This method handles both snooze and inactive transitions in a single operation
        for performance optimization. It processes sessions in batches to avoid
        memory issues with large datasets.
        
        Returns:
            dict: Summary of state transitions with counts
                - snoozed_count: Number of sessions transitioned to SNOOZED
                - inactivated_count: Number of sessions transitioned to INACTIVE
                - total_processed: Total number of sessions processed
        """
        try:
            now = timezone.now()
            snoozed_count = 0
            inactivated_count = 0
            
            logger.info("Starting batch session state update")
            
            # First, handle inactive timeout (24 hours from creation)
            # This takes priority over snooze timeout
            with transaction.atomic():
                sessions_to_inactivate = Session.objects.filter(
                    status__in=[Session.Status.ACTIVE, Session.Status.SNOOZED],
                    created_at__lt=now - cls.INACTIVE_TIMEOUT
                ).select_for_update()
                
                inactivated_count = sessions_to_inactivate.count()
                if inactivated_count > 0:
                    # Set both status=INACTIVE and is_active=False after 24 hours
                    sessions_to_inactivate.update(
                        status=Session.Status.INACTIVE,
                        is_active=False
                    )
                    logger.info(f"Transitioned {inactivated_count} sessions to INACTIVE (24h timeout)")
            
            # Then, handle snooze timeout (4 minutes of inactivity)
            # Only process ACTIVE sessions that haven't been marked INACTIVE
            with transaction.atomic():
                cutoff_time = now - cls.SNOOZE_TIMEOUT
                
                # Find ACTIVE sessions that have been inactive for more than 4 minutes
                # Use COALESCE to handle sessions without last_message_at
                sessions_to_snooze = Session.objects.filter(
                    status=Session.Status.ACTIVE
                ).extra(
                    where=[
                        "COALESCE(last_message_at, created_at) < %s"
                    ],
                    params=[cutoff_time]
                ).select_for_update()
                
                snoozed_count = sessions_to_snooze.count()
                if snoozed_count > 0:
                    # Set status=SNOOZED but keep is_active=True
                    sessions_to_snooze.update(status=Session.Status.SNOOZED)
                    logger.info(f"Transitioned {snoozed_count} sessions to SNOOZED (4min inactivity)")
            
            total_processed = snoozed_count + inactivated_count
            
            if total_processed > 0:
                logger.info(f"Batch session state update completed: {snoozed_count} snoozed, {inactivated_count} inactivated")
            else:
                logger.debug("No sessions required state transitions")
            
            return {
                'snoozed_count': snoozed_count,
                'inactivated_count': inactivated_count,
                'total_processed': total_processed
            }
            
        except Exception as e:
            logger.error(f"Error in batch session state update: {e}")
            raise
    
    @classmethod
    def get_snooze_candidates(cls) -> 'QuerySet[Session]':
        """
        Get sessions that are candidates for snoozing.
        Returns ACTIVE sessions that have been inactive for more than 4 minutes.
        
        Returns:
            QuerySet[Session]: Sessions eligible for snoozing
        """
        try:
            cutoff_time = timezone.now() - cls.SNOOZE_TIMEOUT
            
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
            return Session.objects.none()
    
    @classmethod
    def get_inactive_candidates(cls) -> 'QuerySet[Session]':
        """
        Get sessions that are candidates for inactivation.
        Returns ACTIVE or SNOOZED sessions that have existed for more than 24 hours.
        
        Returns:
            QuerySet[Session]: Sessions eligible for inactivation
        """
        try:
            cutoff_time = timezone.now() - cls.INACTIVE_TIMEOUT
            
            candidates = Session.objects.filter(
                status__in=[Session.Status.ACTIVE, Session.Status.SNOOZED],
                created_at__lt=cutoff_time
            )
            
            logger.debug(f"Found {candidates.count()} sessions eligible for inactivation")
            return candidates
            
        except Exception as e:
            logger.error(f"Error getting inactive candidates: {e}")
            return Session.objects.none()
    
    @classmethod
    def get_session_stats(cls) -> dict:
        """
        Get current session statistics by status.
        Useful for monitoring and debugging.
        
        Returns:
            dict: Session counts by status
        """
        try:
            from django.db.models import Count
            
            stats = Session.objects.values('status').annotate(
                count=Count('id')
            ).order_by('status')
            
            result = {
                'ACTIVE': 0,
                'SNOOZED': 0,
                'INACTIVE': 0,
                'total': 0
            }
            
            for stat in stats:
                result[stat['status']] = stat['count']
                result['total'] += stat['count']
            
            logger.debug(f"Session stats: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting session stats: {e}")
            return {'error': str(e)}
    
    @classmethod
    def should_snooze_session(cls, session: Session) -> bool:
        """
        Check if a specific session should be snoozed based on last activity.
        
        Args:
            session: The Session instance to check
            
        Returns:
            bool: True if session should be snoozed, False otherwise
        """
        try:
            # Only ACTIVE sessions can be snoozed
            if session.status != Session.Status.ACTIVE:
                return False
            
            # Calculate the cutoff time (4 minutes ago)
            cutoff_time = timezone.now() - cls.SNOOZE_TIMEOUT
            
            # Determine the last activity time
            # Use last_message_at if available, otherwise fall back to created_at
            last_activity = session.last_message_at or session.created_at
            
            # Check if session has been inactive for more than 4 minutes
            return last_activity < cutoff_time
            
        except Exception as e:
            logger.error(f"Error checking if session {session.id} should be snoozed: {e}")
            return False
    
    @classmethod
    def should_inactivate_session(cls, session: Session) -> bool:
        """
        Check if a specific session should be inactivated based on creation time.
        
        Args:
            session: The Session instance to check
            
        Returns:
            bool: True if session should be inactivated, False otherwise
        """
        try:
            # Only ACTIVE or SNOOZED sessions can be inactivated
            if session.status not in [Session.Status.ACTIVE, Session.Status.SNOOZED]:
                return False
            
            # Calculate the cutoff time (24 hours ago)
            cutoff_time = timezone.now() - cls.INACTIVE_TIMEOUT
            
            # Check if session has existed for more than 24 hours
            return session.created_at < cutoff_time
            
        except Exception as e:
            logger.error(f"Error checking if session {session.id} should be inactivated: {e}")
            return False