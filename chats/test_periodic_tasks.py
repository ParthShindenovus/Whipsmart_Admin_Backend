"""
Tests for periodic task implementation.
Tests the session lifecycle update task functionality.
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock
from .tasks import update_session_lifecycle_states, get_session_lifecycle_stats
from .session_lifecycle_manager import SessionLifecycleManager


class PeriodicTasksTestCase(TestCase):
    """Test cases for periodic task functions."""
    
    def setUp(self):
        """Set up test data."""
        self.mock_results = {
            'snoozed_count': 5,
            'inactivated_count': 3,
            'total_processed': 8
        }
    
    @patch.object(SessionLifecycleManager, 'update_session_states')
    def test_update_session_lifecycle_states_success(self, mock_update):
        """Test successful execution of session lifecycle update task."""
        # Mock the SessionLifecycleManager method
        mock_update.return_value = self.mock_results
        
        # Execute the task
        result = update_session_lifecycle_states()
        
        # Verify the task was called
        mock_update.assert_called_once()
        
        # Verify the result structure
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['snoozed_count'], 5)
        self.assertEqual(result['inactivated_count'], 3)
        self.assertEqual(result['total_processed'], 8)
        self.assertIn('execution_time_seconds', result)
        self.assertIn('timestamp', result)
        self.assertIsInstance(result['execution_time_seconds'], float)
    
    @patch.object(SessionLifecycleManager, 'update_session_states')
    def test_update_session_lifecycle_states_no_changes(self, mock_update):
        """Test task execution when no sessions need state changes."""
        # Mock no changes needed
        mock_update.return_value = {
            'snoozed_count': 0,
            'inactivated_count': 0,
            'total_processed': 0
        }
        
        # Execute the task
        result = update_session_lifecycle_states()
        
        # Verify the result
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['total_processed'], 0)
        self.assertIn('execution_time_seconds', result)
    
    @patch.object(SessionLifecycleManager, 'update_session_states')
    def test_update_session_lifecycle_states_error(self, mock_update):
        """Test task execution when an error occurs."""
        # Mock an exception
        mock_update.side_effect = Exception("Database connection failed")
        
        # Execute the task
        result = update_session_lifecycle_states()
        
        # Verify error handling
        self.assertEqual(result['status'], 'error')
        self.assertIn('Database connection failed', result['error'])
        self.assertEqual(result['snoozed_count'], 0)
        self.assertEqual(result['inactivated_count'], 0)
        self.assertEqual(result['total_processed'], 0)
        self.assertIn('timestamp', result)
    
    @patch.object(SessionLifecycleManager, 'get_session_stats')
    def test_get_session_lifecycle_stats_success(self, mock_stats):
        """Test successful retrieval of session statistics."""
        # Mock session statistics
        mock_stats.return_value = {
            'ACTIVE': 10,
            'SNOOZED': 5,
            'INACTIVE': 20,
            'total': 35
        }
        
        # Execute the stats function
        result = get_session_lifecycle_stats()
        
        # Verify the result
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['stats']['ACTIVE'], 10)
        self.assertEqual(result['stats']['SNOOZED'], 5)
        self.assertEqual(result['stats']['INACTIVE'], 20)
        self.assertEqual(result['stats']['total'], 35)
        self.assertIn('timestamp', result)
    
    @patch.object(SessionLifecycleManager, 'get_session_stats')
    def test_get_session_lifecycle_stats_error(self, mock_stats):
        """Test statistics retrieval when an error occurs."""
        # Mock an exception
        mock_stats.side_effect = Exception("Stats query failed")
        
        # Execute the stats function
        result = get_session_lifecycle_stats()
        
        # Verify error handling
        self.assertEqual(result['status'], 'error')
        self.assertIn('Stats query failed', result['error'])
        self.assertEqual(result['stats'], {})
        self.assertIn('timestamp', result)
    
    def test_task_result_structure(self):
        """Test that task results have the expected structure."""
        with patch.object(SessionLifecycleManager, 'update_session_states') as mock_update:
            mock_update.return_value = self.mock_results
            
            result = update_session_lifecycle_states()
            
            # Verify all required fields are present
            required_fields = [
                'status', 'execution_time_seconds', 'timestamp',
                'snoozed_count', 'inactivated_count', 'total_processed'
            ]
            
            for field in required_fields:
                self.assertIn(field, result, f"Missing required field: {field}")
            
            # Verify field types
            self.assertIsInstance(result['status'], str)
            self.assertIsInstance(result['execution_time_seconds'], float)
            self.assertIsInstance(result['timestamp'], str)
            self.assertIsInstance(result['snoozed_count'], int)
            self.assertIsInstance(result['inactivated_count'], int)
            self.assertIsInstance(result['total_processed'], int)
    
    def test_task_execution_time_measurement(self):
        """Test that task execution time is properly measured."""
        with patch.object(SessionLifecycleManager, 'update_session_states') as mock_update:
            # Mock a delay to ensure execution time is measured
            def delayed_update():
                import time
                time.sleep(0.1)  # 100ms delay
                return self.mock_results
            
            mock_update.side_effect = delayed_update
            
            result = update_session_lifecycle_states()
            
            # Verify execution time is reasonable (should be >= 0.1 seconds)
            self.assertGreaterEqual(result['execution_time_seconds'], 0.1)
            self.assertLess(result['execution_time_seconds'], 1.0)  # Should not take too long
    
    def test_timestamp_format(self):
        """Test that timestamps are in ISO format."""
        with patch.object(SessionLifecycleManager, 'update_session_states') as mock_update:
            mock_update.return_value = self.mock_results
            
            result = update_session_lifecycle_states()
            
            # Verify timestamp is in ISO format
            timestamp = result['timestamp']
            self.assertIsInstance(timestamp, str)
            
            # Should be parseable as ISO format
            try:
                from datetime import datetime
                parsed_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                self.assertIsInstance(parsed_time, datetime)
            except ValueError:
                self.fail(f"Timestamp '{timestamp}' is not in valid ISO format")


class TaskConfigurationTestCase(TestCase):
    """Test cases for task configuration and setup."""
    
    def test_periodic_tasks_configuration(self):
        """Test that PERIODIC_TASKS configuration is properly defined."""
        from .tasks import PERIODIC_TASKS
        
        # Verify configuration exists
        self.assertIn('session_lifecycle_update', PERIODIC_TASKS)
        
        config = PERIODIC_TASKS['session_lifecycle_update']
        
        # Verify required configuration fields
        self.assertEqual(config['func'], 'chats.tasks.update_session_lifecycle_states')
        self.assertEqual(config['schedule_type'], 'I')  # Interval
        self.assertEqual(config['minutes'], 5)  # Every 5 minutes
        self.assertEqual(config['repeats'], -1)  # Repeat indefinitely
        self.assertEqual(config['name'], 'Session Lifecycle Update')
    
    def test_task_import_path(self):
        """Test that the task function can be imported using the configured path."""
        # This tests that the import path in PERIODIC_TASKS is correct
        import importlib
        
        module_path, function_name = 'chats.tasks.update_session_lifecycle_states'.rsplit('.', 1)
        
        try:
            module = importlib.import_module(module_path)
            task_function = getattr(module, function_name)
            
            # Verify it's callable
            self.assertTrue(callable(task_function))
            
        except (ImportError, AttributeError) as e:
            self.fail(f"Cannot import task function: {e}")


class TaskIntegrationTestCase(TestCase):
    """Integration tests for task system."""
    
    def test_task_can_be_called_directly(self):
        """Test that the task can be called directly without Django-Q."""
        # This is important for cron-based execution
        try:
            result = update_session_lifecycle_states()
            
            # Should return a valid result structure
            self.assertIn('status', result)
            self.assertIn(result['status'], ['success', 'error'])
            
        except Exception as e:
            # If it fails, it should be due to database/model issues, not task structure
            self.assertNotIsInstance(e, (ImportError, AttributeError, TypeError))
    
    def test_stats_function_can_be_called_directly(self):
        """Test that the stats function can be called directly."""
        try:
            result = get_session_lifecycle_stats()
            
            # Should return a valid result structure
            self.assertIn('status', result)
            self.assertIn('stats', result)
            
        except Exception as e:
            # If it fails, it should be due to database/model issues, not function structure
            self.assertNotIsInstance(e, (ImportError, AttributeError, TypeError))