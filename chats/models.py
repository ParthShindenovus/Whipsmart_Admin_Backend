import uuid
from django.db import models
from django.utils import timezone


class Visitor(models.Model):
    """
    Visitor model for tracking unique visitors.
    Visitor IDs are auto-generated UUIDs created by the backend.
    Each visitor can have multiple sessions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, help_text="Unique visitor identifier")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True, help_text="Last time visitor was active")
    metadata = models.JSONField(default=dict, blank=True, help_text="Browser info, IP, etc.")
    
    class Meta:
        verbose_name = "Visitor"
        verbose_name_plural = "Visitors"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Visitor {self.id}"
    
    def update_last_seen(self):
        """Update last_seen_at timestamp."""
        from django.utils import timezone
        self.last_seen_at = timezone.now()
        self.save(update_fields=['last_seen_at'])


class Session(models.Model):
    """
    Session model for managing chat sessions.
    Sessions are created for new chats and are independent of admin users.
    The id field (UUID) serves as the session identifier.
    Each session is associated with a visitor (auto-created if not provided).
    """
    CONVERSATION_TYPE_CHOICES = [
        ('sales', 'Sales'),
        ('support', 'Support'),
        ('knowledge', 'Knowledge'),
        ('routing', 'Routing'),  # Initial state before selection
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visitor = models.ForeignKey(
        Visitor,
        on_delete=models.CASCADE,
        related_name='sessions',
        db_index=True,
        help_text="Visitor this session belongs to (auto-created if not provided)",
        null=False,
        blank=False
    )
    external_user_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Third-party user ID")
    conversation_type = models.CharField(
        max_length=20,
        choices=CONVERSATION_TYPE_CHOICES,
        default='routing',
        db_index=True,
        help_text="Type of conversation: sales, support, knowledge, or routing"
    )
    conversation_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Stores conversation-specific data (e.g., name, email, phone for sales/support)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Session expiration time (24h default, auto-set if not provided)")
    is_active = models.BooleanField(default=True, db_index=True, help_text="Whether the session is active")
    last_message = models.TextField(null=True, blank=True, help_text="Last message in the session (for frontend preview)")
    last_message_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last message")
    metadata = models.JSONField(default=dict, blank=True, help_text="Device info, etc.")
    
    class Meta:
        verbose_name = "Session"
        verbose_name_plural = "Sessions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['visitor']),
            models.Index(fields=['external_user_id']),
            models.Index(fields=['is_active']),
            models.Index(fields=['conversation_type']),
        ]
    
    def __str__(self):
        return f"Session {self.id}"
    
    def save(self, *args, **kwargs):
        """Set default expiration to 24 hours if not provided."""
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        # Ensure conversation_type has a default value
        if not self.conversation_type:
            self.conversation_type = 'routing'
        super().save(*args, **kwargs)
    
    def is_expired(self):
        """Check if session has expired."""
        if self.expires_at is None:
            return False  # Session never expires if expires_at is None
        return timezone.now() > self.expires_at


class ChatMessage(models.Model):
    """
    Chat message model for storing conversation messages.
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name='messages',
        db_column='session_id',
        help_text="Reference to the session (id field of Session model)"
    )
    message = models.TextField()
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    metadata = models.JSONField(default=dict, blank=True, help_text="RAG sources, car results")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    is_deleted = models.BooleanField(default=False, help_text="Soft delete flag")
    
    class Meta:
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['session', 'timestamp']),
            models.Index(fields=['is_deleted']),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.message[:50]}..."
    
    def save(self, *args, **kwargs):
        """Update session's last_message when a message is saved."""
        super().save(*args, **kwargs)
        # Update session's last_message field
        if not self.is_deleted:
            self.session.last_message = self.message[:500]  # Limit to 500 chars for preview
            self.session.last_message_at = self.timestamp
            self.session.save(update_fields=['last_message', 'last_message_at'])
