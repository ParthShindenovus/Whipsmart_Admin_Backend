import uuid
import secrets
import hashlib
from django.db import models
from django.utils import timezone
from django.conf import settings
from core.models import AdminUser


class WidgetAPIKey(models.Model):
    """
    Model for storing widget API keys.
    API keys are hashed before storage and never stored in plain text.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Hashed API key (never store plain text)
    api_key_hash = models.CharField(max_length=255, unique=True, db_index=True)
    
    # Prefix for display (e.g., "sk_live_abc123...")
    key_prefix = models.CharField(max_length=20)
    
    # Key metadata
    name = models.CharField(max_length=255, help_text="Display name for the API key")
    organization_id = models.UUIDField(null=True, blank=True, db_index=True)
    user = models.ForeignKey(
        AdminUser,
        on_delete=models.CASCADE,
        related_name='widget_api_keys',
        db_index=True
    )
    
    # Domain restrictions
    allowed_domains = models.JSONField(
        default=list,
        blank=True,
        help_text="List of allowed domains for CORS validation"
    )
    
    # Expiration
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True, db_index=True)
    
    # Usage tracking
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    # Additional metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)  # Soft delete
    
    class Meta:
        verbose_name = "Widget API Key"
        verbose_name_plural = "Widget API Keys"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['api_key_hash'], name='widget_api_key_hash_idx'),
            models.Index(fields=['organization_id'], name='widget_api_key_org_idx'),
            models.Index(fields=['user'], name='widget_api_key_user_idx'),
            models.Index(fields=['is_active'], condition=models.Q(deleted_at__isnull=True), name='widget_api_key_active_idx'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"
    
    @staticmethod
    def generate_api_key(prefix='sk_live_', length=32):
        """
        Generate a cryptographically secure API key.
        
        Args:
            prefix: Key prefix (e.g., 'sk_live_' or 'sk_test_')
            length: Length of random part (default: 32)
            
        Returns:
            Tuple of (full_key, key_prefix, key_hash)
        """
        # Generate random bytes
        random_part = secrets.token_urlsafe(length)
        full_key = f"{prefix}{random_part}"
        
        # Create hash
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()
        
        # Create prefix for display (first 12 chars of full key)
        display_prefix = full_key[:12] + "..."
        
        return full_key, display_prefix, key_hash
    
    @staticmethod
    def hash_api_key(api_key):
        """Hash an API key for comparison."""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    def is_expired(self):
        """Check if the API key is expired."""
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at
    
    def is_valid(self):
        """Check if the API key is valid (active and not expired)."""
        return self.is_active and not self.is_expired() and self.deleted_at is None
    
    def update_last_used(self):
        """Update the last used timestamp."""
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])


class WidgetConfig(models.Model):
    """
    Model for storing widget configuration per API key.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_key = models.OneToOneField(
        WidgetAPIKey,
        on_delete=models.CASCADE,
        related_name='widget_config',
        null=True,
        blank=True
    )
    
    # API URLs
    api_url = models.URLField(default='https://api.yourdomain.com')
    widget_url = models.URLField(default='https://cdn.yourdomain.com/widget')
    
    # Features
    features = models.JSONField(default=dict, blank=True)
    
    # Theme
    theme = models.JSONField(default=dict, blank=True)
    
    # Organization info
    organization_name = models.CharField(max_length=255, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Widget Configuration"
        verbose_name_plural = "Widget Configurations"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Widget Config - {self.organization_name or (self.api_key.name if self.api_key else 'Default')}"


class APIKeyUsageLog(models.Model):
    """
    Model for logging API key usage for analytics and security monitoring.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_key = models.ForeignKey(
        WidgetAPIKey,
        on_delete=models.CASCADE,
        related_name='usage_logs'
    )
    organization_id = models.UUIDField(null=True, blank=True)
    
    # Request details
    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Response details
    status_code = models.IntegerField()
    response_time = models.IntegerField(help_text="Response time in milliseconds")
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        verbose_name = "API Key Usage Log"
        verbose_name_plural = "API Key Usage Logs"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['api_key', '-timestamp']),
            models.Index(fields=['organization_id', '-timestamp']),
            models.Index(fields=['timestamp']),
        ]
    
    def __str__(self):
        return f"{self.api_key.key_prefix} - {self.endpoint} - {self.status_code}"
