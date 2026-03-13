"""
Background tasks for session lifecycle management.
Provides periodic tasks for automated session state updates and cleanup.
"""
import logging
from typing import Dict, Any
from django.utils import timezone
from .session_lifecycle_manager import SessionLifecycleManager
from .cleanup_service import CleanupService

logger = logging.getLogger(__name__)


def update_session_lifecycle_states() -> Dict[str, Any]:
    """
    Periodic task to update session states based on lifecycle rules.
    
    This task is designed to run every 5 minutes to:
    - Transition ACTIVE sessions to SNOOZED after 4 minutes of inactivity
    - Transition ACTIVE/SNOOZED sessions to INACTIVE after 24 hours from creation
    
    Returns:
        dict: Task execution results with counts and status
    """
    try:
        start_time = timezone.now()
        logger.info("Starting periodic session lifecycle update task")
        
        # Execute the batch session state update
        results = SessionLifecycleManager.update_session_states()
        
        # Calculate execution time
        end_time = timezone.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Prepare task result
        task_result = {
            'status': 'success',
            'execution_time_seconds': execution_time,
            'timestamp': end_time.isoformat(),
            'snoozed_count': results.get('snoozed_count', 0),
            'inactivated_count': results.get('inactivated_count', 0),
            'total_processed': results.get('total_processed', 0)
        }
        
        # Log results
        if task_result['total_processed'] > 0:
            logger.info(
                f"Session lifecycle update completed: "
                f"{task_result['snoozed_count']} snoozed, "
                f"{task_result['inactivated_count']} inactivated "
                f"in {execution_time:.2f}s"
            )
        else:
            logger.debug(f"No sessions required state transitions (execution time: {execution_time:.2f}s)")
        
        return task_result
        
    except Exception as e:
        error_msg = f"Session lifecycle update task failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        return {
            'status': 'error',
            'error': error_msg,
            'timestamp': timezone.now().isoformat(),
            'snoozed_count': 0,
            'inactivated_count': 0,
            'total_processed': 0
        }


def get_session_lifecycle_stats() -> Dict[str, Any]:
    """
    Helper task to get current session statistics.
    Useful for monitoring and debugging session states.
    
    Returns:
        dict: Current session statistics by status
    """
    try:
        logger.debug("Getting session lifecycle statistics")
        
        stats = SessionLifecycleManager.get_session_stats()
        
        result = {
            'status': 'success',
            'timestamp': timezone.now().isoformat(),
            'stats': stats
        }
        
        logger.debug(f"Session stats retrieved: {stats}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to get session statistics: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        return {
            'status': 'error',
            'error': error_msg,
            'timestamp': timezone.now().isoformat(),
            'stats': {}
        }


def cleanup_old_sessions() -> Dict[str, Any]:
    """
    Periodic task to clean up old inactive sessions.
    
    This task is designed to run daily at low-traffic hours (e.g., 2 AM) to:
    - Delete INACTIVE sessions older than 30 days
    - Never delete Visitor records
    - Never delete ACTIVE or SNOOZED sessions
    - Log the number of sessions deleted
    
    Returns:
        dict: Task execution results with counts and status
    """
    try:
        start_time = timezone.now()
        logger.info("Starting periodic session cleanup task")
        
        # Execute the cleanup operation
        deleted_count = CleanupService.cleanup_old_sessions()
        
        # Calculate execution time
        end_time = timezone.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Prepare task result
        task_result = {
            'status': 'success',
            'execution_time_seconds': execution_time,
            'timestamp': end_time.isoformat(),
            'deleted_count': deleted_count,
            'cleanup_cutoff_days': 30
        }
        
        # Log results
        if deleted_count > 0:
            logger.info(
                f"Session cleanup completed: "
                f"{deleted_count} INACTIVE sessions deleted "
                f"in {execution_time:.2f}s"
            )
        else:
            logger.info(f"No sessions required cleanup (execution time: {execution_time:.2f}s)")
        
        return task_result
        
    except Exception as e:
        error_msg = f"Session cleanup task failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        return {
            'status': 'error',
            'error': error_msg,
            'timestamp': timezone.now().isoformat(),
            'deleted_count': 0,
            'cleanup_cutoff_days': 30
        }


def get_cleanup_stats() -> Dict[str, Any]:
    """
    Helper task to get current cleanup statistics.
    Useful for monitoring and debugging cleanup operations.
    
    Returns:
        dict: Current cleanup statistics
    """
    try:
        logger.debug("Getting cleanup statistics")
        
        stats = CleanupService.get_cleanup_stats()
        
        result = {
            'status': 'success',
            'timestamp': timezone.now().isoformat(),
            'stats': stats
        }
        
        logger.debug(f"Cleanup stats retrieved: {stats}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to get cleanup statistics: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        return {
            'status': 'error',
            'error': error_msg,
            'timestamp': timezone.now().isoformat(),
            'stats': {}
        }


# Task configuration for Django-Q
# These functions can be called directly or scheduled via Django-Q
PERIODIC_TASKS = {
    'session_lifecycle_update': {
        'func': 'chats.tasks.update_session_lifecycle_states',
        'schedule_type': 'I',  # Interval
        'minutes': 5,  # Run every 5 minutes
        'repeats': -1,  # Repeat indefinitely
        'name': 'Session Lifecycle Update',
        'hook': None,  # No success/failure hooks for now
    },
    'session_cleanup': {
        'func': 'chats.tasks.cleanup_old_sessions',
        'schedule_type': 'D',  # Daily
        'hour': 2,  # Run at 2 AM
        'minute': 0,  # At the top of the hour
        'repeats': -1,  # Repeat indefinitely
        'name': 'Session Cleanup',
        'hook': None,  # No success/failure hooks for now
    }
}