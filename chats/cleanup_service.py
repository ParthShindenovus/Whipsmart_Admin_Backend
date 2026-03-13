"""
CleanupService for automated cleanup of old inactive sessions.
Handles deletion of INACTIVE sessions older than 30 days while preserving Visitor records.
"""
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import QuerySet
from .models import Session, Visitor
import logging

logger = logging.getLogger(__name__)


class CleanupService:
    """
    Service class for automated cleanup of old inactive sessions.
    Deletes INACTIVE sessions older than 30 days while preserving all Visitor records
    and all ACTIVE/SNOOZED sessions.
    """
    
    # 30-day cleanup timeout as specified in requirements
    CLEANUP_TIMEOUT = timedelta(days=30)
    
    @staticmethod
    def cleanup_old_sessions() -> int:
        """
        Delete INACTIVE sessions older than 30 days.
        
        This method:
        - Deletes sessions where status=INACTIVE AND updated_at < now-30days
        - NEVER deletes Visitor records
        - NEVER deletes sessions with status ACTIVE or SNOOZED
        - Logs the number of sessions deleted
        
        Returns:
            int: Number of sessions deleted
        """
        try:
            # Calculate the cutoff time (30 days ago)
            cutoff_time = timezone.now() - CleanupService.CLEANUP_TIMEOUT
            
            logger.info(f"Starting cleanup of INACTIVE sessions older than {cutoff_time}")
            
            # Get sessions eligible for cleanup
            cleanup_candidates = CleanupService.get_cleanup_candidates()
            
            # Filter by cutoff time (using created_at since Session model doesn't have updated_at)
            sessions_to_delete = cleanup_candidates.filter(created_at__lt=cutoff_time)
            
            # Count sessions before deletion for logging
            delete_count = sessions_to_delete.count()
            
            if delete_count == 0:
                logger.info("No INACTIVE sessions found that are older than 30 days")
                return 0
            
            # Log details before deletion
            logger.info(f"Found {delete_count} INACTIVE sessions older than 30 days for deletion")
            
            # Perform the deletion in a transaction
            with transaction.atomic():
                # Delete the sessions
                deleted_count, deleted_details = sessions_to_delete.delete()
                
                # Log the results
                actual_sessions_deleted = deleted_details.get('chats.Session', 0)
                logger.info(f"Successfully deleted {actual_sessions_deleted} INACTIVE sessions")
                
                # Log additional details if other related objects were deleted
                if deleted_count > actual_sessions_deleted:
                    logger.info(f"Total objects deleted: {deleted_count} (including related objects)")
                    for model, count in deleted_details.items():
                        if model != 'chats.Session' and count > 0:
                            logger.info(f"  - {model}: {count}")
                
                return actual_sessions_deleted
                
        except Exception as e:
            logger.error(f"Error during session cleanup: {e}")
            raise
    
    @staticmethod
    def get_cleanup_candidates() -> QuerySet[Session]:
        """
        Get sessions eligible for cleanup.
        Returns INACTIVE sessions that could potentially be deleted.
        
        This method returns sessions where:
        - status = INACTIVE
        
        The caller should apply additional time-based filtering as needed.
        
        Returns:
            QuerySet[Session]: Sessions eligible for cleanup (before time filtering)
        """
        try:
            candidates = Session.objects.filter(
                status=Session.Status.INACTIVE
            ).select_related('visitor')  # Include visitor for potential logging
            
            logger.debug(f"Found {candidates.count()} INACTIVE sessions as cleanup candidates")
            return candidates
            
        except Exception as e:
            logger.error(f"Error getting cleanup candidates: {e}")
            # Return empty queryset in case of error
            return Session.objects.none()
    
    @staticmethod
    def get_cleanup_stats() -> dict:
        """
        Get statistics about sessions eligible for cleanup.
        Useful for monitoring and reporting.
        
        Returns:
            dict: Statistics about cleanup candidates
                - total_inactive: Total number of INACTIVE sessions
                - cleanup_eligible: Number of INACTIVE sessions older than 30 days
                - cleanup_protected: Number of ACTIVE/SNOOZED sessions (never deleted)
                - total_sessions: Total number of sessions in database
                - total_visitors: Total number of visitors (never deleted)
        """
        try:
            cutoff_time = timezone.now() - CleanupService.CLEANUP_TIMEOUT
            
            # Count sessions by status
            total_sessions = Session.objects.count()
            total_inactive = Session.objects.filter(status=Session.Status.INACTIVE).count()
            cleanup_eligible = Session.objects.filter(
                status=Session.Status.INACTIVE,
                created_at__lt=cutoff_time
            ).count()
            cleanup_protected = Session.objects.filter(
                status__in=[Session.Status.ACTIVE, Session.Status.SNOOZED]
            ).count()
            
            # Count visitors (never deleted)
            total_visitors = Visitor.objects.count()
            
            stats = {
                'total_inactive': total_inactive,
                'cleanup_eligible': cleanup_eligible,
                'cleanup_protected': cleanup_protected,
                'total_sessions': total_sessions,
                'total_visitors': total_visitors,
                'cutoff_time': cutoff_time.isoformat()
            }
            
            logger.debug(f"Cleanup stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error getting cleanup stats: {e}")
            return {'error': str(e)}
    
    @staticmethod
    def dry_run_cleanup() -> dict:
        """
        Perform a dry run of the cleanup operation.
        Shows what would be deleted without actually deleting anything.
        
        Returns:
            dict: Information about what would be deleted
                - sessions_to_delete: Number of sessions that would be deleted
                - cutoff_time: The cutoff time used for deletion
                - sample_sessions: List of sample session IDs that would be deleted (max 10)
        """
        try:
            cutoff_time = timezone.now() - CleanupService.CLEANUP_TIMEOUT
            
            # Get sessions that would be deleted
            sessions_to_delete = CleanupService.get_cleanup_candidates().filter(
                created_at__lt=cutoff_time
            )
            
            delete_count = sessions_to_delete.count()
            
            # Get sample session IDs for reporting (limit to 10)
            sample_sessions = list(
                sessions_to_delete.values_list('id', flat=True)[:10]
            )
            
            result = {
                'sessions_to_delete': delete_count,
                'cutoff_time': cutoff_time.isoformat(),
                'sample_sessions': [str(session_id) for session_id in sample_sessions]
            }
            
            logger.info(f"Dry run cleanup result: {delete_count} sessions would be deleted")
            return result
            
        except Exception as e:
            logger.error(f"Error during dry run cleanup: {e}")
            return {'error': str(e)}