from rest_framework import serializers
from .models import Document, DocumentChunk
from core.serializers import AdminUserSerializer


class ExtractFromURLSerializer(serializers.Serializer):
    """Serializer for extract-from-url endpoint."""
    url = serializers.URLField(
        required=True,
        help_text="URL to extract content from"
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional document title (auto-extracted from page if not provided)"
    )


class DocumentChunkSerializer(serializers.ModelSerializer):
    """Serializer for DocumentChunk model."""
    
    class Meta:
        model = DocumentChunk
        fields = ['id', 'chunk_id', 'chunk_index', 'text', 'text_length', 
                  'question', 'is_vectorized', 'vector_id', 'vectorized_at', 'metadata', 
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for Document model."""
    uploaded_by = AdminUserSerializer(read_only=True)
    file = serializers.FileField(write_only=True, required=True, help_text="File to upload (form-data)")
    title = serializers.CharField(required=False, help_text="Document title (auto-detected from filename if not provided)")
    chunks = DocumentChunkSerializer(many=True, read_only=True, help_text="Document chunks (only included if requested)")
    
    class Meta:
        model = Document
        fields = ['id', 'title', 'file', 'file_url', 'file_type', 
                  'state', 'vector_status', 'processing_status', 'processing_error',
                  'vector_id', 'is_vectorized', 'vectorized_at', 'chunk_count', 
                  'uploaded_by', 'is_active', 'structured_text_qa_url',
                  'chunks', 'created_at', 'updated_at']
        read_only_fields = ['id', 'uploaded_by', 'file_url', 'file_type', 'state', 'vector_status',
                           'processing_status', 'processing_error', 'vector_id', 'is_vectorized', 
                           'vectorized_at', 'chunk_count', 'structured_text_qa_url',
                           'created_at', 'updated_at']
    
    def validate_file(self, value):
        """Validate uploaded file."""
        if value:
            # Get file extension
            file_name = value.name.lower()
            valid_extensions = ['.pdf', '.txt', '.docx', '.html']
            if not any(file_name.endswith(ext) for ext in valid_extensions):
                raise serializers.ValidationError(
                    "Invalid file type. Supported formats: PDF, TXT, DOCX, HTML"
                )
            
            # Check file size (10MB limit)
            if value.size > 10 * 1024 * 1024:
                raise serializers.ValidationError("File size exceeds 10MB limit")
        
        return value
    
    def to_representation(self, instance):
        """Customize representation to conditionally include chunks."""
        representation = super().to_representation(instance)
        
        # Only include chunks if explicitly requested via query parameter
        request = self.context.get('request')
        if request and request.query_params.get('include_chunks') == 'true':
            chunks = instance.chunks.all().order_by('chunk_index')
            representation['chunks'] = DocumentChunkSerializer(chunks, many=True).data
        else:
            # Remove chunks from representation if not requested
            representation.pop('chunks', None)
        
        return representation

