"""
Custom middleware to disable CSRF for API endpoints.
Since we're using JWT token authentication, CSRF is not needed for API endpoints.
"""
from django.utils.deprecation import MiddlewareMixin


class DisableCSRFForAPI(MiddlewareMixin):
    """
    Middleware to disable CSRF protection for API endpoints.
    API endpoints use JWT token authentication, so CSRF is not required.
    """
    
    def process_request(self, request):
        """Disable CSRF for API endpoints"""
        # Check if the request path starts with /api/
        if request.path.startswith('/api/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None


