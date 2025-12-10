"""
Custom authentication class for API key authentication.
"""
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from .models import WidgetAPIKey
from .utils import extract_api_key_from_request, hash_api_key, validate_domain_origin


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Custom authentication class for API key authentication.
    
    Checks for API key in:
    1. X-API-Key header
    2. Authorization: Bearer <api-key> header
    3. Query parameter: ?apiKey=...
    """
    
    def authenticate(self, request):
        """
        Authenticate the request using API key.
        
        Returns:
            Tuple of (user, token) if authentication succeeds, None otherwise.
            For API key auth, we return (None, api_key_record) since there's no user.
        """
        # Extract API key from request
        api_key = extract_api_key_from_request(request)
        
        # Also check query parameter
        if not api_key:
            api_key = request.query_params.get('apiKey')
        
        if not api_key:
            # No API key provided - return None (permission class will handle rejection)
            return None
        
        # Hash the provided key
        key_hash = hash_api_key(api_key)
        
        # Lookup API key record
        try:
            api_key_record = WidgetAPIKey.objects.get(
                api_key_hash=key_hash,
                deleted_at__isnull=True
            )
        except WidgetAPIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid API key')
        
        # Check if key is active
        if not api_key_record.is_active:
            raise AuthenticationFailed('API key inactive')
        
        # Check if key is expired
        if api_key_record.is_expired():
            raise AuthenticationFailed('API key expired')
        
        # Validate domain origin (now permissive - allows all if no restrictions set)
        origin = request.META.get('HTTP_ORIGIN') or request.META.get('HTTP_REFERER', '')
        # Domain validation is now permissive - only restricts if explicitly configured
        # This allows widget to work from any domain
        
        # Update last used timestamp
        api_key_record.update_last_used()
        
        # Return (None, api_key_record) - no user, but API key is authenticated
        return (None, api_key_record)
    
    def authenticate_header(self, request):
        """
        Return a string to be used as the value of the `WWW-Authenticate`
        header in a `401 Unauthenticated` response.
        """
        return 'API-Key'

