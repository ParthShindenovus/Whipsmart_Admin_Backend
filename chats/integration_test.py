"""
Integration test for IP-based visitor identity and session snoozing system.
Tests the complete flow from IP resolution to session management.
"""
import logging
from django.test import TestCase, RequestFactory
from django.utils import timezone
from datetime import timedelta
from unittest.mock import Mock, patch
from chats.models import Visitor, Session, ChatMessage
from chats.ip_resolver import IPResolver
from chats.session_manager import SessionManager
from chats.session_lifecycle_manager import SessionLifecycleManager
from chats.snooze_handler import SnoozeHandler
from chats.cleanup_service import CleanupService
from agents.langgraph_agent.integration import ChatAPIIntegration, RESTAPIAdapter, WebSocketAdapter

logger = logging.getLogger(__name__)


class IntegrationTestCase(TestCase):
    """Integration tests for the complete IP-based visitor and session system."""
    
    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.test_ip = '192.168.1.100'
        self.test_ipv6 = '2001:db8::1'
    
    def test_complete_rest_api_flow(self):
        """Test complete flow through REST API integration."""
        # Create a mock request with IP
        request = self.factory.post('/api/chat/')
        request.META['HTTP_X_FORWARDED_FOR'] = self.test_ip
        
        # Test session creation
        result = RESTAPIAdapter.create_session(request)
        
        self.assertTrue(result['success'])
        self.assertIn('session_id', result)
        self.assertIn('visitor_id', result)
        self.assertFalse(result['existing_session'])
        
        session_id = result['session_id']
        visitor_id = result['visitor_id']
        
        # Verify visitor was created with correct IP
        visitor = Visitor.objects.get(id=visitor_id)
        self.assertEqual(visitor.ip_address, self.test_ip)
        
        # Verify session was created with ACTIVE status
        session = Session.objects.get(id=session_id)
        self.assertEqual(session.status, Session.Status.ACTIVE)
        self.assertEqual(session.visitor.id, visitor.id)
        
        # Test that second request returns existing session
        result2 = RESTAPIAdapter.create_session(request)
        self.assertTrue(result2['success'])
        self.assertEqual(result2['session_id'], session_id)
        self.assertTrue(result2['existing_session'])
    
    def test_complete_websocket_flow(self):
        """Test complete flow through WebSocket integration."""
        # Create a mock WebSocket scope with IP
        scope = {
            'headers': [
                (b'x-forwarded-for', self.test_ip.encode())
            ]
        }
        
        # Test session creation
        result = WebSocketAdapter.create_session(scope)
        
        self.assertTrue(result['success'])
        self.assertIn('session_id', result)
        self.assertIn('visitor_id', result)
        
        session_id = result['session_id']
        visitor_id = result['visitor_id']
        
        # Verify visitor was created with correct IP
        visitor = Visitor.objects.get(id=visitor_id)
        self.assertEqual(visitor.ip_address, self.test_ip)
        
        # Verify session was created with ACTIVE status
        session = Session.objects.get(id=session_id)
        self.assertEqual(session.status, Session.Status.ACTIVE)
        self.assertEqual(session.visitor.id, visitor.id)
    
    def test_ip_consistency_across_entry_points(self):
        """Test that same IP resolves to same visitor across REST and WebSocket."""
        # Create visitor via REST API
        request = self.factory.post('/api/chat/')
        request.META['REMOTE_ADDR'] = self.test_ip
        
        rest_result = RESTAPIAdapter.create_session(request)
        rest_visitor_id = rest_result['visitor_id']
        
        # Create visitor via WebSocket with same IP
        scope = {
            'client': [self.test_ip, 12345]
        }
        
        ws_result = WebSocketAdapter.create_session(scope)
        ws_visitor_id = ws_result['visitor_id']
        
        # Should resolve to same visitor
        self.assertEqual(rest_visitor_id, ws_visitor_id)
    
    def test_profile_persistence_across_sessions(self):
        """Test that user profile persists across multiple sessions."""
        # Create initial session and collect profile data
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        session1 = SessionManager.create_session(visitor)
        
        # Collect user info using integration layer
        profile_result = ChatAPIIntegration.collect_user_info(
            str(session1.id),
            name="John Doe",
            email="john@example.com",
            phone="+1234567890"
        )
        
        self.assertTrue(profile_result['success'])
        
        # Verify profile is stored on visitor
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "John Doe")
        self.assertEqual(visitor.email, "john@example.com")
        self.assertEqual(visitor.phone, "+1234567890")
        
        # Create new session for same visitor
        session2 = SessionManager.create_session(visitor)
        
        # Profile should be available in new session
        request = self.factory.post('/api/chat/')
        request.META['REMOTE_ADDR'] = self.test_ip
        
        chat_result = RESTAPIAdapter.handle_chat_request(
            request, str(session2.id), "Hello"
        )
        
        # Should include visitor profile
        self.assertIn('visitor_profile', chat_result)
        profile = chat_result['visitor_profile']
        self.assertEqual(profile['name'], "John Doe")
        self.assertEqual(profile['email'], "john@example.com")
        self.assertEqual(profile['phone'], "+1234567890")
    
    def test_session_lifecycle_transitions(self):
        """Test session lifecycle transitions in realistic scenarios."""
        # Create visitor and session
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        session = SessionManager.create_session(visitor)
        
        # Initially should be ACTIVE
        self.assertEqual(session.status, Session.Status.ACTIVE)
        
        # Simulate 5 minutes of inactivity (past snooze timeout)
        past_time = timezone.now() - timedelta(minutes=5)
        session.last_message_at = past_time
        session.save(update_fields=['last_message_at'])
        
        # Run lifecycle update
        results = SessionLifecycleManager.update_session_states()
        
        # Session should be snoozed
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.SNOOZED)
        self.assertEqual(results['snoozed_count'], 1)
        
        # Test reactivation
        SessionManager.reactivate_session(session)
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.ACTIVE)
        
        # Simulate 25 hours old session (past inactive timeout) - use bulk_update
        old_time = timezone.now() - timedelta(hours=25)
        Session.objects.filter(id=session.id).update(created_at=old_time)
        
        # Run lifecycle update again
        results = SessionLifecycleManager.update_session_states()
        
        # Session should be inactive
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.INACTIVE)
        self.assertEqual(results['inactivated_count'], 1)
    
    def test_session_visibility_management(self):
        """Test that session visibility is managed correctly."""
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        
        # Create sessions with different statuses
        active_session = SessionManager.create_session(visitor)
        snoozed_session = SessionManager.create_session(visitor)
        inactive_session = SessionManager.create_session(visitor)
        
        # Set different statuses
        SessionManager.transition_to_snoozed(snoozed_session)
        SessionManager.transition_to_inactive(inactive_session)
        
        # Refresh sessions from database to get updated status
        active_session.refresh_from_db()
        snoozed_session.refresh_from_db()
        inactive_session.refresh_from_db()
        
        # Query for visible sessions (ACTIVE and SNOOZED only)
        visible_sessions = Session.objects.filter(
            visitor=visitor,
            status__in=[Session.Status.ACTIVE, Session.Status.SNOOZED]
        )
        
        visible_list = list(visible_sessions)
        self.assertEqual(len(visible_list), 2)
        self.assertIn(active_session, visible_list)
        self.assertIn(snoozed_session, visible_list)
        self.assertNotIn(inactive_session, visible_list)
    
    def test_cleanup_service_integration(self):
        """Test cleanup service integration with session lifecycle."""
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        
        # Create sessions with different ages and statuses
        old_inactive_session = SessionManager.create_session(visitor)
        recent_inactive_session = SessionManager.create_session(visitor)
        old_active_session = SessionManager.create_session(visitor)
        
        # Make sessions inactive
        SessionManager.transition_to_inactive(old_inactive_session)
        SessionManager.transition_to_inactive(recent_inactive_session)
        
        # Make one session old (35 days) - use bulk_update since created_at has auto_now_add=True
        old_time = timezone.now() - timedelta(days=35)
        
        # Use bulk_update to bypass auto_now_add restriction
        Session.objects.filter(id=old_inactive_session.id).update(created_at=old_time)
        Session.objects.filter(id=old_active_session.id).update(created_at=old_time)
        
        # Refresh sessions to verify the update
        old_inactive_session.refresh_from_db()
        old_active_session.refresh_from_db()
        
        # Run cleanup
        deleted_count = CleanupService.cleanup_old_sessions()
        
        # Only old inactive session should be deleted
        self.assertEqual(deleted_count, 1)
        
        # Verify correct sessions remain
        self.assertFalse(Session.objects.filter(id=old_inactive_session.id).exists())
        self.assertTrue(Session.objects.filter(id=recent_inactive_session.id).exists())
        self.assertTrue(Session.objects.filter(id=old_active_session.id).exists())
        
        # Visitor should never be deleted
        self.assertTrue(Visitor.objects.filter(id=visitor.id).exists())
    
    def test_snooze_handler_integration(self):
        """Test snooze handler integration with session management."""
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        session = SessionManager.create_session(visitor)
        
        # Make session inactive for more than 4 minutes
        past_time = timezone.now() - timedelta(minutes=5)
        session.last_message_at = past_time
        session.save(update_fields=['last_message_at'])
        
        # Run snooze handler
        snoozed_count = SnoozeHandler.check_and_snooze_inactive_sessions()
        
        # Session should be snoozed
        self.assertEqual(snoozed_count, 1)
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.SNOOZED)
    
    def test_ipv6_support_integration(self):
        """Test that IPv6 addresses work throughout the system."""
        # Test IPv6 through complete flow
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ipv6)
        session = SessionManager.create_session(visitor)
        
        # Verify IPv6 is stored correctly
        self.assertEqual(visitor.ip_address, self.test_ipv6)
        
        # Test through REST API
        request = self.factory.post('/api/chat/')
        request.META['REMOTE_ADDR'] = self.test_ipv6
        
        result = RESTAPIAdapter.create_session(request)
        self.assertTrue(result['success'])
        
        # Should resolve to same visitor
        self.assertEqual(result['visitor_id'], str(visitor.id))
    
    def test_error_handling_integration(self):
        """Test error handling across integration points."""
        # Test invalid IP handling - should return error result, not raise exception
        request = self.factory.post('/api/chat/')
        request.META['REMOTE_ADDR'] = 'invalid-ip'
        
        # Should handle gracefully and return error result
        result = RESTAPIAdapter.create_session(request)
        self.assertFalse(result['success'])
        self.assertIn('error', result)
        
        # Test missing session handling
        request.META['REMOTE_ADDR'] = self.test_ip
        fake_session_id = '00000000-0000-0000-0000-000000000000'
        
        result = RESTAPIAdapter.handle_chat_request(
            request, fake_session_id, "Hello"
        )
        
        self.assertFalse(result['success'])
        self.assertIn('error', result)
    
    def test_concurrent_access_handling(self):
        """Test handling of concurrent access to same IP."""
        # Simulate race condition where multiple requests come from same IP
        visitor1 = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        visitor2 = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        
        # Should resolve to same visitor
        self.assertEqual(visitor1.id, visitor2.id)
        
        # Should only have one visitor with this IP
        self.assertEqual(Visitor.objects.filter(ip_address=self.test_ip).count(), 1)
    
    def test_last_seen_at_updates_integration(self):
        """Test that last_seen_at updates work throughout the system."""
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        original_last_seen = visitor.last_seen_at
        
        # Wait a moment
        import time
        time.sleep(0.01)
        
        # Access through different entry points
        request = self.factory.post('/api/chat/')
        request.META['REMOTE_ADDR'] = self.test_ip
        
        RESTAPIAdapter.create_session(request)
        
        # Visitor should have updated timestamp
        visitor.refresh_from_db()
        self.assertGreater(visitor.last_seen_at, original_last_seen)
    
    def test_session_reactivation_integration(self):
        """Test session reactivation through API calls."""
        visitor = IPResolver.get_or_create_visitor_from_ip(self.test_ip)
        session = SessionManager.create_session(visitor)
        
        # Snooze the session
        SessionManager.transition_to_snoozed(session)
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.SNOOZED)
        
        # Make API call - should reactivate session
        request = self.factory.post('/api/chat/')
        request.META['REMOTE_ADDR'] = self.test_ip
        
        result = RESTAPIAdapter.handle_chat_request(
            request, str(session.id), "Hello"
        )
        
        # Session should be reactivated
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.ACTIVE)
    
    def test_complete_user_journey_integration(self):
        """Test a complete user journey from start to finish."""
        # 1. User connects via REST API
        request = self.factory.post('/api/chat/')
        request.META['HTTP_X_FORWARDED_FOR'] = self.test_ip
        
        session_result = RESTAPIAdapter.create_session(request)
        self.assertTrue(session_result['success'])
        
        session_id = session_result['session_id']
        visitor_id = session_result['visitor_id']
        
        # 2. User provides profile information
        profile_result = ChatAPIIntegration.collect_user_info(
            session_id,
            name="Jane Smith",
            email="jane@example.com"
        )
        self.assertTrue(profile_result['success'])
        
        # 3. Session becomes inactive and gets snoozed
        session = Session.objects.get(id=session_id)
        past_time = timezone.now() - timedelta(minutes=5)
        session.last_message_at = past_time
        session.save(update_fields=['last_message_at'])
        
        SessionLifecycleManager.update_session_states()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.SNOOZED)
        
        # 4. User returns and session is reactivated
        chat_result = RESTAPIAdapter.handle_chat_request(
            request, session_id, "I'm back"
        )
        
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.ACTIVE)
        
        # 5. Profile data is still available
        self.assertIn('visitor_profile', chat_result)
        profile = chat_result['visitor_profile']
        self.assertEqual(profile['name'], "Jane Smith")
        self.assertEqual(profile['email'], "jane@example.com")
        
        # 6. Session eventually becomes inactive after 24 hours - use bulk_update
        old_time = timezone.now() - timedelta(hours=25)
        Session.objects.filter(id=session.id).update(created_at=old_time)
        
        SessionLifecycleManager.update_session_states()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.INACTIVE)
        
        # 7. User starts new session - profile is still available
        new_session_result = RESTAPIAdapter.create_session(request)
        self.assertTrue(new_session_result['success'])
        
        # Should get same visitor but new session
        self.assertEqual(new_session_result['visitor_id'], visitor_id)
        self.assertNotEqual(new_session_result['session_id'], session_id)
        
        # Profile should be pre-populated
        profile = new_session_result['visitor_profile']
        self.assertEqual(profile['name'], "Jane Smith")
        self.assertEqual(profile['email'], "jane@example.com")