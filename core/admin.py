from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import AdminUser


@admin.register(AdminUser)
class AdminUserAdmin(BaseUserAdmin):
    """Admin interface for AdminUser model."""
    list_display = ['username', 'email', 'is_active_admin', 'is_staff', 'created_at']
    list_filter = ['is_active_admin', 'is_staff', 'is_superuser', 'created_at']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering = ['-created_at']
    
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Admin Status', {'fields': ('is_active_admin',)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Admin Status', {'fields': ('is_active_admin',)}),
    )
