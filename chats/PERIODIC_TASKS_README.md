# Session Lifecycle Periodic Tasks

This document explains how to set up and manage periodic tasks for automated session lifecycle management in the IP-based visitor session snoozing system.

## Overview

The periodic task system automatically manages session states by:
- **Session Lifecycle Updates** (every 5 minutes):
  - Transitioning ACTIVE sessions to SNOOZED after 4 minutes of inactivity
  - Transitioning ACTIVE/SNOOZED sessions to INACTIVE after 24 hours from creation
- **Session Cleanup** (daily at 2 AM):
  - Deleting INACTIVE sessions older than 30 days
  - Never deleting Visitor records or ACTIVE/SNOOZED sessions

## Implementation Options

### Option 1: Django-Q (Recommended)

Django-Q provides a robust task queue system with built-in scheduling, monitoring, and failure handling.

#### Setup Steps

1. **Install Django-Q**:
   ```bash
   pip install django-q
   ```

2. **Add to INSTALLED_APPS** in `settings.py`:
   ```python
   INSTALLED_APPS = [
       # ... other apps
       'django_q',
       # ... other apps
   ]
   ```

3. **Add Django-Q Configuration** to `settings.py`:
   ```python
   # Django-Q Configuration
   Q_CLUSTER = {
       'name': 'whipsmart_session_tasks',
       'workers': 2,
       'recycle': 500,
       'timeout': 300,
       'compress': True,
       'save_limit': 250,
       'queue_limit': 500,
       'cpu_affinity': 1,
       'label': 'Session Lifecycle Tasks',
       'orm': 'default',  # Use Django database as broker
       'retry': 3600,
       'max_attempts': 3,
       'catch_up': True,
       'sync': False,
   }
   ```

4. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Set Up Periodic Tasks**:
   ```bash
   python manage.py setup_periodic_tasks
   ```

6. **Start Django-Q Cluster**:
   ```bash
   python manage.py qcluster
   ```

#### Management Commands

- **Setup tasks**: `python manage.py setup_periodic_tasks`
- **Remove tasks**: `python manage.py setup_periodic_tasks --remove`
- **Check status**: `python manage.py setup_periodic_tasks --status`
- **Dry run**: `python manage.py setup_periodic_tasks --dry-run`

#### Monitoring

- Access Django admin panel
- Navigate to "Django Q" section
- Monitor scheduled tasks, successes, and failures
- View task execution history and performance

Both tasks (lifecycle updates and cleanup) will be visible in the monitoring interface.

### Option 2: Cron Jobs (Alternative)

For simpler deployments or when Django-Q is not desired, use cron jobs.

#### Setup Steps

1. **Create Cron Jobs** (session lifecycle every 5 minutes, cleanup daily at 2 AM):
   ```bash
   crontab -e
   ```
   
   Add these lines:
   ```
   */5 * * * * /path/to/your/venv/bin/python /path/to/your/project/manage.py run_session_lifecycle_update
   0 2 * * * /path/to/your/venv/bin/python /path/to/your/project/manage.py cleanup_sessions
   ```

2. **For Heroku** (use Heroku Scheduler addon):
   ```bash
   heroku addons:create scheduler:standard
   ```
   
   Configure jobs in Heroku dashboard:
   - **Session Lifecycle**: 
     - Command: `python manage.py run_session_lifecycle_update`
     - Frequency: Every 10 minutes (Heroku minimum)
   - **Session Cleanup**:
     - Command: `python manage.py cleanup_sessions`
     - Frequency: Daily at 2:00 AM

#### Management Commands

- **Run lifecycle update**: `python manage.py run_session_lifecycle_update`
- **Run cleanup**: `python manage.py cleanup_sessions`
- **Show stats**: `python manage.py run_session_lifecycle_update --stats`
- **Cleanup dry run**: `python manage.py cleanup_sessions --dry-run`
- **Verbose output**: `python manage.py run_session_lifecycle_update --verbose`

## Task Configuration

### Core Task Function

The main task function is `chats.tasks.update_session_lifecycle_states()`:

```python
def update_session_lifecycle_states() -> Dict[str, Any]:
    """
    Periodic task to update session states based on lifecycle rules.
    
    Returns:
        dict: Task execution results with counts and status
    """
```

### Task Schedule

- **Session Lifecycle Updates**:
  - **Frequency**: Every 5 minutes
  - **Timeout**: 5 minutes (300 seconds)
  - **Function**: `chats.tasks.update_session_lifecycle_states()`
- **Session Cleanup**:
  - **Frequency**: Daily at 2:00 AM
  - **Timeout**: 5 minutes (300 seconds)
  - **Function**: `chats.tasks.cleanup_old_sessions()`
- **Retry**: Failed tasks retry after 1 hour
- **Max Attempts**: 3 retry attempts

### Error Handling

