import uuid
from django.db import models
from core.models import AdminUser


class Document(models.Model):
    """
    Document model for storing uploaded files (PDFs, Docs, TXT, HTML).
    Implements state management for document lifecycle.
    """
    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('txt', 'Text'),
        ('docx', 'Word Document'),
        ('html', 'HTML'),
        ('url', 'URL'),
    ]
    
    STATE_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('chunked', 'Chunked'),
        ('processing', 'Processing'),
        ('live', 'Live'),
        ('removed_from_vectordb', 'RemovedFromVectorDB'),
        ('deleted', 'Deleted'),
    ]
    
    VECTOR_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('chunking', 'Chunking'),
        ('embedding', 'Embedding'),
        ('uploading', 'Uploading'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('extracting', 'Extracting'),
        ('structuring', 'Structuring with LLM'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    file_url = models.URLField(help_text="URL to the document file (stored in media folder)")
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    
    # Structured text files (for PDFs - raw and processed Q&A format)
    structured_text_raw_url = models.URLField(
        blank=True, 
        null=True, 
        help_text="URL to raw extracted structured text file (for PDFs)"
    )
    structured_text_qa_url = models.URLField(
        blank=True, 
        null=True, 
        help_text="URL to processed Q&A format structured text file (for PDFs)"
    )
    
    # State management
    state = models.CharField(
        max_length=30, 
        choices=STATE_CHOICES, 
        default='uploaded',
        help_text="Current state of the document in the lifecycle"
    )
    vector_status = models.CharField(
        max_length=20,
        choices=VECTOR_STATUS_CHOICES,
        default='not_started',
        help_text="Status of vectorization process"
    )
    
    # PDF Processing status (for tracking async PDF extraction/structuring)
    processing_status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS_CHOICES,
        default='pending',
        help_text="Status of PDF extraction and structuring process"
    )
    processing_error = models.TextField(
        blank=True,
        null=True,
        help_text="Error message if PDF processing failed"
    )
    
    # Vectorization tracking
    vector_id = models.TextField(blank=True, null=True, help_text="Pinecone vector IDs (comma-separated)")
    is_vectorized = models.BooleanField(default=False, help_text="Whether document has been vectorized")
    vectorized_at = models.DateTimeField(null=True, blank=True, help_text="When document was vectorized")
    chunk_count = models.IntegerField(default=0, help_text="Number of chunks created")
    
    uploaded_by = models.ForeignKey(
        AdminUser,
        on_delete=models.CASCADE,
        related_name='documents',
        db_column='uploaded_by_id'
    )
    is_active = models.BooleanField(default=True, help_text="Whether the document is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['file_type']),
            models.Index(fields=['is_active']),
            models.Index(fields=['is_vectorized']),
            models.Index(fields=['state']),
            models.Index(fields=['vector_status']),
        ]
    
    def __str__(self):
        return self.title
    
    def can_delete(self):
        """Check if document can be deleted (only when not live in vector DB)."""
        return self.state in ('removed_from_vectordb', 'uploaded', 'chunked', 'processing')
    
    def is_live_in_vectordb(self):
        """Check if document is live in vector database."""
        return self.state == 'live' and self.is_vectorized


class DocumentChunk(models.Model):
    """
    Model to store document chunks in database.
    Each chunk has a unique chunk_id and belongs to a document.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='chunks',
        db_column='document_id'
    )
    chunk_id = models.CharField(
        max_length=255,
        help_text="Unique chunk identifier (format: {document_id}-chunk-{index})"
    )
    chunk_index = models.IntegerField(help_text="Index of chunk in the document")
    text = models.TextField(help_text="Text content of the chunk (answer for Q&A format)")
    text_length = models.IntegerField(help_text="Length of chunk text in characters")
    question = models.TextField(
        blank=True,
        null=True,
        help_text="Question label for this chunk (for Q&A format chunks)"
    )
    
    # Vectorization status
    is_vectorized = models.BooleanField(default=False, help_text="Whether chunk has been vectorized")
    vector_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Pinecone vector ID for this chunk"
    )
    vectorized_at = models.DateTimeField(null=True, blank=True, help_text="When chunk was vectorized")
    
    # Metadata stored in DB (also stored in Pinecone)
    metadata = models.JSONField(
        default=dict,
        help_text="Metadata for the chunk (document_id, title, file_type, etc.)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Document Chunk"
        verbose_name_plural = "Document Chunks"
        ordering = ['document', 'chunk_index']
        unique_together = [['document', 'chunk_id']]
        indexes = [
            models.Index(fields=['document', 'chunk_index']),
            models.Index(fields=['chunk_id']),
            models.Index(fields=['is_vectorized']),
        ]
    
    def __str__(self):
        return f"{self.document.title} - Chunk {self.chunk_index}"
