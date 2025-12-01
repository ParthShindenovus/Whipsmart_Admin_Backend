import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class AdminUser(AbstractUser):
    """
    Custom user model extending AbstractUser for admin users.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_active_admin = models.BooleanField(default=True, help_text="Designates whether this admin user is active.")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Admin User"
        verbose_name_plural = "Admin Users"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.username
