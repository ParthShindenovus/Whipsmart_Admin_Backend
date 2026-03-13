from django.contrib import admin
from .models import Session, ChatMessage, Visitor, MessageSuggestion


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    """Admin interface for Visitor model."""
    list_display = ['id', 'ip_address', 'name', 'email', 'phone', 'created_at', 'last_seen_at', 'session_count']
    list_filter = ['created_at', 'last_seen_at']
    search_fields = ['id', 'ip_address', 'name', 'email', 'phone']
    readonly_fields = ['id', 'created_at', 'last_seen_at']
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Identity', {
            'fields': ('id', 'ip_address')
        }),
        ('Profile Information', {
            'fields': ('name', 'email', 'phone')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_seen_at')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        })
    )
    
    def session_count(self, obj):
        return obj.sessions.count()
    session_count.short_description = 'Sessions'


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    """Admin interface for Session model."""
    list_display = ['id', 'visitor', 'external_user_id', 'is_active', 'status', 'expires_at', 'created_at', 'is_inactive']
    list_filter = ['is_active', 'status', 'expires_at', 'created_at', 'visitor']
    search_fields = ['id', 'external_user_id', 'visitor__id']
    readonly_fields = ['id', 'created_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['visitor']
    
    def is_inactive(self, obj):
        return obj.status == obj.Status.INACTIVE
    is_inactive.boolean = True
    is_inactive.short_description = 'Inactive'


class MessageSuggestionInline(admin.TabularInline):
    """Inline admin for MessageSuggestion model."""
    model = MessageSuggestion
    extra = 0
    readonly_fields = ['id', 'suggestion_type', 'is_clicked', 'clicked_at', 'created_at']
    fields = ['suggestion_text', 'suggestion_type', 'order', 'is_clicked', 'clicked_at']


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Admin interface for ChatMessage model."""
    list_display = ['id', 'session', 'role', 'message_preview', 'is_deleted', 'timestamp', 'suggestion_count']
    list_filter = ['role', 'is_deleted', 'timestamp']
    search_fields = ['message', 'session__id']
    readonly_fields = ['id', 'timestamp']
    date_hierarchy = 'timestamp'
    raw_id_fields = ['session']
    inlines = [MessageSuggestionInline]
    
    def message_preview(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_preview.short_description = 'Message'
    
    def suggestion_count(self, obj):
        return obj.suggestions.count()
    suggestion_count.short_description = 'Suggestions'


@admin.register(MessageSuggestion)
class MessageSuggestionAdmin(admin.ModelAdmin):
    """Admin interface for MessageSuggestion model."""
    list_display = ['id', 'message_preview', 'suggestion_text', 'suggestion_type', 'order', 'is_clicked', 'clicked_at', 'created_at']
    list_filter = ['suggestion_type', 'is_clicked', 'created_at']
    search_fields = ['suggestion_text', 'message__message', 'message__session__id']
    readonly_fields = ['id', 'created_at', 'clicked_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['message']
    
    def message_preview(self, obj):
        return obj.message.message[:50] + '...' if len(obj.message.message) > 50 else obj.message.message
    message_preview.short_description = 'Message'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('message', 'message__session')
