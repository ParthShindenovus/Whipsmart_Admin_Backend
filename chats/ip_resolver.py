"""
IP Resolver utility for visitor identity resolution.
Provides centralized IP-based visitor resolution functionality.
"""
import logging
from typing import Optional
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.utils import timezone
from .models import Visitor

logger = logging.getLogger(__name__)


class IPResolver:
    """
    Centralized utility for resolving visitor identity from IP addresses.
    Serves as the single source of truth for visitor resolution across the application.
    """
    
    @staticmethod
    def get_or_create_visitor_from_ip(ip_address: str) -> Visitor:
        """
        Resolve or create visitor from IP address.
        Updates last_seen_at timestamp on every call.
        
        Args:
            ip_address: The IP address (IPv4 or IPv6) to resolve
            
        Returns:
            Visitor: The visitor instance associated with the IP address
            
        Raises:
            ValidationError: If the IP address is invalid
            ValueError: If the IP address is empty or None
        """
        if not ip_address or not ip_address.strip():
            raise ValueError("IP address cannot be empty or None")
        
        # Strip whitespace
        ip_address = ip_address.strip()
        
        # Validate IP address format (supports both IPv4 and IPv6)
        try:
            validate_ipv46_address(ip_address)
        except ValidationError as e:
            logger.error(f"[IP_RESOLVER] Invalid IP address format: {ip_address}")
            raise ValidationError(f"Invalid IP address format: {ip_address}") from e
        
        try:
            # Try to get existing visitor
            visitor = Visitor.objects.get(ip_address=ip_address)
            logger.info(f"[IP_RESOLVER] Found existing visitor {visitor.id} for IP: {ip_address}")
            
            # Update last_seen_at timestamp
            visitor.last_seen_at = timezone.now()
            visitor.save(update_fields=['last_seen_at'])
            
            return visitor
            
        except Visitor.DoesNotExist:
            # Create new visitor
            try:
                visitor = Visitor.objects.create(ip_address=ip_address)
                logger.info(f"[IP_RESOLVER] Created new visitor {visitor.id} for IP: {ip_address}")
                return visitor
                
            except Exception as e:
                # Handle potential race condition where another process creates the visitor
                # between our get() and create() calls
                try:
                    visitor = Visitor.objects.get(ip_address=ip_address)
                    logger.info(f"[IP_RESOLVER] Found visitor {visitor.id} for IP: {ip_address} (race condition)")
                    
                    # Update last_seen_at timestamp
                    visitor.last_seen_at = timezone.now()
                    visitor.save(update_fields=['last_seen_at'])
                    
                    return visitor
                except Visitor.DoesNotExist:
                    # Re-raise original exception if visitor still doesn't exist
                    logger.error(f"[IP_RESOLVER] Error creating visitor for IP {ip_address}: {str(e)}")
                    raise e
    
    @staticmethod
    def extract_client_ip(request) -> str:
        """
        Extract client IP from request headers.
        Checks X-Forwarded-For header first, then falls back to REMOTE_ADDR.
        
        Args:
            request: Django request object
            
        Returns:
            str: The client IP address
            
        Raises:
            ValueError: If no valid IP address can be extracted
        """
        # Check X-Forwarded-For header first (for proxied requests)
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
            # The rightmost IP is typically the most recent proxy, but we want the leftmost (original client)
            # However, for security, we should take the rightmost trusted IP
            # For now, we'll take the first IP (leftmost) as the original client
            ip_list = [ip.strip() for ip in x_forwarded_for.split(',')]
            client_ip = ip_list[0]  # First IP is typically the original client
            
            # Validate the extracted IP
            try:
                validate_ipv46_address(client_ip)
                logger.info(f"[IP_RESOLVER] Extracted IP from X-Forwarded-For: {client_ip}")
                return client_ip
            except ValidationError:
                logger.warning(f"[IP_RESOLVER] Invalid IP in X-Forwarded-For: {client_ip}")
                # Continue to fallback
        
        # Fallback to REMOTE_ADDR
        remote_addr = request.META.get('REMOTE_ADDR')
        if remote_addr:
            try:
                validate_ipv46_address(remote_addr)
                logger.info(f"[IP_RESOLVER] Extracted IP from REMOTE_ADDR: {remote_addr}")
                return remote_addr
            except ValidationError:
                logger.warning(f"[IP_RESOLVER] Invalid IP in REMOTE_ADDR: {remote_addr}")
        
        # If we get here, no valid IP was found
        logger.error("[IP_RESOLVER] No valid IP address found in request headers")
        raise ValueError("No valid IP address found in request headers")
    
    @staticmethod
    def extract_websocket_ip(scope) -> str:
        """
        Extract client IP from WebSocket scope.
        Checks X-Forwarded-For header first, then falls back to client address.
        
        Args:
            scope: WebSocket scope dictionary
            
        Returns:
            str: The client IP address
            
        Raises:
            ValueError: If no valid IP address can be extracted
        """
        # Check headers for X-Forwarded-For
        headers = dict(scope.get('headers', []))
        x_forwarded_for = headers.get(b'x-forwarded-for')
        
        if x_forwarded_for:
            # Decode bytes to string and extract first IP
            x_forwarded_for_str = x_forwarded_for.decode('utf-8')
            ip_list = [ip.strip() for ip in x_forwarded_for_str.split(',')]
            client_ip = ip_list[0]  # First IP is typically the original client
            
            # Validate the extracted IP
            try:
                validate_ipv46_address(client_ip)
                logger.info(f"[IP_RESOLVER] Extracted WebSocket IP from X-Forwarded-For: {client_ip}")
                return client_ip
            except ValidationError:
                logger.warning(f"[IP_RESOLVER] Invalid WebSocket IP in X-Forwarded-For: {client_ip}")
                # Continue to fallback
        
        # Fallback to client address from scope
        client = scope.get('client')
        if client and len(client) >= 1:
            client_ip = client[0]  # First element is the IP address
            try:
                validate_ipv46_address(client_ip)
                logger.info(f"[IP_RESOLVER] Extracted WebSocket IP from client: {client_ip}")
                return client_ip
            except ValidationError:
                logger.warning(f"[IP_RESOLVER] Invalid WebSocket IP in client: {client_ip}")
        
        # If we get here, no valid IP was found
        logger.error("[IP_RESOLVER] No valid IP address found in WebSocket scope")
        raise ValueError("No valid IP address found in WebSocket scope")