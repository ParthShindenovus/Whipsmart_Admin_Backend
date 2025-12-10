from django.contrib import admin
from .models import WidgetAPIKey, WidgetConfig, APIKeyUsageLog


@admin.register(WidgetAPIKey)
class WidgetAPIKeyAdmin(admin.ModelAdmin):
    """Admin interface for Widget API Keys."""
    list_display = [
        'key_prefix',
        'name',
        'user',
        'is_active',
        'expires_at',
        'last_used_at',
        'created_at',
    ]
    list_filter = [
        'is_active',
        'created_at',
        'expires_at',
    ]
    search_fields = [
        'name',
        'key_prefix',
        'user__username',
    ]
    readonly_fields = [
        'id',
        'api_key_hash',
        'key_prefix',
        'created_at',
        'updated_at',
        'last_used_at',
    ]
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'name', 'user')
        }),
        ('API Key Details', {
            'fields': ('api_key_hash', 'key_prefix', 'is_active', 'expires_at')
        }),
        ('Domain Restrictions', {
            'fields': ('allowed_domains',)
        }),
        ('Metadata', {
            'fields': ('metadata',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_used_at', 'deleted_at')
        }),
    )


@admin.register(WidgetConfig)
class WidgetConfigAdmin(admin.ModelAdmin):
    """Admin interface for Widget Configuration."""
    list_display = [
        'organization_name',
        'api_url',
        'widget_url',
        'created_at',
    ]
    search_fields = [
        'organization_name',
    ]
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(APIKeyUsageLog)
class APIKeyUsageLogAdmin(admin.ModelAdmin):
    """Admin interface for API Key Usage Logs."""
    list_display = [
        'api_key',
        'endpoint',
        'method',
        'status_code',
        'ip_address',
        'timestamp',
    ]
    list_filter = [
        'status_code',
        'method',
        'timestamp',
    ]
    search_fields = [
        'api_key__key_prefix',
        'endpoint',
        'ip_address',
    ]
    readonly_fields = [
        'id',
        'api_key',
        'endpoint',
        'method',
        'ip_address',
        'user_agent',
        'status_code',
        'response_time',
        'timestamp',
    ]
    date_hierarchy = 'timestamp'
