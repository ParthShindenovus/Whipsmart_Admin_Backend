"""
Django management command to run session lifecycle updates.

This command can be used as an alternative to Django-Q for running periodic
session state updates. It can be scheduled via cron or other task schedulers.

Usage:
    python manage.py run_session_lifecycle_update
    python manage.py run_session_lifecycle_update --stats  # Show statistics only
    python manage.py run_session_lifecycle_update --verbose  # Verbose output
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from chats.tasks import update_session_lifecycle_states, get_session_lifecycle_stats
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run session lifecycle update task'

    def add_arguments(self, parser):
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Show session statistics only (no state updates)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output',
        )

    def handle(self, *args, **options):
        try:
            if options['verbose']:
                self.stdout.write(f"Starting session lifecycle update at {timezone.now()}")
            
            if options['stats']:
                # Show statistics only
                self.show_statistics(verbose=options['verbose'])
            else:
                # Run the actual update task
                self.run_lifecycle_update(verbose=options['verbose'])
                
        except Exception as e:
            raise CommandError(f"Session lifecycle update failed: {e}")

    def show_statistics(self, verbose=False):
        """Show current session statistics."""
        try:
            if verbose:
                self.stdout.write("Retrieving session statistics...")
            
            stats_result = get_session_lifecycle_stats()
            
            if stats_result['status'] == 'error':
                self.stdout.write(
                    self.style.ERROR(f"Failed to get statistics: {stats_result['error']}")
                )
                return
            
            stats = stats_result['stats']
            
            self.stdout.write(self.style.SUCCESS("Current Session Statistics:"))
            self.stdout.write("-" * 40)
            self.stdout.write(f"ACTIVE sessions:   {stats.get('ACTIVE', 0)}")
            self.stdout.write(f"SNOOZED sessions:  {stats.get('SNOOZED', 0)}")
            self.stdout.write(f"INACTIVE sessions: {stats.get('INACTIVE', 0)}")
            self.stdout.write(f"Total sessions:    {stats.get('total', 0)}")
            
            if verbose:
                self.stdout.write(f"Retrieved at: {stats_result['timestamp']}")
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to show statistics: {e}")
            )

    def run_lifecycle_update(self, verbose=False):
        """Run the session lifecycle update task."""
        try:
            if verbose:
                self.stdout.write("Running session lifecycle update task...")
            
            # Execute the task
            result = update_session_lifecycle_states()
            
            if result['status'] == 'error':
                self.stdout.write(
                    self.style.ERROR(f"Task failed: {result['error']}")
                )
                return
            
            # Display results
            snoozed = result['snoozed_count']
            inactivated = result['inactivated_count']
            total = result['total_processed']
            execution_time = result['execution_time_seconds']
            
            if total > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Session lifecycle update completed: "
                        f"{snoozed} snoozed, {inactivated} inactivated "
                        f"({execution_time:.2f}s)"
                    )
                )
            else:
                message = f"No sessions required state transitions ({execution_time:.2f}s)"
                if verbose:
                    self.stdout.write(self.style.SUCCESS(message))
                else:
                    # For non-verbose mode, only show when there are changes
                    # This reduces log noise when run frequently via cron
                    pass
            
            if verbose:
                self.stdout.write(f"Task completed at: {result['timestamp']}")
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to run lifecycle update: {e}")
            )
            raise