from django.contrib import admin
from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Admin interface for Document model."""
    list_display = ['title', 'file_type', 'file_url', 'uploaded_by', 'is_vectorized', 'is_active', 'created_at']
    list_filter = ['file_type', 'is_active', 'is_vectorized', 'created_at']
    search_fields = ['title', 'file_url', 'uploaded_by__username']
    readonly_fields = ['id', 'file_url', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['uploaded_by']
