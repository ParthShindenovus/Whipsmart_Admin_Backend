"""
Django management command to set up periodic tasks for session lifecycle management.

This command configures Django-Q scheduled tasks for automated session state updates.
Run this command once to set up the periodic tasks, then ensure Django-Q cluster is running.

Usage:
    python manage.py setup_periodic_tasks
    python manage.py setup_periodic_tasks --remove  # Remove existing tasks
    python manage.py setup_periodic_tasks --status  # Show current task status
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Set up periodic tasks for session lifecycle management'

    def add_arguments(self, parser):
        parser.add_argument(
            '--remove',
            action='store_true',
            help='Remove existing periodic tasks instead of creating them',
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Show status of existing periodic tasks',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        try:
            # Try to import Django-Q components
            from django_q.models import Schedule
            from django_q.tasks import schedule
        except ImportError:
            raise CommandError(
                "Django-Q is not installed. Please install it with: pip install django-q"
            )

        if options['status']:
            self.show_task_status()
            return

        if options['remove']:
            self.remove_periodic_tasks(dry_run=options['dry_run'])
        else:
            self.setup_periodic_tasks(dry_run=options['dry_run'])

    def show_task_status(self):
        """Show status of existing periodic tasks."""
        try:
            from django_q.models import Schedule
            
            self.stdout.write(self.style.SUCCESS("Current Periodic Tasks:"))
            self.stdout.write("-" * 50)
            
            tasks = Schedule.objects.filter(
                func__in=[
                    'chats.tasks.update_session_lifecycle_states',
                    'chats.tasks.cleanup_old_sessions',
                ]
            )
            
            if not tasks.exists():
                self.stdout.write(self.style.WARNING("No periodic tasks found."))
                return
            
            for task in tasks:
                status = "ACTIVE" if task.repeats != 0 else "INACTIVE"
                next_run = task.next_run.strftime('%Y-%m-%d %H:%M:%S') if task.next_run else "N/A"
                
                self.stdout.write(f"Task: {task.name}")
                self.stdout.write(f"  Function: {task.func}")
                
                # Show schedule based on schedule type
                if task.schedule_type == Schedule.MINUTES:
                    self.stdout.write(f"  Schedule: Every {task.minutes} minutes")
                elif task.schedule_type == Schedule.DAILY:
                    self.stdout.write(f"  Schedule: Daily at {task.hour:02d}:{task.minute:02d}")
                else:
                    self.stdout.write(f"  Schedule: {task.schedule_type}")
                
                self.stdout.write(f"  Status: {status}")
                self.stdout.write(f"  Next Run: {next_run}")
                self.stdout.write(f"  Repeats: {task.repeats}")
                self.stdout.write("")
                
        except Exception as e:
            raise CommandError(f"Failed to show task status: {e}")

    def setup_periodic_tasks(self, dry_run=False):
        """Set up periodic tasks for session lifecycle management."""
        try:
            from django_q.models import Schedule
            from django_q.tasks import schedule
            
            self.stdout.write("Setting up periodic tasks for session lifecycle management...")
            
            # Task configurations
            task_configs = [
                {
                    'func': 'chats.tasks.update_session_lifecycle_states',
                    'name': 'Session Lifecycle Update',
                    'schedule_type': Schedule.MINUTES,
                    'minutes': 5,  # Run every 5 minutes
                    'repeats': -1,  # Repeat indefinitely
                },
                {
                    'func': 'chats.tasks.cleanup_old_sessions',
                    'name': 'Session Cleanup',
                    'schedule_type': Schedule.DAILY,
                    'hour': 2,  # Run at 2 AM
                    'minute': 0,  # At the top of the hour
                    'repeats': -1,  # Repeat indefinitely
                }
            ]
            
            if dry_run:
                self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
                for task_config in task_configs:
                    self.stdout.write(f"Would create task: {task_config['name']}")
                    self.stdout.write(f"  Function: {task_config['func']}")
                    if task_config['schedule_type'] == Schedule.MINUTES:
                        self.stdout.write(f"  Schedule: Every {task_config['minutes']} minutes")
                    elif task_config['schedule_type'] == Schedule.DAILY:
                        self.stdout.write(f"  Schedule: Daily at {task_config['hour']:02d}:{task_config['minute']:02d}")
                    self.stdout.write("")
                return
            
            # Process each task configuration
            for task_config in task_configs:
                # Check if task already exists
                existing_task = Schedule.objects.filter(
                    func=task_config['func'],
                    name=task_config['name']
                ).first()
                
                if existing_task:
                    self.stdout.write(
                        self.style.WARNING(f"Task '{task_config['name']}' already exists. Updating...")
                    )
                    # Update existing task
                    existing_task.schedule_type = task_config['schedule_type']
                    if task_config['schedule_type'] == Schedule.MINUTES:
                        existing_task.minutes = task_config['minutes']
                    elif task_config['schedule_type'] == Schedule.DAILY:
                        existing_task.hour = task_config['hour']
                        existing_task.minute = task_config['minute']
                    existing_task.repeats = task_config['repeats']
                    existing_task.next_run = timezone.now()
                    existing_task.save()
                    
                    self.stdout.write(
                        self.style.SUCCESS(f"Updated existing task: {task_config['name']}")
                    )
                else:
                    # Create new scheduled task
                    schedule_kwargs = {
                        'func': task_config['func'],
                        'name': task_config['name'],
                        'schedule_type': task_config['schedule_type'],
                        'repeats': task_config['repeats'],
                        'next_run': timezone.now()
                    }
                    
                    # Add schedule-specific parameters
                    if task_config['schedule_type'] == Schedule.MINUTES:
                        schedule_kwargs['minutes'] = task_config['minutes']
                    elif task_config['schedule_type'] == Schedule.DAILY:
                        schedule_kwargs['hour'] = task_config['hour']
                        schedule_kwargs['minute'] = task_config['minute']
                    
                    scheduled_task = schedule(**schedule_kwargs)
                    
                    self.stdout.write(
                        self.style.SUCCESS(f"Created periodic task: {task_config['name']}")
                    )
                    self.stdout.write(f"  Task ID: {scheduled_task}")
                    self.stdout.write(f"  Function: {task_config['func']}")
                    if task_config['schedule_type'] == Schedule.MINUTES:
                        self.stdout.write(f"  Schedule: Every {task_config['minutes']} minutes")
                    elif task_config['schedule_type'] == Schedule.DAILY:
                        self.stdout.write(f"  Schedule: Daily at {task_config['hour']:02d}:{task_config['minute']:02d}")
            
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Periodic task setup completed!"))
            self.stdout.write("")
            self.stdout.write("Configured tasks:")
            self.stdout.write("1. Session Lifecycle Update - Every 5 minutes")
            self.stdout.write("   - Transitions ACTIVE sessions to SNOOZED after 4 minutes inactivity")
            self.stdout.write("   - Transitions sessions to INACTIVE after 24 hours")
            self.stdout.write("2. Session Cleanup - Daily at 2:00 AM")
            self.stdout.write("   - Deletes INACTIVE sessions older than 30 days")
            self.stdout.write("")
            self.stdout.write("Next steps:")
            self.stdout.write("1. Add 'django_q' to INSTALLED_APPS in settings.py")
            self.stdout.write("2. Configure Django-Q settings in settings.py")
            self.stdout.write("3. Run migrations: python manage.py migrate")
            self.stdout.write("4. Start Django-Q cluster: python manage.py qcluster")
            self.stdout.write("")
            self.stdout.write("The tasks will automatically start running once the cluster is active.")
            
        except Exception as e:
            raise CommandError(f"Failed to set up periodic tasks: {e}")

    def remove_periodic_tasks(self, dry_run=False):
        """Remove existing periodic tasks."""
        try:
            from django_q.models import Schedule
            
            self.stdout.write("Removing periodic tasks for session lifecycle management...")
            
            tasks_to_remove = Schedule.objects.filter(
                func__in=[
                    'chats.tasks.update_session_lifecycle_states',
                    'chats.tasks.cleanup_old_sessions',
                ]
            )
            
            if not tasks_to_remove.exists():
                self.stdout.write(self.style.WARNING("No periodic tasks found to remove."))
                return
            
            if dry_run:
                self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
                for task in tasks_to_remove:
                    self.stdout.write(f"Would remove task: {task.name} ({task.func})")
                return
            
            task_count = tasks_to_remove.count()
            task_names = [task.name for task in tasks_to_remove]
            
            tasks_to_remove.delete()
            
            self.stdout.write(
                self.style.SUCCESS(f"Removed {task_count} periodic task(s):")
            )
            for name in task_names:
                self.stdout.write(f"  - {name}")
                
        except Exception as e:
            raise CommandError(f"Failed to remove periodic tasks: {e}")