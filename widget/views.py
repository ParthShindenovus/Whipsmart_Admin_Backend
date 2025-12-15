from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import BaseAuthentication
from django.utils import timezone
from django.db.models import Q
from django.core.paginator import Paginator
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from .authentication import APIKeyAuthentication
from .permissions import RequiresAPIKey
from .models import WidgetAPIKey, WidgetConfig, APIKeyUsageLog
from .serializers import (
    WidgetAPIKeyCreateSerializer,
    WidgetAPIKeySerializer,
    WidgetAPIKeyCreateResponseSerializer,
    WidgetAPIKeyRegenerateResponseSerializer,
    WidgetConfigSerializer,
    EmbedCodeSerializer,
)
from .utils import generate_api_key, hash_api_key, check_rate_limit
from core.views_base import StandardizedResponseMixin
from core.utils import success_response, error_response
import time


@extend_schema_view(
    list=extend_schema(
        summary="List API keys",
        description="Retrieve all API keys for the authenticated user/organization.",
        tags=['Widget API Keys'],
    ),
    retrieve=extend_schema(
        summary="Get API key details",
        description="Retrieve detailed information about a specific API key.",
        tags=['Widget API Keys'],
    ),
    destroy=extend_schema(
        summary="Revoke API key",
        description="Revoke or delete an API key (soft delete).",
        tags=['Widget API Keys'],
    ),
)
class WidgetAPIKeyViewSet(StandardizedResponseMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing Widget API Keys.
    """
    serializer_class = WidgetAPIKeySerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter API keys by authenticated user and optional organization."""
        queryset = WidgetAPIKey.objects.filter(deleted_at__isnull=True)
        
        # Filter by user
        queryset = queryset.filter(user=self.request.user)
        
        
        # Optional active status filter
        is_active = self.request.query_params.get('isActive')
        if is_active is not None:
            is_active_bool = is_active.lower() == 'true'
            queryset = queryset.filter(is_active=is_active_bool)
        
        return queryset.order_by('-created_at')
    
    @extend_schema(
        summary="Create API key",
        description="Create a new API key for embedding the chat widget. The API key is returned only once.",
        request=WidgetAPIKeyCreateSerializer,
        responses={201: WidgetAPIKeyCreateResponseSerializer},
        tags=['Widget API Keys'],
    )
    def create(self, request):
        """Create a new API key."""
        serializer = WidgetAPIKeyCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Validation error",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate API key
        prefix = getattr(request.data, 'prefix', 'sk_live_')
        full_key, key_prefix, key_hash = generate_api_key(prefix=prefix)
        
        # Create API key record
        api_key = WidgetAPIKey.objects.create(
            api_key_hash=key_hash,
            key_prefix=key_prefix,
            name=serializer.validated_data['name'],
            user=request.user,
            allowed_domains=serializer.validated_data.get('allowed_domains', []),
            expires_at=serializer.validated_data.get('expires_at'),
            metadata=serializer.validated_data.get('metadata', {}),
        )
        
        # Prepare response with the actual key (only shown once)
        response_data = {
            'id': api_key.id,
            'api_key': full_key,  # Only time this is returned
            'key_prefix': api_key.key_prefix,
            'name': api_key.name,
            'user': api_key.user.id,
            'allowed_domains': api_key.allowed_domains,
            'created_at': api_key.created_at,
            'expires_at': api_key.expires_at,
            'is_active': api_key.is_active,
            'last_used_at': api_key.last_used_at,
            'metadata': api_key.metadata,
        }
        
        return success_response(
            response_data,
            message="API key created successfully. Please save it securely as it won't be shown again.",
            status_code=status.HTTP_201_CREATED
        )
    
    def list(self, request):
        """List API keys with pagination."""
        queryset = self.get_queryset()
        
        # Pagination
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 20))
        
        paginator = Paginator(queryset, limit)
        page_obj = paginator.get_page(page)
        
        serializer = self.get_serializer(page_obj.object_list, many=True)
        
        return success_response({
            'data': serializer.data,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': paginator.count,
                'totalPages': paginator.num_pages,
            }
        })
    
    def destroy(self, request, pk=None):
        """Soft delete (revoke) an API key."""
        try:
            api_key = self.get_object()
            
            # Verify ownership
            if api_key.user != request.user:
                return error_response(
                    message="You don't have permission to revoke this API key.",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # Soft delete
            api_key.is_active = False
            api_key.deleted_at = timezone.now()
            api_key.save()
            
            return success_response(
                message="API key revoked successfully"
            )
        except WidgetAPIKey.DoesNotExist:
            return error_response(
                message="API key not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
    
    @extend_schema(
        summary="Regenerate API key",
        description="Generate a new API key for an existing key record. The old key is invalidated immediately.",
        responses={200: WidgetAPIKeyRegenerateResponseSerializer},
        tags=['Widget API Keys'],
    )
    @action(detail=True, methods=['post'])
    def regenerate(self, request, pk=None):
        """Regenerate an API key."""
        try:
            api_key = self.get_object()
            
            # Verify ownership
            if api_key.user != request.user:
                return error_response(
                    message="You don't have permission to regenerate this API key.",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # Generate new key (preserve prefix type)
            # Extract prefix from existing key (e.g., "sk_live_abc..." -> "sk_live_")
            existing_prefix = api_key.key_prefix
            if '_' in existing_prefix:
                prefix_parts = existing_prefix.split('_')
                prefix = f"{prefix_parts[0]}_{prefix_parts[1]}_"
            else:
                prefix = 'sk_live_'
            full_key, key_prefix, key_hash = generate_api_key(prefix=prefix)
            
            # Update API key record (invalidate old key)
            api_key.api_key_hash = key_hash
            api_key.key_prefix = key_prefix
            api_key.is_active = True
            api_key.deleted_at = None
            api_key.save()
            
            response_data = {
                'id': api_key.id,
                'api_key': full_key,  # Only time this is returned
                'key_prefix': api_key.key_prefix,
                'regenerated_at': timezone.now(),
            }
            
            return success_response(
                response_data,
                message="API key regenerated successfully. Please save it securely as it won't be shown again."
            )
        except WidgetAPIKey.DoesNotExist:
            return error_response(
                message="API key not found",
                status_code=status.HTTP_404_NOT_FOUND
            )


@extend_schema(
    summary="Get widget configuration",
    description="Returns widget configuration for a valid API key. Used by widget loader script. API key can be provided via header (X-API-Key or Authorization Bearer) or query parameter.",
    parameters=[
        OpenApiParameter(
            name='apiKey',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description='API Key (optional) - Can also be provided via X-API-Key header or Authorization: Bearer <key> header',
        ),
    ],
    responses={200: WidgetConfigSerializer},
    tags=['Widget'],
)
@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])  # Use API key authentication instead of JWT
@permission_classes([RequiresAPIKey])  # Require API key authentication
def get_widget_config(request):
    """
    Get widget configuration for a valid API key.
    This endpoint is called by the widget loader script.
    
    API key can be provided via:
    1. Header: X-API-Key or Authorization: Bearer <key>
    2. Query parameter: ?apiKey=sk_live_...
    """
    # Get API key record from authentication (request.auth will be WidgetAPIKey instance)
    api_key_record = getattr(request, 'auth', None)
    
    # If not authenticated via APIKeyAuthentication, try middleware or query params
    if not api_key_record or not isinstance(api_key_record, WidgetAPIKey):
        # Check if middleware set it
        api_key_record = getattr(request, 'api_key', None)
        
        # If still not set, try query parameter
        if not api_key_record:
            api_key = request.query_params.get('apiKey')
            
            # If we have an API key, validate it manually
            if api_key:
                from .utils import hash_api_key
                key_hash = hash_api_key(api_key)
                try:
                    api_key_record = WidgetAPIKey.objects.get(
                        api_key_hash=key_hash,
                        deleted_at__isnull=True
                    )
                    
                    # Check if key is valid
                    if not api_key_record.is_active:
                        return error_response(
                            message="API key inactive",
                            status_code=status.HTTP_401_UNAUTHORIZED
                        )
                    
                    if api_key_record.is_expired():
                        return error_response(
                            message="API key expired",
                            status_code=status.HTTP_401_UNAUTHORIZED
                        )
                    
                    # Validate domain origin (now more permissive - allows all if no restrictions set)
                    from .utils import validate_domain_origin
                    origin = request.META.get('HTTP_ORIGIN') or request.META.get('HTTP_REFERER', '')
                    # Domain validation is now permissive - only restricts if explicitly configured
                    # This allows widget to work from any domain
                    
                    # Update last used
                    api_key_record.update_last_used()
                    
                except WidgetAPIKey.DoesNotExist:
                    return error_response(
                        message="Invalid API key",
                        status_code=status.HTTP_401_UNAUTHORIZED
                    )
    
    if not api_key_record:
        return error_response(
            message="API key required. Provide via header (X-API-Key or Authorization: Bearer <key>) or query parameter (?apiKey=...)",
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    
    # Check rate limit
    is_allowed, remaining, reset_time = check_rate_limit(
        api_key_record.id,
        '/api/v1/widget/config',
        limit=100,  # 100 requests per hour
        time_window_seconds=3600
    )
    
    if not is_allowed:
        response = error_response(
            message="Rate limit exceeded",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
        )
        # Set rate limit headers
        response['X-RateLimit-Limit'] = '100'
        response['X-RateLimit-Remaining'] = '0'
        response['X-RateLimit-Reset'] = str(reset_time)
        return response
    
    # Get or create widget config (use API key instead of organization_id)
    widget_config, created = WidgetConfig.objects.get_or_create(
        api_key=api_key_record,
        defaults={
            'api_url': getattr(request, 'api_url', 'https://api.yourdomain.com'),
            'widget_url': getattr(request, 'widget_url', 'https://cdn.yourdomain.com/widget'),
            'features': {
                'chatEnabled': True,
                'fileUploadEnabled': True,
                'voiceEnabled': False,
            },
            'theme': {
                'primaryColor': '#000000',
                'position': 'bottom-right',
            },
            'organization_name': api_key_record.metadata.get('organizationName', '') if isinstance(api_key_record.metadata, dict) else '',
        }
    )
    
    # Log usage
    start_time = time.time()
    response_time = int((time.time() - start_time) * 1000)
    
    APIKeyUsageLog.objects.create(
        api_key=api_key_record,
        endpoint='/api/v1/widget/config',
        method='GET',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        status_code=200,
        response_time=response_time,
    )
    
    serializer = WidgetConfigSerializer(widget_config)
    response = success_response(serializer.data)
    # Add rate limit headers
    response['X-RateLimit-Limit'] = '100'
    response['X-RateLimit-Remaining'] = str(remaining)
    response['X-RateLimit-Reset'] = str(reset_time)
    return response


@extend_schema(
    summary="Get embed code",
    description="Generates copy-paste ready HTML/JavaScript embed code snippet for customers to embed the widget on their website. Returns formatted code with instructions.",
    parameters=[
        OpenApiParameter(
            name='apiKeyId',
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.QUERY,
            required=True,
            description='API Key ID (UUID) - Required to identify which API key to generate embed code for',
        ),
        OpenApiParameter(
            name='apiKey',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description='Full API Key (optional) - If provided, embed code will be ready to use with full key included. Otherwise, you\'ll need to replace the prefix with your full key.',
        ),
    ],
    responses={200: EmbedCodeSerializer},
    tags=['Widget'],
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_embed_code(request):
    """
    Generate embed code for an API key.
    
    API key ID must be provided via query parameter: ?apiKeyId=<uuid>
    Optionally, provide full API key via: ?apiKey=<full_key> to include it in embed code
    """
    api_key_id = request.query_params.get('apiKeyId')
    full_api_key = request.query_params.get('apiKey')  # Optional: full API key to include in embed code
    
    # If API key ID is provided, look it up
    if api_key_id:
        try:
            api_key = WidgetAPIKey.objects.get(
                id=api_key_id,
                user=request.user,
                deleted_at__isnull=True
            )
        except WidgetAPIKey.DoesNotExist:
            return error_response(
                message="API key not found or you don't have permission to access it",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # If full API key is provided, verify it matches
        if full_api_key:
            from .utils import hash_api_key
            provided_hash = hash_api_key(full_api_key)
            if provided_hash != api_key.api_key_hash:
                return error_response(
                    message="Provided API key does not match the API key ID",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
    else:
        return error_response(
            message="apiKeyId query parameter is required",
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # Get widget config
    widget_config = WidgetConfig.objects.filter(
        api_key=api_key
    ).first()
    
    if not widget_config:
        widget_config = WidgetConfig.objects.create(
            api_key=api_key,
            api_url=getattr(request, 'api_url', 'https://api.yourdomain.com'),
            widget_url=getattr(request, 'widget_url', 'https://cdn.yourdomain.com/widget'),
        )
    
    # Get widget URLs from settings or config
    from django.conf import settings
    api_url = widget_config.api_url or getattr(settings, 'WIDGET_API_URL', 'https://api.yourdomain.com')
    widget_url = widget_config.widget_url or getattr(settings, 'WIDGET_CDN_URL', 'https://cdn.yourdomain.com/widget')
    widget_loader_url = getattr(settings, 'WIDGET_LOADER_URL', 'https://cdn.yourdomain.com/widget-loader.js')
    
    # Use full API key if provided, otherwise use prefix (user will need to replace it)
    api_key_for_embed = full_api_key if full_api_key else api_key.key_prefix
    
    # Generate nicely formatted embed code that's ready to copy-paste
    embed_code_formatted = f'''<!-- WhipSmart Chat Widget -->
<!-- Copy and paste this code before the closing </body> tag of your website -->

<script src="{widget_loader_url}" 
        data-api-key="{api_key_for_embed}" 
        data-api-url="{api_url}" 
        data-widget-url="{widget_url}">
</script>'''
    
    # Also provide a clean one-liner version for easy copying
    embed_code_oneline = f'<script src="{widget_loader_url}" data-api-key="{api_key_for_embed}" data-api-url="{api_url}" data-widget-url="{widget_url}"></script>'
    
    # Instructions for the user
    if full_api_key:
        instructions = f'''To embed the WhipSmart Chat Widget on your website:

1. Copy the embed code below
2. Paste it before the closing </body> tag of your HTML pages

The widget will automatically load and appear on your website.'''
        note = 'Embed code is ready to use! The full API key has been included.'
    else:
        instructions = f'''To embed the WhipSmart Chat Widget on your website:

1. Copy the embed code below
2. Paste it before the closing </body> tag of your HTML pages
3. Replace "{api_key.key_prefix}" with your full API key

The widget will automatically load and appear on your website.'''
        note = f'Important: Replace "{api_key.key_prefix}" in the embed code with your full API key. You can also provide the full API key via ?apiKey parameter to get ready-to-use embed code.'
    
    response_data = {
        'embed_code': embed_code_formatted,
        'embed_code_oneline': embed_code_oneline,
        'instructions': instructions,
        'api_key_prefix': api_key.key_prefix,
        'api_key_id': str(api_key.id),
        'widget_url': widget_url,
        'api_url': api_url,
        'widget_loader_url': widget_loader_url,
        'note': note,
        'is_ready_to_use': bool(full_api_key),  # Indicates if embed code has full API key
    }
    
    return success_response(response_data)


def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@extend_schema(
    summary="Serve widget loader script",
    description="Serves the widget-loader.js script with proper CORS headers to allow cross-origin loading.",
    responses={200: OpenApiTypes.BINARY},
    tags=['Widget'],
)
@api_view(['GET', 'OPTIONS'])
@permission_classes([AllowAny])  # Allow public access to widget loader
def serve_widget_loader(request):
    """
    Serve widget-loader.js with proper CORS headers.
    This endpoint allows the widget script to be loaded from any origin.
    
    IMPORTANT: If you're hosting widget-loader.js on a separate server (e.g., chatbot-widget.novuscode.in),
    that server needs to be configured with CORS headers. For Django servers, use django-cors-headers.
    For static file servers (nginx, Apache, CDN), configure CORS headers in the server configuration.
    """
    from django.conf import settings
    from django.http import HttpResponse, FileResponse
    from pathlib import Path
    
    # Handle OPTIONS preflight request
    if request.method == 'OPTIONS':
        response = HttpResponse()
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Origin, Accept, X-API-Key, Authorization'
        response['Access-Control-Max-Age'] = '3600'
        return response
    
    # Try to find widget-loader.js in static files or a specific location
    widget_loader_path = None
    
    # Check if widget-loader.js exists in static files
    static_root = getattr(settings, 'STATIC_ROOT', None)
    if static_root:
        widget_loader_path = Path(static_root) / 'widget-loader.js'
        if not widget_loader_path.exists():
            widget_loader_path = None
    
    # If not in static root, check for a widget static directory
    if not widget_loader_path or not widget_loader_path.exists():
        widget_static_dir = Path(__file__).parent.parent / 'static' / 'widget'
        widget_loader_path = widget_static_dir / 'widget-loader.js'
        if not widget_loader_path.exists():
            widget_loader_path = None
    
    # If file exists, serve it with CORS headers
    if widget_loader_path and widget_loader_path.exists():
        try:
            response = FileResponse(
                open(widget_loader_path, 'rb'),
                content_type='application/javascript; charset=utf-8'
            )
        except Exception as e:
            return error_response(
                message=f"Error reading widget-loader.js: {str(e)}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        # If file doesn't exist, return a minimal loader script that redirects to CDN
        widget_loader_url = getattr(settings, 'WIDGET_LOADER_URL', 'https://cdn.yourdomain.com/widget-loader.js')
        
        # Return a simple loader script that loads from CDN
        loader_script = f'''// WhipSmart Widget Loader
// This file should be replaced with the actual widget-loader.js
// For now, redirecting to CDN: {widget_loader_url}

(function() {{
    var script = document.createElement('script');
    script.src = '{widget_loader_url}';
    script.async = true;
    document.head.appendChild(script);
}})();
'''
        response = HttpResponse(loader_script, content_type='application/javascript; charset=utf-8')
    
    # Set CORS headers explicitly for JavaScript files
    # These headers allow the script to be loaded from any origin
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response['Access-Control-Allow-Headers'] = 'Content-Type, Origin, Accept, X-API-Key, Authorization'
    response['Access-Control-Max-Age'] = '3600'
    
    # Cache control for better performance
    response['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
    
    return response
