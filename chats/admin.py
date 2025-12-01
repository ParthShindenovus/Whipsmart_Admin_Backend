from django.contrib import admin
from .models import Session, ChatMessage


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    """Admin interface for Session model."""
    list_display = ['session_id', 'external_user_id', 'is_active', 'expires_at', 'created_at', 'is_expired']
    list_filter = ['is_active', 'expires_at', 'created_at']
    search_fields = ['session_id', 'external_user_id']
    readonly_fields = ['id', 'created_at']
    date_hierarchy = 'created_at'
    
    def is_expired(self, obj):
        return obj.is_expired()
    is_expired.boolean = True
    is_expired.short_description = 'Expired'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Admin interface for ChatMessage model."""
    list_display = ['id', 'session', 'role', 'message_preview', 'is_deleted', 'timestamp']
    list_filter = ['role', 'is_deleted', 'timestamp']
    search_fields = ['message', 'session__session_id']
    readonly_fields = ['id', 'timestamp']
    date_hierarchy = 'timestamp'
    raw_id_fields = ['session']
    
    def message_preview(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_preview.short_description = 'Message'
