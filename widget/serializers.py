from rest_framework import serializers
from django.utils import timezone
from .models import WidgetAPIKey, WidgetConfig


class WidgetAPIKeyCreateSerializer(serializers.Serializer):
    """Serializer for creating a new API key."""
    name = serializers.CharField(max_length=255, required=True)
    allowed_domains = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    metadata = serializers.JSONField(required=False, default=dict)
    
    def validate_expires_at(self, value):
        """Ensure expiration date is in the future."""
        if value and value <= timezone.now():
            raise serializers.ValidationError("Expiration date must be in the future.")
        return value


class WidgetAPIKeySerializer(serializers.ModelSerializer):
    """Serializer for API key (without exposing the actual key)."""
    class Meta:
        model = WidgetAPIKey
        fields = [
            'id',
            'key_prefix',
            'name',
            'user',
            'allowed_domains',
            'created_at',
            'expires_at',
            'is_active',
            'last_used_at',
            'metadata',
        ]
        read_only_fields = [
            'id',
            'key_prefix',
            'user',
            'created_at',
            'last_used_at',
        ]


class WidgetAPIKeyCreateResponseSerializer(serializers.Serializer):
    """Serializer for API key creation response (includes the actual key once)."""
    id = serializers.UUIDField()
    api_key = serializers.CharField()  # Only shown once during creation
    key_prefix = serializers.CharField()
    name = serializers.CharField()
    user = serializers.UUIDField()
    allowed_domains = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True)
    is_active = serializers.BooleanField()
    last_used_at = serializers.DateTimeField(allow_null=True)
    metadata = serializers.JSONField()


class WidgetAPIKeyRegenerateResponseSerializer(serializers.Serializer):
    """Serializer for API key regeneration response."""
    id = serializers.UUIDField()
    api_key = serializers.CharField()  # Only shown once during regeneration
    key_prefix = serializers.CharField()
    regenerated_at = serializers.DateTimeField()


class WidgetConfigSerializer(serializers.ModelSerializer):
    """Serializer for widget configuration."""
    class Meta:
        model = WidgetConfig
        fields = [
            'api_url',
            'widget_url',
            'features',
            'theme',
            'organization_name',
        ]


class EmbedCodeSerializer(serializers.Serializer):
    """Serializer for embed code generation."""
    embed_code = serializers.CharField(help_text="Formatted embed code with comments - ready to copy and paste")
    embed_code_oneline = serializers.CharField(help_text="One-line embed code for easy copying")
    instructions = serializers.CharField(help_text="Step-by-step instructions for embedding the widget")
    api_key_prefix = serializers.CharField(help_text="API key prefix for display")
    api_key_id = serializers.UUIDField(help_text="API key ID")
    widget_url = serializers.URLField(help_text="Widget CDN URL")
    api_url = serializers.URLField(help_text="API base URL")
    widget_loader_url = serializers.URLField(help_text="Widget loader script URL")
    note = serializers.CharField(help_text="Important note about API key")
    is_ready_to_use = serializers.BooleanField(help_text="True if embed code includes full API key and is ready to use")

