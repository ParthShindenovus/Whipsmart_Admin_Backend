"""
Django management command for cleaning up old inactive sessions.

This command:
1. Deletes INACTIVE sessions older than 30 days
2. Never deletes Visitor records
3. Never deletes ACTIVE or SNOOZED sessions
4. Provides dry-run and verbosity options
5. Logs the number of sessions deleted

Usage:
    python manage.py cleanup_sessions                    # Normal cleanup
    python manage.py cleanup_sessions --dry-run          # Show what would be deleted
    python manage.py cleanup_sessions --verbosity=2      # Verbose output
    python manage.py cleanup_sessions --dry-run -v 2     # Dry run with verbose output

Run this command periodically (e.g., daily) via cronjob or task scheduler.
For Heroku, use Heroku Scheduler addon.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from chats.cleanup_service import CleanupService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up old inactive sessions (INACTIVE sessions older than 30 days)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting anything',
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Show cleanup statistics without performing cleanup',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        show_stats = options['stats']
        verbosity = options['verbosity']
        
        # Configure output style based on verbosity
        if verbosity >= 2:
            self.stdout.write(self.style.SUCCESS('Starting session cleanup command...'))
            self.stdout.write(f'Current time: {timezone.now()}')
            self.stdout.write(f'Dry run mode: {dry_run}')
            self.stdout.write(f'Show stats only: {show_stats}')
        
        try:
            # Show statistics if requested
            if show_stats:
                self._show_cleanup_stats(verbosity)
                return
            
            # Perform dry run if requested
            if dry_run:
                self._perform_dry_run(verbosity)
                return
            
            # Perform actual cleanup
            self._perform_cleanup(verbosity)
            
        except Exception as e:
            logger.error(f"Error in cleanup_sessions command: {e}", exc_info=True)
            raise CommandError(f'Cleanup command failed: {e}')

    def _show_cleanup_stats(self, verbosity):
        """Show cleanup statistics without performing any cleanup."""
        if verbosity >= 1:
            self.stdout.write(self.style.HTTP_INFO('Fetching cleanup statistics...'))
        
        try:
            stats = CleanupService.get_cleanup_stats()
            
            if 'error' in stats:
                self.stdout.write(
                    self.style.ERROR(f'Error getting cleanup stats: {stats["error"]}')
                )
                return
            
            # Display statistics
            self.stdout.write(self.style.SUCCESS('\n=== CLEANUP STATISTICS ==='))
            self.stdout.write(f'Total sessions in database: {stats["total_sessions"]}')
            self.stdout.write(f'Total visitors in database: {stats["total_visitors"]} (never deleted)')
            self.stdout.write(f'ACTIVE/SNOOZED sessions: {stats["cleanup_protected"]} (protected from cleanup)')
            self.stdout.write(f'Total INACTIVE sessions: {stats["total_inactive"]}')
            self.stdout.write(
                self.style.WARNING(
                    f'INACTIVE sessions eligible for cleanup: {stats["cleanup_eligible"]}'
                )
            )
            self.stdout.write(f'Cutoff time (30 days ago): {stats["cutoff_time"]}')
            
            if verbosity >= 2:
                self.stdout.write(f'\nDetailed breakdown:')
                self.stdout.write(f'  - Sessions that will be preserved: {stats["cleanup_protected"] + stats["total_inactive"] - stats["cleanup_eligible"]}')
                self.stdout.write(f'  - Sessions eligible for deletion: {stats["cleanup_eligible"]}')
            
        except Exception as e:
            logger.error(f"Error getting cleanup statistics: {e}", exc_info=True)
            self.stdout.write(
                self.style.ERROR(f'Failed to get cleanup statistics: {e}')
            )

    def _perform_dry_run(self, verbosity):
        """Perform a dry run showing what would be deleted."""
        if verbosity >= 1:
            self.stdout.write(self.style.WARNING('=== DRY RUN MODE ==='))
            self.stdout.write('No sessions will actually be deleted.')
        
        try:
            dry_run_result = CleanupService.dry_run_cleanup()
            
            if 'error' in dry_run_result:
                self.stdout.write(
                    self.style.ERROR(f'Error in dry run: {dry_run_result["error"]}')
                )
                return
            
            sessions_to_delete = dry_run_result['sessions_to_delete']
            cutoff_time = dry_run_result['cutoff_time']
            sample_sessions = dry_run_result['sample_sessions']
            
            if sessions_to_delete == 0:
                self.stdout.write(
                    self.style.SUCCESS('No INACTIVE sessions found that are older than 30 days.')
                )
                self.stdout.write('Nothing would be deleted.')
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'Would delete {sessions_to_delete} INACTIVE sessions older than {cutoff_time}'
                    )
                )
                
                if verbosity >= 2 and sample_sessions:
                    self.stdout.write(f'\nSample session IDs that would be deleted:')
                    for session_id in sample_sessions:
                        self.stdout.write(f'  - {session_id}')
                    
                    if len(sample_sessions) == 10 and sessions_to_delete > 10:
                        self.stdout.write(f'  ... and {sessions_to_delete - 10} more sessions')
            
            if verbosity >= 1:
                self.stdout.write(
                    self.style.HTTP_INFO(
                        f'\nTo perform actual cleanup, run: python manage.py cleanup_sessions'
                    )
                )
            
        except Exception as e:
            logger.error(f"Error in dry run cleanup: {e}", exc_info=True)
            self.stdout.write(
                self.style.ERROR(f'Dry run failed: {e}')
            )

    def _perform_cleanup(self, verbosity):
        """Perform the actual cleanup operation."""
        if verbosity >= 1:
            self.stdout.write(self.style.HTTP_INFO('=== PERFORMING CLEANUP ==='))
            self.stdout.write('Deleting INACTIVE sessions older than 30 days...')
        
        try:
            # Perform the cleanup
            deleted_count = CleanupService.cleanup_old_sessions()
            
            if deleted_count == 0:
                self.stdout.write(
                    self.style.SUCCESS('No INACTIVE sessions found that are older than 30 days.')
                )
                self.stdout.write('No cleanup was necessary.')
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully deleted {deleted_count} INACTIVE sessions older than 30 days.'
                    )
                )
                
                if verbosity >= 2:
                    self.stdout.write(f'\nCleanup completed at: {timezone.now()}')
                    self.stdout.write('All Visitor records were preserved.')
                    self.stdout.write('All ACTIVE and SNOOZED sessions were preserved.')
            
            # Show final statistics if verbose
            if verbosity >= 2:
                self.stdout.write(self.style.HTTP_INFO('\n=== POST-CLEANUP STATISTICS ==='))
                try:
                    stats = CleanupService.get_cleanup_stats()
                    if 'error' not in stats:
                        self.stdout.write(f'Remaining total sessions: {stats["total_sessions"]}')
                        self.stdout.write(f'Remaining INACTIVE sessions: {stats["total_inactive"]}')
                        self.stdout.write(f'Protected sessions (ACTIVE/SNOOZED): {stats["cleanup_protected"]}')
                        self.stdout.write(f'Total visitors (unchanged): {stats["total_visitors"]}')
                except Exception as e:
                    logger.warning(f"Could not get post-cleanup statistics: {e}")
            
        except Exception as e:
            logger.error(f"Error during cleanup operation: {e}", exc_info=True)
            self.stdout.write(
                self.style.ERROR(f'Cleanup operation failed: {e}')
            )
            raise CommandError(f'Cleanup failed: {e}')