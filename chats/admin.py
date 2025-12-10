from django.contrib import admin
from .models import Session, ChatMessage, Visitor


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    """Admin interface for Visitor model."""
    list_display = ['id', 'created_at', 'last_seen_at', 'session_count']
    list_filter = ['created_at', 'last_seen_at']
    search_fields = ['id']
    readonly_fields = ['id', 'created_at', 'last_seen_at']
    date_hierarchy = 'created_at'
    
    def session_count(self, obj):
        return obj.sessions.count()
    session_count.short_description = 'Sessions'


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    """Admin interface for Session model."""
    list_display = ['id', 'visitor', 'external_user_id', 'is_active', 'expires_at', 'created_at', 'is_expired']
    list_filter = ['is_active', 'expires_at', 'created_at', 'visitor']
    search_fields = ['id', 'external_user_id', 'visitor__id']
    readonly_fields = ['id', 'created_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['visitor']
    
    def is_expired(self, obj):
        return obj.is_expired()
    is_expired.boolean = True
    is_expired.short_description = 'Expired'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Admin interface for ChatMessage model."""
    list_display = ['id', 'session', 'role', 'message_preview', 'is_deleted', 'timestamp']
    list_filter = ['role', 'is_deleted', 'timestamp']
    search_fields = ['message', 'session__id']
    readonly_fields = ['id', 'timestamp']
    date_hierarchy = 'timestamp'
    raw_id_fields = ['session']
    
    def message_preview(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_preview.short_description = 'Message'
