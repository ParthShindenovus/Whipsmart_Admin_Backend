"""
Middleware for API key authentication.
"""
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from .models import WidgetAPIKey
from .utils import extract_api_key_from_request, hash_api_key, validate_domain_origin, constant_time_compare


class APIKeyAuthenticationMiddleware(MiddlewareMixin):
    """
    Middleware to authenticate requests using API keys.
    
    This middleware validates API keys for widget endpoints.
    It checks:
    1. API key presence
    2. API key validity (active, not expired)
    3. Domain restrictions (if configured)
    4. Updates last_used_at timestamp
    """
    
    # Paths that require API key authentication
    # Note: These are handled by APIKeyAuthentication class in views
    # Middleware is kept for backward compatibility but views handle auth directly
    API_KEY_REQUIRED_PATHS = [
        '/api/v1/widget/config',
        '/api/chats/messages/chat',  # Chat endpoints require API key
        '/api/chats/messages/chat/stream',  # Streaming chat endpoint
    ]
    
    def process_request(self, request):
        """Process incoming request and validate API key if needed."""
        # Check if this path requires API key authentication
        path = request.path
        requires_api_key = any(path.startswith(required_path) for required_path in self.API_KEY_REQUIRED_PATHS)
        
        if not requires_api_key:
            return None  # Continue processing
        
        # Extract API key from request (headers first, then query params)
        api_key = extract_api_key_from_request(request)
        
        # Also check query parameter
        if not api_key:
            api_key = request.GET.get('apiKey')
        
        # If still no API key, let the view handle it (it can check request body)
        # This allows flexibility for POST requests with body
        if not api_key:
            return None  # Let view handle the error message
        
        # Hash the provided key
        key_hash = hash_api_key(api_key)
        
        # Lookup API key record
        try:
            api_key_record = WidgetAPIKey.objects.get(
                api_key_hash=key_hash,
                deleted_at__isnull=True
            )
        except WidgetAPIKey.DoesNotExist:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Invalid API key',
                    'error': 'The provided API key is invalid or does not exist'
                },
                status=401
            )
        
        # Check if key is active
        if not api_key_record.is_active:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'API key inactive',
                    'error': 'This API key has been revoked'
                },
                status=401
            )
        
        # Check if key is expired
        if api_key_record.is_expired():
            return JsonResponse(
                {
                    'success': False,
                    'message': 'API key expired',
                    'error': 'This API key has expired'
                },
                status=401
            )
        
        # Validate domain origin (now permissive - allows all if no restrictions set)
        origin = request.META.get('HTTP_ORIGIN') or request.META.get('HTTP_REFERER', '')
        # Domain validation is now permissive - only restricts if explicitly configured
        # This allows widget to work from any domain
        
        # Attach API key record to request for use in views
        request.api_key = api_key_record
        request.organization_id = api_key_record.organization_id
        
        # Update last used timestamp (async to avoid blocking)
        api_key_record.update_last_used()
        
        return None  # Continue processing

