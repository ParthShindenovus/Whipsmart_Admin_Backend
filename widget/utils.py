"""
Utility functions for widget API key management.
"""
import secrets
import hashlib
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from django.core.exceptions import ValidationError


def generate_api_key(prefix=None, length=32):
    """
    Generate a cryptographically secure API key.
    
    Args:
        prefix: Key prefix (defaults to sk_live_ from settings)
        length: Length of random part
        
    Returns:
        Tuple of (full_key, key_prefix, key_hash)
    """
    if prefix is None:
        prefix = getattr(settings, 'API_KEY_PREFIX_LIVE', 'sk_live_')
    
    # Generate random bytes
    random_part = secrets.token_urlsafe(length)
    full_key = f"{prefix}{random_part}"
    
    # Create hash
    key_hash = hash_api_key(full_key)
    
    # Create prefix for display (first 12 chars of full key)
    display_prefix = full_key[:12] + "..."
    
    return full_key, display_prefix, key_hash


def hash_api_key(api_key):
    """
    Hash an API key using SHA-256.
    
    Args:
        api_key: Plain text API key
        
    Returns:
        Hashed key (hex string)
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def constant_time_compare(val1, val2):
    """
    Compare two strings in constant time to prevent timing attacks.
    
    Args:
        val1: First string
        val2: Second string
        
    Returns:
        True if strings are equal, False otherwise
    """
    return secrets.compare_digest(val1, val2)


def get_rate_limit_key(api_key_id, endpoint, time_window='hour'):
    """
    Generate a rate limit cache key.
    
    Args:
        api_key_id: API key UUID
        endpoint: Endpoint path
        time_window: Time window ('hour', 'minute', 'day')
        
    Returns:
        Cache key string
    """
    return f"rate_limit:api_key:{api_key_id}:{endpoint}:{time_window}"


def check_rate_limit(api_key_id, endpoint, limit, time_window_seconds=3600):
    """
    Check if API key has exceeded rate limit.
    
    Args:
        api_key_id: API key UUID
        endpoint: Endpoint path
        limit: Maximum number of requests allowed
        time_window_seconds: Time window in seconds (default: 3600 = 1 hour)
        
    Returns:
        Tuple of (is_allowed, remaining, reset_time)
    """
    cache_key = get_rate_limit_key(api_key_id, endpoint)
    current_count = cache.get(cache_key, 0)
    
    if current_count >= limit:
        # Calculate reset time
        ttl = cache.ttl(cache_key)
        if ttl is None:
            reset_time = timezone.now().timestamp() + time_window_seconds
        else:
            reset_time = timezone.now().timestamp() + ttl
        return False, 0, int(reset_time)
    
    # Increment counter
    cache.set(cache_key, current_count + 1, time_window_seconds)
    remaining = limit - (current_count + 1)
    reset_time = timezone.now().timestamp() + time_window_seconds
    
    return True, remaining, int(reset_time)


def extract_api_key_from_request(request):
    """
    Extract API key from request headers.
    
    Checks:
    1. X-API-Key header
    2. Authorization: Bearer <key> header
    
    Args:
        request: Django request object
        
    Returns:
        API key string or None
    """
    # Check X-API-Key header
    api_key = request.META.get('HTTP_X_API_KEY')
    if api_key:
        return api_key
    
    # Check Authorization header
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]  # Remove 'Bearer ' prefix
    
    return None


def validate_domain_origin(api_key_record, origin):
    """
    Validate if the request origin is allowed for the API key.
    
    Args:
        api_key_record: WidgetAPIKey instance
        origin: Request origin (e.g., 'https://example.com')
        
    Returns:
        True if allowed, False otherwise
    """
    if not api_key_record.allowed_domains:
        # No restrictions
        return True
    
    if not origin:
        # No origin provided but restrictions exist
        return False
    
    # Normalize origin (remove protocol if needed)
    origin_normalized = origin.lower().rstrip('/')
    
    # Check if origin matches any allowed domain
    for allowed_domain in api_key_record.allowed_domains:
        allowed_normalized = allowed_domain.lower().rstrip('/')
        if origin_normalized == allowed_normalized or origin_normalized.endswith('.' + allowed_normalized):
            return True
    
    return False

