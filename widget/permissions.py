"""
Custom permission classes for API key authentication.
"""
from rest_framework import permissions
from .models import WidgetAPIKey


class RequiresAPIKey(permissions.BasePermission):
    """
    Permission class that requires API key authentication.
    
    Checks if request.auth is a WidgetAPIKey instance.
    """
    
    def has_permission(self, request, view):
        """
        Check if request has valid API key authentication.
        
        Returns True if request.auth is a WidgetAPIKey instance.
        """
        # Check if API key was authenticated
        api_key_record = getattr(request, 'auth', None)
        
        # API key authentication sets request.auth to WidgetAPIKey instance
        if api_key_record and isinstance(api_key_record, WidgetAPIKey):
            return True
        
        # Also check if middleware set it (for backward compatibility)
        api_key_record = getattr(request, 'api_key', None)
        if api_key_record and isinstance(api_key_record, WidgetAPIKey):
            return True
        
        return False
    
    def has_object_permission(self, request, view, obj):
        """
        Object-level permission check.
        For API keys, we allow access if API key is valid.
        """
        return self.has_permission(request, view)


