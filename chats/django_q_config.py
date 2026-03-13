"""
Django-Q configuration for session lifecycle management.

This module provides Django-Q settings and utilities for periodic task scheduling.
Add these settings to your Django settings.py file to enable Django-Q.
"""

# Django-Q Configuration
# Add this to your settings.py file:

DJANGO_Q_SETTINGS = {
    'name': 'whipsmart_session_tasks',
    'workers': 2,  # Number of worker processes
    'recycle': 500,  # Recycle worker after this many tasks
    'timeout': 300,  # Task timeout in seconds (5 minutes)
    'compress': True,  # Compress task data
    'save_limit': 250,  # Keep this many successful tasks in database
    'queue_limit': 500,  # Maximum tasks in queue
    'cpu_affinity': 1,  # CPU affinity for workers
    'label': 'Session Lifecycle Tasks',
    'redis': {
        'host': '127.0.0.1',
        'port': 6379,
        'db': 0,
        'password': None,
        'socket_timeout': None,
        'charset': 'utf-8',
        'errors': 'strict',
        'unix_socket_path': None,
    },
    # Alternative: Use Django ORM as broker (for development)
    'orm': 'default',  # Use Django database as broker instead of Redis
    
    # Task retry configuration
    'retry': 3600,  # Retry failed tasks after 1 hour
    'max_attempts': 3,  # Maximum retry attempts
    
    # Logging
    'catch_up': True,  # Catch up on missed scheduled tasks
    'sync': False,  # Set to True for synchronous execution (testing only)
}

# Installation Instructions
INSTALLATION_INSTRUCTIONS = """
To set up Django-Q for periodic session lifecycle tasks:

1. Install Django-Q:
   pip install django-q

2. Add to INSTALLED_APPS in settings.py:
   INSTALLED_APPS = [
       ...
       'django_q',
       ...
   ]

3. Add Django-Q configuration to settings.py:
   # Copy the DJANGO_Q_SETTINGS from this file

4. Run migrations:
   python manage.py migrate

5. Set up periodic tasks:
   python manage.py setup_periodic_tasks

6. Start Django-Q cluster:
   python manage.py qcluster

7. (Optional) Monitor tasks in Django admin:
   - Go to Django admin
   - Check "Django Q" section for task monitoring

For production deployment:
- Use Redis as broker instead of Django ORM
- Run qcluster as a service/daemon
- Monitor task execution and failures
- Set up proper logging and alerting
"""

# Alternative: Simple cron-based approach
CRON_INSTRUCTIONS = """
Alternative: Use cron instead of Django-Q

If you prefer not to use Django-Q, you can set up a cron job:

1. Create a management command to run the task:
   python manage.py run_session_lifecycle_update

2. Add to crontab (run every 5 minutes):
   */5 * * * * /path/to/your/venv/bin/python /path/to/your/project/manage.py run_session_lifecycle_update

3. For Heroku, use Heroku Scheduler addon:
   - Add the addon: heroku addons:create scheduler:standard
   - Configure job: python manage.py run_session_lifecycle_update
   - Set frequency: Every 10 minutes (minimum for Heroku Scheduler)
"""


def get_django_q_settings():
    """
    Get Django-Q settings for session lifecycle management.
    
    Returns:
        dict: Django-Q configuration settings
    """
    return DJANGO_Q_SETTINGS


def print_installation_instructions():
    """Print installation and setup instructions."""
    print(INSTALLATION_INSTRUCTIONS)


def print_cron_instructions():
    """Print alternative cron-based setup instructions."""
    print(CRON_INSTRUCTIONS)


# Task monitoring utilities
def get_task_status():
    """
    Get status of periodic tasks.
    
    Returns:
        dict: Task status information
    """
    try:
        from django_q.models import Schedule, Success, Failure
        from django.utils import timezone
        from datetime import timedelta
        
        # Get scheduled tasks
        scheduled_tasks = Schedule.objects.filter(
            func__in=[
                'chats.tasks.update_session_lifecycle_states',
                'chats.tasks.cleanup_old_sessions'
            ]
        )
        
        # Get recent task executions (last 24 hours)
        since = timezone.now() - timedelta(hours=24)
        
        # Session lifecycle task stats
        lifecycle_successes = Success.objects.filter(
            func='chats.tasks.update_session_lifecycle_states',
            stopped__gte=since
        ).count()
        
        lifecycle_failures = Failure.objects.filter(
            func='chats.tasks.update_session_lifecycle_states',
            stopped__gte=since
        ).count()
        
        # Cleanup task stats
        cleanup_successes = Success.objects.filter(
            func='chats.tasks.cleanup_old_sessions',
            stopped__gte=since
        ).count()
        
        cleanup_failures = Failure.objects.filter(
            func='chats.tasks.cleanup_old_sessions',
            stopped__gte=since
        ).count()
        
        return {
            'scheduled_tasks': scheduled_tasks.count(),
            'lifecycle_task': {
                'recent_successes_24h': lifecycle_successes,
                'recent_failures_24h': lifecycle_failures,
                'last_success': Success.objects.filter(
                    func='chats.tasks.update_session_lifecycle_states'
                ).order_by('-stopped').first(),
                'last_failure': Failure.objects.filter(
                    func='chats.tasks.update_session_lifecycle_states'
                ).order_by('-stopped').first(),
            },
            'cleanup_task': {
                'recent_successes_24h': cleanup_successes,
                'recent_failures_24h': cleanup_failures,
                'last_success': Success.objects.filter(
                    func='chats.tasks.cleanup_old_sessions'
                ).order_by('-stopped').first(),
                'last_failure': Failure.objects.filter(
                    func='chats.tasks.cleanup_old_sessions'
                ).order_by('-stopped').first(),
            }
        }
        
    except ImportError:
        return {'error': 'Django-Q not installed'}
    except Exception as e:
        return {'error': str(e)}