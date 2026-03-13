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
    
    # User contact information (collected after 3 questions)
    name = models.CharField(max_length=255, blank=True, null=True, help_text="Visitor's full name")
    email = models.EmailField(blank=True, null=True, help_text="Visitor's email address")
    phone = models.CharField(max_length=20, blank=True, null=True, help_text="Visitor's phone number")
    questions_asked = models.IntegerField(default=0, help_text="Number of questions asked by this visitor across all sessions")
    
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
    questions_asked = models.IntegerField(
        default=0,
        help_text="Number of questions asked in this session"
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


class MessageSuggestion(models.Model):
    """
    Model for storing suggestions generated for assistant messages.
    Each assistant message can have multiple suggestions for follow-up questions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name='suggestions',
        help_text="The assistant message this suggestion belongs to"
    )
    suggestion_text = models.CharField(
        max_length=200,
        help_text="The suggestion text displayed to the user"
    )
    suggestion_type = models.CharField(
        max_length=50,
        choices=[
            ('rag_related', 'RAG Related Question'),
            ('contextual', 'Contextual Suggestion'),
            ('conversion', 'Conversion Action'),
            ('fallback', 'Fallback Suggestion'),
        ],
        default='contextual',
        help_text="Type of suggestion generated"
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order of the suggestion (0-based)"
    )
    is_clicked = models.BooleanField(
        default=False,
        help_text="Whether this suggestion was clicked by the user"
    )
    clicked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the suggestion was clicked"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata like RAG sources, generation method, etc."
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        verbose_name = "Message Suggestion"
        verbose_name_plural = "Message Suggestions"
        ordering = ['message', 'order']
        indexes = [
            models.Index(fields=['message', 'order']),
            models.Index(fields=['suggestion_type']),
            models.Index(fields=['is_clicked']),
            models.Index(fields=['created_at']),
        ]
        unique_together = [['message', 'order']]
    
    def __str__(self):
        return f"Suggestion for {self.message.id}: {self.suggestion_text[:50]}..."
    
    def mark_clicked(self):
        """Mark this suggestion as clicked."""
        if not self.is_clicked:
            self.is_clicked = True
            self.clicked_at = timezone.now()
            self.save(update_fields=['is_clicked', 'clicked_at'])