Both tasks include comprehensive error handling:
- Database transaction safety
- Detailed logging of successes and failures
- Graceful degradation on errors
- Structured error reporting

### Logging

Task execution is logged with different levels:
- **INFO**: Successful executions with session counts
- **DEBUG**: No-change executions and detailed statistics
- **ERROR**: Task failures with full stack traces

### Statistics

Get current session statistics:
```bash
python manage.py run_session_lifecycle_update --stats
```

Get cleanup statistics:
```bash
python manage.py cleanup_sessions --stats
```

### Django-Q Monitoring

If using Django-Q, monitor tasks via:
1. Django admin panel → Django Q section
2. Command line: `python manage.py setup_periodic_tasks --status`
3. Programmatic access via `chats.django_q_config.get_task_status()`

## Production Deployment

### Django-Q Production Setup

1. **Use Redis as Broker** (instead of Django ORM):
   ```python
   Q_CLUSTER = {
       # ... other settings
       'redis': {
           'host': 'your-redis-host',
           'port': 6379,
           'db': 0,
           'password': 'your-redis-password',
       },
       # Remove 'orm': 'default' when using Redis
   }
   ```

2. **Run as Service**:
   - Create systemd service file for `qcluster`
   - Ensure automatic restart on failure
   - Monitor process health

3. **Scaling**:
   - Increase worker count for high-volume deployments
   - Monitor memory usage and adjust `recycle` setting
   - Use multiple clusters if needed

### Cron Production Setup

1. **System Cron** (preferred over user cron):
   ```bash
   sudo crontab -e
   ```

2. **Logging**:
   ```
   */5 * * * * /path/to/venv/bin/python /path/to/project/manage.py run_session_lifecycle_update >> /var/log/session_lifecycle.log 2>&1
   0 2 * * * /path/to/venv/bin/python /path/to/project/manage.py cleanup_sessions >> /var/log/session_cleanup.log 2>&1
   ```

3. **Monitoring**:
   - Set up log rotation for task logs
   - Monitor cron execution via system logs
   - Alert on task failures

## Troubleshooting

### Common Issues

1. **Django-Q not starting**:
   - Check Redis connection (if using Redis)
   - Verify Django-Q is in INSTALLED_APPS
   - Check database migrations are applied

2. **Tasks not running**:
   - Verify qcluster is running
   - Check scheduled tasks exist: `python manage.py setup_periodic_tasks --status`
   - Review Django-Q logs in admin panel

3. **High memory usage**:
   - Reduce `save_limit` in Q_CLUSTER settings
   - Increase `recycle` to restart workers more frequently
   - Monitor task execution time

4. **Cron jobs not executing**:
   - Check cron service is running: `sudo service cron status`
   - Verify cron syntax and paths
   - Check system logs: `grep CRON /var/log/syslog`

5. **Cleanup task issues**:
   - Check cleanup service logs for errors
   - Verify INACTIVE sessions exist for cleanup
   - Test with dry-run: `python manage.py cleanup_sessions --dry-run`

### Performance Tuning

1. **Batch Size**: The task processes all eligible sessions in batches using database transactions
2. **Execution Time**: Monitor task execution time and adjust timeout if needed
3. **Frequency**: 5-minute frequency balances responsiveness with system load
4. **Database Indexes**: Ensure proper indexes exist on session status and timestamp fields

## Files Overview

- `chats/tasks.py` - Core task functions (lifecycle updates and cleanup)
- `chats/django_q_config.py` - Django-Q configuration and utilities
- `chats/management/commands/setup_periodic_tasks.py` - Django-Q task setup
- `chats/management/commands/run_session_lifecycle_update.py` - Direct lifecycle task execution
- `chats/management/commands/cleanup_sessions.py` - Direct cleanup task execution
- `chats/session_lifecycle_manager.py` - Core session lifecycle logic
- `chats/cleanup_service.py` - Core cleanup logic

## Testing

Test the task system:

1. **Manual Execution**:
   ```bash
   python manage.py run_session_lifecycle_update --verbose
   python manage.py cleanup_sessions --verbose
   ```

2. **Statistics Check**:
   ```bash
   python manage.py run_session_lifecycle_update --stats
   python manage.py cleanup_sessions --stats
   ```

3. **Dry Run Cleanup**:
   ```bash
   python manage.py cleanup_sessions --dry-run
   ```

4. **Django-Q Test**:
   ```python
   from chats.tasks import update_session_lifecycle_states, cleanup_old_sessions
   
   # Test lifecycle updates
   lifecycle_result = update_session_lifecycle_states()
   print(lifecycle_result)
   
   # Test cleanup
   cleanup_result = cleanup_old_sessions()
   print(cleanup_result)
   ```

This comprehensive setup ensures reliable, automated session lifecycle management with proper monitoring and error handling capabilities.