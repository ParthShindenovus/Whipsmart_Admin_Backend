from django.test import TestCase
from chats.models import Session, Visitor


class SessionStatusFieldTest(TestCase):
    """Test the new status field functionality in Session model."""
    
    def setUp(self):
        """Set up test data."""
        self.visitor = Visitor.objects.create(ip_address='192.168.1.100')
    
    def test_session_default_status_is_active(self):
        """Test that new sessions default to ACTIVE status."""
        session = Session.objects.create(visitor=self.visitor)
        self.assertEqual(session.status, Session.Status.ACTIVE)
    
    def test_session_status_choices(self):
        """Test that all status choices are available."""
        expected_choices = [
            ('ACTIVE', 'Active'),
            ('SNOOZED', 'Snoozed'),
            ('INACTIVE', 'Inactive')
        ]
        self.assertEqual(Session.Status.choices, expected_choices)
    
    def test_session_status_can_be_changed(self):
        """Test that session status can be updated to different values."""
        session = Session.objects.create(visitor=self.visitor)
        
        # Test changing to SNOOZED
        session.status = Session.Status.SNOOZED
        session.save()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.SNOOZED)
        
        # Test changing to INACTIVE
        session.status = Session.Status.INACTIVE
        session.is_active = False  # Need to sync is_active field
        session.save()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.INACTIVE)
    
    def test_session_status_field_properties(self):
        """Test that status field has correct properties."""
        status_field = Session._meta.get_field('status')
        self.assertEqual(status_field.max_length, 10)
        self.assertTrue(status_field.db_index)
        self.assertEqual(status_field.default, Session.Status.ACTIVE)
    
    def test_session_status_is_active_sync(self):
        """Test that is_active and status fields are kept in sync."""
        session = Session.objects.create(visitor=self.visitor)
        
        # Test setting is_active to False syncs status to INACTIVE
        session.is_active = False
        session.save()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.INACTIVE)
        self.assertFalse(session.is_active)
        
        # Test setting is_active to True when status is INACTIVE syncs status to ACTIVE
        session.is_active = True
        session.save()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.ACTIVE)
        self.assertTrue(session.is_active)
    
    def test_session_status_sync_preserves_snoozed(self):
        """Test that SNOOZED status is preserved when is_active is True."""
        session = Session.objects.create(visitor=self.visitor)
        
        # Set status to SNOOZED
        session.status = Session.Status.SNOOZED
        session.save()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.SNOOZED)
        self.assertTrue(session.is_active)  # SNOOZED sessions should still be considered active
