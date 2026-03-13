"""
Tests for IPResolver utility class.
"""
from django.test import TestCase, RequestFactory
from django.core.exceptions import ValidationError
from django.utils import timezone
from unittest.mock import Mock
from chats.ip_resolver import IPResolver
from chats.models import Visitor


class IPResolverTest(TestCase):
    """Test the IPResolver utility class."""
    
    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
    
    def test_get_or_create_visitor_from_ip_creates_new_visitor(self):
        """Test that get_or_create_visitor_from_ip creates a new visitor for new IP."""
        ip_address = '192.168.1.100'
        
        # Ensure no visitor exists for this IP
        self.assertFalse(Visitor.objects.filter(ip_address=ip_address).exists())
        
        # Create visitor
        visitor = IPResolver.get_or_create_visitor_from_ip(ip_address)
        
        # Verify visitor was created
        self.assertIsInstance(visitor, Visitor)
        self.assertEqual(visitor.ip_address, ip_address)
        self.assertTrue(Visitor.objects.filter(ip_address=ip_address).exists())
    
    def test_get_or_create_visitor_from_ip_returns_existing_visitor(self):
        """Test that get_or_create_visitor_from_ip returns existing visitor for known IP."""
        ip_address = '192.168.1.101'
        
        # Create existing visitor
        existing_visitor = Visitor.objects.create(ip_address=ip_address)
        original_last_seen = existing_visitor.last_seen_at
        
        # Get visitor (should return existing one)
        visitor = IPResolver.get_or_create_visitor_from_ip(ip_address)
        
        # Verify same visitor was returned
        self.assertEqual(visitor.id, existing_visitor.id)
        self.assertEqual(visitor.ip_address, ip_address)
        
        # Verify last_seen_at was updated
        visitor.refresh_from_db()
        self.assertGreater(visitor.last_seen_at, original_last_seen)
    
    def test_get_or_create_visitor_from_ip_handles_ipv6(self):
        """Test that get_or_create_visitor_from_ip handles IPv6 addresses."""
        ipv6_address = '2001:db8::1'
        
        # Create visitor with IPv6
        visitor = IPResolver.get_or_create_visitor_from_ip(ipv6_address)
        
        # Verify visitor was created with IPv6
        self.assertEqual(visitor.ip_address, ipv6_address)
        self.assertTrue(Visitor.objects.filter(ip_address=ipv6_address).exists())
    
    def test_get_or_create_visitor_from_ip_validates_ip_format(self):
        """Test that get_or_create_visitor_from_ip validates IP address format."""
        invalid_ips = [
            'invalid.ip',
            '999.999.999.999',
            '192.168.1',
            'not-an-ip',
            '192.168.1.1.1'
        ]
        
        for invalid_ip in invalid_ips:
            with self.assertRaises(ValidationError):
                IPResolver.get_or_create_visitor_from_ip(invalid_ip)
    
    def test_get_or_create_visitor_from_ip_handles_empty_ip(self):
        """Test that get_or_create_visitor_from_ip handles empty IP addresses."""
        empty_ips = [None, '', '   ']
        
        for empty_ip in empty_ips:
            with self.assertRaises(ValueError):
                IPResolver.get_or_create_visitor_from_ip(empty_ip)
    
    def test_extract_client_ip_from_x_forwarded_for(self):
        """Test extracting IP from X-Forwarded-For header."""
        request = self.factory.get('/')
        request.META['HTTP_X_FORWARDED_FOR'] = '192.168.1.100, 10.0.0.1, 172.16.0.1'
        
        ip = IPResolver.extract_client_ip(request)
        
        # Should return the first IP (original client)
        self.assertEqual(ip, '192.168.1.100')
    
    def test_extract_client_ip_from_remote_addr(self):
        """Test extracting IP from REMOTE_ADDR when X-Forwarded-For is not present."""
        request = self.factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.200'
        
        ip = IPResolver.extract_client_ip(request)
        
        self.assertEqual(ip, '192.168.1.200')
    
    def test_extract_client_ip_prefers_x_forwarded_for(self):
        """Test that X-Forwarded-For is preferred over REMOTE_ADDR."""
        request = self.factory.get('/')
        request.META['HTTP_X_FORWARDED_FOR'] = '192.168.1.100'
        request.META['REMOTE_ADDR'] = '192.168.1.200'
        
        ip = IPResolver.extract_client_ip(request)
        
        # Should prefer X-Forwarded-For
        self.assertEqual(ip, '192.168.1.100')
    
    def test_extract_client_ip_handles_invalid_x_forwarded_for(self):
        """Test fallback to REMOTE_ADDR when X-Forwarded-For contains invalid IP."""
        request = self.factory.get('/')
        request.META['HTTP_X_FORWARDED_FOR'] = 'invalid-ip, another-invalid'
        request.META['REMOTE_ADDR'] = '192.168.1.200'
        
        ip = IPResolver.extract_client_ip(request)
        
        # Should fallback to REMOTE_ADDR
        self.assertEqual(ip, '192.168.1.200')
    
    def test_extract_client_ip_raises_error_when_no_valid_ip(self):
        """Test that ValueError is raised when no valid IP can be extracted."""
        request = self.factory.get('/')
        # Remove all IP-related headers
        if 'REMOTE_ADDR' in request.META:
            del request.META['REMOTE_ADDR']
        if 'HTTP_X_FORWARDED_FOR' in request.META:
            del request.META['HTTP_X_FORWARDED_FOR']
        
        with self.assertRaises(ValueError):
            IPResolver.extract_client_ip(request)
    
    def test_extract_websocket_ip_from_x_forwarded_for(self):
        """Test extracting IP from WebSocket X-Forwarded-For header."""
        scope = {
            'headers': [
                (b'x-forwarded-for', b'192.168.1.100, 10.0.0.1')
            ]
        }
        
        ip = IPResolver.extract_websocket_ip(scope)
        
        self.assertEqual(ip, '192.168.1.100')
    
    def test_extract_websocket_ip_from_client(self):
        """Test extracting IP from WebSocket client when X-Forwarded-For is not present."""
        scope = {
            'client': ['192.168.1.200', 12345]  # [ip, port]
        }
        
        ip = IPResolver.extract_websocket_ip(scope)
        
        self.assertEqual(ip, '192.168.1.200')
    
    def test_extract_websocket_ip_prefers_x_forwarded_for(self):
        """Test that WebSocket X-Forwarded-For is preferred over client."""
        scope = {
            'headers': [
                (b'x-forwarded-for', b'192.168.1.100')
            ],
            'client': ['192.168.1.200', 12345]
        }
        
        ip = IPResolver.extract_websocket_ip(scope)
        
        # Should prefer X-Forwarded-For
        self.assertEqual(ip, '192.168.1.100')
    
    def test_extract_websocket_ip_raises_error_when_no_valid_ip(self):
        """Test that ValueError is raised when no valid WebSocket IP can be extracted."""
        scope = {}  # Empty scope
        
        with self.assertRaises(ValueError):
            IPResolver.extract_websocket_ip(scope)
    
    def test_ip_uniqueness_constraint(self):
        """Test that IP address uniqueness is enforced."""
        ip_address = '192.168.1.150'
        
        # Create first visitor
        visitor1 = IPResolver.get_or_create_visitor_from_ip(ip_address)
        
        # Try to get visitor again - should return same visitor
        visitor2 = IPResolver.get_or_create_visitor_from_ip(ip_address)
        
        # Should be the same visitor
        self.assertEqual(visitor1.id, visitor2.id)
        
        # Should only have one visitor with this IP
        self.assertEqual(Visitor.objects.filter(ip_address=ip_address).count(), 1)
    
    def test_last_seen_at_updates_on_every_call(self):
        """Test that last_seen_at is updated on every call to get_or_create_visitor_from_ip."""
        ip_address = '192.168.1.160'
        
        # Create visitor
        visitor1 = IPResolver.get_or_create_visitor_from_ip(ip_address)
        first_seen = visitor1.last_seen_at
        
        # Wait a moment and call again
        import time
        time.sleep(0.01)  # Small delay to ensure different timestamp
        
        visitor2 = IPResolver.get_or_create_visitor_from_ip(ip_address)
        second_seen = visitor2.last_seen_at
        
        # Should be same visitor but with updated timestamp
        self.assertEqual(visitor1.id, visitor2.id)
        self.assertGreater(second_seen, first_seen)