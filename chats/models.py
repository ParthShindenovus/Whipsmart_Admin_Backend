import uuid
from django.db import models
from django.utils import timezone


class Session(models.Model):
    """
    Session model for managing chat sessions.
    Sessions are created for new chats and are independent of admin users.
    The id field (UUID) serves as the session identifier.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_user_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Third-party user ID")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Session expiration time (24h default, auto-set if not provided)")
    is_active = models.BooleanField(default=True, db_index=True, help_text="Whether the session is active")
    metadata = models.JSONField(default=dict, blank=True, help_text="Device info, etc.")
    
    class Meta:
        verbose_name = "Session"
        verbose_name_plural = "Sessions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['external_user_id']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"Session {self.id}"
    
    def save(self, *args, **kwargs):
        """Set default expiration to 24 hours if not provided."""
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)
    
    def is_expired(self):
        """Check if session has expired."""
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
