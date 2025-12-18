from rest_framework import viewsets, views, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied
from drf_spectacular.utils import extend_schema_view, extend_schema
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from pathlib import Path
import logging
import uuid

logger = logging.getLogger(__name__)
from .models import Document, DocumentChunk
from .serializers import DocumentSerializer, ExtractFromURLSerializer
from .services.vectorization_service import vectorize_document, delete_document_vectors, search_documents
from .services.document_processor import process_document
from .services.url_extractor import extract_content_from_url, validate_url
from core.views_base import StandardizedResponseMixin
from core.utils import success_response, error_response


@extend_schema_view(
    list=extend_schema(
        summary="List all documents",
        description="Retrieve a list of all documents. Requires authentication.",
        tags=['Documents'],
    ),
    create=extend_schema(
        summary="Upload new document",
        description="Upload a new document (PDF, TXT, DOCX, HTML) using form-data. The file will be saved to the media folder and the URL will be stored in the database. Title and file_type are automatically extracted from the uploaded file (title from filename, file_type from extension). For PDFs, the document is extracted and structured using LLM in Q&A format asynchronously in the background - the document is saved immediately and structured_text_qa_url will be populated when processing completes. Only the structured Q&A text file is created (no raw extracted file). This structured file is used for chunking. Maximum file size: 100MB. Requires authentication.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Document file to upload (PDF, TXT, DOCX, HTML). Title and file_type are auto-detected from the file. Max size: 100MB.'
                    },
                    'title': {
                        'type': 'string',
                        'description': 'Document title (optional, defaults to filename without extension)'
                    },
                    'filename': {
                        'type': 'string',
                        'description': 'Optional: Custom filename for PDF metadata (used in Q&A chunks). Only applies to PDFs.'
                    },
                    'reference_url': {
                        'type': 'string',
                        'description': 'Optional: Reference URL for PDF metadata (used in Q&A chunks). Only applies to PDFs.'
                    }
                },
                'required': ['file']
            }
        },
        tags=['Documents'],
    ),
    retrieve=extend_schema(
        summary="Get document details",
        description="Retrieve detailed information about a specific document.",
        tags=['Documents'],
    ),
    update=extend_schema(exclude=True),  # Hide update endpoint
    partial_update=extend_schema(exclude=True),  # Hide partial update endpoint
    destroy=extend_schema(
        summary="Delete document",
        description="Delete a document. Requires authentication.",
        tags=['Documents'],
    ),
)
class DocumentViewSet(StandardizedResponseMixin, viewsets.ModelViewSet):
    """
    ViewSet for Document model.
    
    Manages document uploads and metadata. Supports file uploads for PDF, TXT, DOCX, and HTML.
    """
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ['title', 'file_type']
    filterset_fields = ['file_type', 'is_active', 'uploaded_by']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Filter documents by current user if not superuser."""
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(uploaded_by=self.request.user)
        return queryset
    
    def validate_document_id(self, pk):
        """Validate document ID is a valid UUID."""
        if not pk or pk == 'undefined' or pk == 'null':
            return error_response(
                'Document ID is required and must be a valid UUID. Please provide a valid document ID.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate UUID format
        try:
            uuid.UUID(str(pk))
        except (ValueError, TypeError):
            return error_response(
                f'Invalid document ID format: "{pk}". Document ID must be a valid UUID.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        return None  # Validation passed
    
    def perform_create(self, serializer):
        """Handle file upload, save to media folder, and set file_url. Auto-detect title and file_type from file."""
        uploaded_file = serializer.validated_data.pop('file', None)
        
        if not uploaded_file:
            raise ValidationError({'file': 'File is required'})
        
        # Check file size
        max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 100 * 1024 * 1024)  # Default 100MB
        if uploaded_file.size > max_size:
            raise ValidationError({
                'file': f'File size exceeds maximum allowed size of {max_size / (1024 * 1024):.1f}MB'
            })
        
        # Extract file name and extension
        from pathlib import Path
        from datetime import datetime
        import threading
        file_path_obj = Path(uploaded_file.name)
        file_name = uploaded_file.name
        file_stem = file_path_obj.stem  # Filename without extension
        file_extension = file_path_obj.suffix.lower()  # Extension with dot
        
        # Auto-detect file type from extension (always auto-detect, don't accept from request)
        file_type_map = {
            '.pdf': 'pdf',
            '.txt': 'txt',
            '.docx': 'docx',
            '.html': 'html'
        }
        
        file_type = file_type_map.get(file_extension)
        if not file_type:
            raise ValidationError({'file': f'Unsupported file type. Supported extensions: {", ".join(file_type_map.keys())}'})
        serializer.validated_data['file_type'] = file_type
        
        # Auto-detect title from filename (without extension) if not provided
        title = serializer.validated_data.get('title')
        if not title:
            # Use filename without extension as title
            title = file_stem
            serializer.validated_data['title'] = title
        
        # Generate file path in media folder, separated by environment (development vs production)
        env_folder = 'development' if settings.DEBUG else 'production'
        now = datetime.now()
        file_path = f'{env_folder}/documents/{now.year}/{now.month:02d}/{now.day:02d}/{file_name}'
        
        # Save file to media folder (default_storage is imported at module level)
        file_name_saved = default_storage.save(file_path, uploaded_file)
        
        # Build file URL
        if settings.DEBUG:
            # In development, use request to build absolute URL
            file_url = self.request.build_absolute_uri(settings.MEDIA_URL + file_name_saved)
        else:
            # In production, use MEDIA_URL setting
            file_url = f"{settings.MEDIA_URL}{file_name_saved}"
        
        # Save document immediately (without structured text URL for PDFs)
        # PDF processing will happen asynchronously
        document = serializer.save(
            uploaded_by=self.request.user,
            file_url=file_url,
            title=title,
            file_type=file_type,
            state='uploaded',
            structured_text_raw_url=None,  # Not used - we only create Q&A structured file
            structured_text_qa_url=None,  # Will be populated after async processing
            processing_status='pending' if file_type == 'pdf' else 'completed'  # Track PDF processing status
        )
        
        # For PDFs, extract data and structure with LLM (Q&A format) asynchronously
        if file_type == 'pdf':
            # Get optional parameters from request
            user_filename = serializer.validated_data.pop('filename', None) or self.request.data.get('filename', '').strip() or None
            reference_url = serializer.validated_data.pop('reference_url', None) or self.request.data.get('reference_url', '').strip() or None
            
            # Get host for URL building
            host = self.request.get_host() if hasattr(self.request, 'get_host') else 'localhost:8000'
            protocol = 'https' if self.request.is_secure() else 'http'
            
            # Process PDF in background thread to avoid blocking the response
            def process_pdf_async():
                try:
                    from knowledgebase.services.pdf_extractor import process_uploaded_pdf
                    
                    # Update status to extracting
                    document.processing_status = 'extracting'
                    document.processing_error = None
                    document.save(update_fields=['processing_status', 'processing_error'])
                    
                    # Re-open the file from storage
                    file_path_full = Path(settings.MEDIA_ROOT) / file_name_saved
                    if not file_path_full.exists():
                        logger.error(f"File not found for PDF processing: {file_path_full}")
                        document.processing_status = 'failed'
                        document.processing_error = f"File not found: {file_path_full}"
                        document.save(update_fields=['processing_status', 'processing_error'])
                        return
                    
                    # Create a file wrapper that implements Django UploadedFile interface
                    class FileWrapper:
                        def __init__(self, file_path, name):
                            self.file_path = Path(file_path) if not isinstance(file_path, Path) else file_path
                            self.name = name
                            self.size = self.file_path.stat().st_size if self.file_path.exists() else 0
                        
                        def read(self, size=-1):
                            with open(self.file_path, 'rb') as f:
                                return f.read(size)
                        
                        def chunks(self, chunk_size=8192):
                            """Read file in chunks, mimicking Django UploadedFile.chunks()"""
                            with open(self.file_path, 'rb') as f:
                                while True:
                                    chunk = f.read(chunk_size)
                                    if not chunk:
                                        break
                                    yield chunk
                        
                        def seek(self, pos):
                            # Not needed for chunks() method, but included for compatibility
                            pass
                        
                        def tell(self):
                            # Not needed for chunks() method, but included for compatibility
                            return 0
                    
                    wrapped_file = FileWrapper(file_path_full, file_name)
                    
                    # Update status to structuring
                    document.processing_status = 'structuring'
                    document.save(update_fields=['processing_status'])
                    
                    logger.info(f"Extracting and structuring PDF with LLM (Q&A format): {file_name}")
                    # Process PDF: extract data, structure with LLM, Q&A format, NO raw file
                    output_paths = process_uploaded_pdf(
                        uploaded_file=wrapped_file,
                        use_llm=True,  # Use LLM for structuring
                        qa_format=True,  # Q&A format for RAG
                        user_filename=user_filename,
                        reference_url=reference_url,
                        save_raw=False  # Don't create raw file - only structured Q&A file
                    )
                    
                    # Build URL for structured Q&A text file (only file we create)
                    base_dir = Path(settings.BASE_DIR)
                    processed_path = output_paths.get('processed_path')
                    
                    structured_text_qa_url = None
                    
                    if processed_path and processed_path.exists():
                        # Convert absolute path to relative path from BASE_DIR
                        rel_processed_path = processed_path.relative_to(base_dir)
                        if settings.DEBUG:
                            structured_text_qa_url = f"{protocol}://{host}/{rel_processed_path.as_posix()}"
                        else:
                            structured_text_qa_url = f"/{rel_processed_path.as_posix()}"
                        
                        # Update document with structured Q&A text URL and mark as completed
                        document.structured_text_qa_url = structured_text_qa_url
                        document.processing_status = 'completed'
                        document.processing_error = None
                        document.save(update_fields=['structured_text_qa_url', 'processing_status', 'processing_error'])
                        
                        logger.info(f"Successfully created structured Q&A text file for document {document.id}: {structured_text_qa_url}")
                    else:
                        logger.warning(f"Structured Q&A file was not created for document {document.id}")
                        document.processing_status = 'failed'
                        document.processing_error = "Structured Q&A file was not created"
                        document.save(update_fields=['processing_status', 'processing_error'])
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error creating structured Q&A text file for PDF {file_name}: {e}", exc_info=True)
                    # Update document with error status
                    document.processing_status = 'failed'
                    document.processing_error = error_msg
                    document.save(update_fields=['processing_status', 'processing_error'])
            
            # Start background processing
            thread = threading.Thread(target=process_pdf_async)
            thread.daemon = True
            thread.start()
            logger.info(f"Started background PDF extraction and structuring for document {document.id}")
    
    @extend_schema(
        summary="Chunk document",
        description="Process a document and create chunks stored in database. This extracts text and chunks it without vectorizing.",
        request=None,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'chunks_created': {'type': 'integer'},
                    'message': {'type': 'string'},
                }
            }
        },
        tags=['Documents'],
    )
    @action(detail=True, methods=['post'], url_path='chunk')
    def chunk(self, request, pk=None):
        """Chunk a document and store chunks in database. For PDFs with structured text, parses Q&A pairs."""
        # Validate document ID
        validation_error = self.validate_document_id(pk)
        if validation_error:
            return validation_error
        
        document = self.get_object()
        
        # Check if document is in valid state
        if document.state not in ('uploaded', 'chunked'):
            return Response({
                'success': False,
                'message': f'Document must be in "uploaded" state. Current state: {document.state}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Process document and save chunks to DB
        try:
            logger.info(f"Starting chunking for document {document.id} (file_url: {document.file_url}, file_type: {document.file_type})")
            
            # For PDFs, use structured Q&A text file (created during upload with LLM)
            if document.file_type == 'pdf':
                if not document.structured_text_qa_url:
                    return error_response(
                        'Structured Q&A text file is not ready yet. Please wait for PDF processing to complete and try again.',
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                
                logger.info(f"Using structured Q&A text file for document {document.id}")
                
                # Read structured Q&A text file
                qa_file_path = self._get_file_path_from_url(document.structured_text_qa_url)
                if not qa_file_path.exists():
                    logger.warning(f"Structured Q&A file not found: {qa_file_path}")
                    return error_response(
                        'Structured Q&A text file not found. The file may still be processing or there was an error during PDF extraction.',
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                
                with open(qa_file_path, 'r', encoding='utf-8') as f:
                    structured_text = f.read()
                
                # Parse Q&A pairs
                from knowledgebase.services.pdf_extractor import parse_qa_structure
                
                logger.info(f"Parsing Q&A structure from file. File length: {len(structured_text)} characters")
                logger.debug(f"First 500 chars of structured text: {structured_text[:500]}")
                
                qa_pairs = parse_qa_structure(structured_text, document.title)
                
                logger.info(f"Parsed {len(qa_pairs)} Q&A pairs from structured text")
                
                if not qa_pairs:
                    logger.error(f"No Q&A pairs parsed from structured text for document {document.id}")
                    logger.error(f"Structured text preview (first 1000 chars): {structured_text[:1000]}")
                    return error_response(
                        f'No Q&A pairs found in structured text file. File length: {len(structured_text)} chars. Please ensure the document was properly processed. Check server logs for details.',
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                
                # Delete existing chunks for this document
                DocumentChunk.objects.filter(document=document).delete()
                
                # Create DocumentChunk records from Q&A pairs
                chunks_created = []
                for idx, qa_pair in enumerate(qa_pairs):
                    chunk_id = f"{document.id}-chunk-{idx}"
                    chunk_text = qa_pair.get('answer', '')
                    question = qa_pair.get('question', '')
                    
                    # Build metadata
                    metadata = {
                        'document_id': str(document.id),
                        'title': qa_pair.get('title', document.title),
                        'file_type': document.file_type,
                        'page': qa_pair.get('page', 'N/A'),
                        'filename': qa_pair.get('filename', document.title),
                        'section': qa_pair.get('section', ''),
                        'description': qa_pair.get('description', ''),
                        'reference_url': qa_pair.get('reference_url', 'N/A'),
                    }
                    
                    chunk = DocumentChunk.objects.create(
                        document=document,
                        chunk_id=chunk_id,
                        chunk_index=idx,
                        text=chunk_text,
                        text_length=len(chunk_text),
                        question=question,
                        metadata=metadata
                    )
                    chunks_created.append(chunk)
                
                # Update document state and chunk count
                document.state = 'chunked'
                document.chunk_count = len(chunks_created)
                document.save(update_fields=['state', 'chunk_count'])
                
                logger.info(f"Successfully created {len(chunks_created)} Q&A chunks for document {document.id}")
                return success_response(
                    {
                        'chunks_created': len(chunks_created),
                        'document_id': str(document.id),
                        'document_title': document.title,
                        'state': document.state,
                        'chunk_type': 'qa_pairs'
                    },
                    message=f'Document chunked successfully. {len(chunks_created)} Q&A chunks created.'
                )
            else:
                # Regular document processing (non-PDF or PDF without structured text)
                return self._chunk_regular_document(document)
                
        except FileNotFoundError as e:
            logger.error(f"File not found error for document {document.id}: {str(e)}")
            return error_response(
                f'File not found: {str(e)}. Please ensure the file exists at the specified location.',
                status_code=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            logger.error(f"Value error for document {document.id}: {str(e)}")
            return error_response(
                f'Invalid file URL or path: {str(e)}',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error chunking document {document.id}: {str(e)}", exc_info=True)
            return error_response(
                f'Error chunking document: {str(e)}. Please check the file format and try again.',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _chunk_regular_document(self, document):
        """Helper method to chunk regular documents (non-PDF or PDF without structured text)."""
        processed_chunks = process_document(
            file_url=document.file_url,
            file_type=document.file_type,
            document_id=str(document.id),
            title=document.title,
            save_to_db=True
        )
        
        if processed_chunks:
            logger.info(f"Successfully created {len(processed_chunks)} chunks for document {document.id}")
            document.refresh_from_db()
            return success_response(
                {
                    'chunks_created': len(processed_chunks),
                    'document_id': str(document.id),
                    'document_title': document.title,
                    'state': document.state,
                    'chunk_type': 'regular'
                },
                message=f'Document chunked successfully. {len(processed_chunks)} chunks created.'
            )
        else:
            logger.warning(f"No chunks created for document {document.id} - no text extracted")
            return error_response(
                'No text extracted from document. The file may be empty, corrupted, or in an unsupported format.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
    
    def _get_file_path_from_url(self, url: str) -> Path:
        """Helper method to convert URL to file path. Handles both media URLs and structured text URLs."""
        from django.conf import settings
        from urllib.parse import urlparse, unquote
        
        # Remove protocol and domain if present
        if url.startswith('http://') or url.startswith('https://'):
            parsed = urlparse(url)
            url_path = parsed.path
        else:
            url_path = url
        
        # Decode URL-encoded characters (e.g., %20 -> space)
        url_path = unquote(url_path)
        
        # Remove leading slash
        url_path = url_path.lstrip('/')
        
        # Check if it's a media URL (starts with media/ or /media/)
        if url_path.startswith('media/') or url_path.startswith('media/'):
            # Use media root
            file_path = Path(settings.MEDIA_ROOT) / url_path.replace('media/', '', 1).lstrip('/')
        else:
            # Assume it's a relative path from BASE_DIR (for structured text files)
            base_dir = Path(settings.BASE_DIR)
            file_path = base_dir / url_path
        
        return file_path
    
    @extend_schema(
        summary="Get document processing status",
        description="Get the current processing status of a document. Useful for checking PDF extraction/structuring progress.",
        request=None,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'data': {
                        'type': 'object',
                        'properties': {
                            'document_id': {'type': 'string'},
                            'processing_status': {'type': 'string'},
                            'processing_error': {'type': 'string'},
                            'structured_text_qa_url': {'type': 'string'},
                            'is_ready_for_chunking': {'type': 'boolean'}
                        }
                    }
                }
            }
        },
        tags=['Documents'],
    )
    @action(detail=True, methods=['get'], url_path='processing-status')
    def processing_status(self, request, pk=None):
        """Get document processing status."""
        # Validate document ID
        validation_error = self.validate_document_id(pk)
        if validation_error:
            return validation_error
        
        document = self.get_object()
        
        # Check if document is ready for chunking (PDFs need structured_text_qa_url)
        is_ready_for_chunking = True
        if document.file_type == 'pdf':
            is_ready_for_chunking = document.processing_status == 'completed' and document.structured_text_qa_url is not None
        
        return success_response(
            {
                'document_id': str(document.id),
                'processing_status': document.processing_status,
                'processing_error': document.processing_error,
                'structured_text_qa_url': document.structured_text_qa_url,
                'is_ready_for_chunking': is_ready_for_chunking,
                'file_type': document.file_type
            },
            message='Document processing status retrieved successfully'
        )
    
    @extend_schema(
        summary="Vectorize document",
        description="Vectorize a document and upload chunks to Pinecone. Document must be chunked first. Uses chunks from database.",
        request=None,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'chunks_created': {'type': 'integer'},
                    'vectors_uploaded': {'type': 'integer'},
                    'message': {'type': 'string'},
                }
            }
        },
        tags=['Documents'],
    )
    @action(detail=True, methods=['post'], url_path='vectorize')
    def vectorize(self, request, pk=None):
        """Vectorize a document and upload to Pinecone."""
        # Validate document ID
        validation_error = self.validate_document_id(pk)
        if validation_error:
            return validation_error
        
        document = self.get_object()
        
        # Check if already vectorized/live
        if document.state == 'live':
            return Response({
                'success': False,
                'message': 'Document is already live in vector database. Remove from vector DB first to re-vectorize.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if document is chunked
        if document.state not in ('chunked', 'processing', 'removed_from_vectordb'):
            return Response({
                'success': False,
                'message': f'Document must be chunked first. Current state: {document.state}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Vectorize document (uses chunks from DB)
        result = vectorize_document(document, use_db_chunks=True)
        
        if result['success']:
            return Response({
                'success': True,
                'chunks_created': result.get('chunks_created', 0),
                'vectors_uploaded': result.get('vectors_uploaded', 0),
                'message': f'Document vectorized successfully. {result.get("vectors_uploaded", 0)} vectors uploaded to Pinecone.'
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'message': result.get('error', 'Failed to vectorize document')
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @extend_schema(
        summary="Get document chunks",
        description="Retrieve all chunks for a specific document. Returns list of chunks with their text, metadata, and vectorization status.",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'document_id': {'type': 'string'},
                    'document_title': {'type': 'string'},
                    'total_chunks': {'type': 'integer'},
                    'chunks': {
                        'type': 'array',
                        'items': {'$ref': '#/components/schemas/DocumentChunk'}
                    }
                }
            }
        },
        tags=['Documents'],
    )
    @action(detail=True, methods=['get'], url_path='chunks')
    def get_chunks(self, request, pk=None):
        """Get all chunks for a document."""
        # Validate document ID
        validation_error = self.validate_document_id(pk)
        if validation_error:
            return validation_error
        
        document = self.get_object()
        
        chunks = DocumentChunk.objects.filter(document=document).order_by('chunk_index')
        
        from .serializers import DocumentChunkSerializer
        chunk_serializer = DocumentChunkSerializer(chunks, many=True)
        
        return Response({
            'document_id': str(document.id),
            'document_title': document.title,
            'total_chunks': chunks.count(),
            'chunks': chunk_serializer.data
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Remove document from vector DB",
        description="Remove all vectors associated with a document from Pinecone. Document state will change to 'removed_from_vectordb'. No request body required.",
        request=None,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'message': {'type': 'string'},
                }
            }
        },
        tags=['Documents'],
    )
    @action(detail=True, methods=['post'], url_path='remove-from-vectordb')
    def remove_from_vectordb(self, request, pk=None):
        """Remove document vectors from Pinecone."""
        # Validate document ID
        validation_error = self.validate_document_id(pk)
        if validation_error:
            return validation_error
        
        document = self.get_object()
        
        if document.state != 'live':
            return Response({
                'success': False,
                'message': f'Document is not live in vector database. Current state: {document.state}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Delete vectors
        success = delete_document_vectors(document)
        
        if success:
            return Response({
                'success': True,
                'message': 'Document removed from vector database successfully'
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'message': 'Failed to remove document from vector database'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def perform_destroy(self, instance):
        """Override delete to check if document can be deleted."""
        if not instance.can_delete():
            raise PermissionDenied(
                f'Document cannot be deleted. Current state: {instance.state}. '
                'Remove from vector database first.'
            )
        
        # Delete associated chunks
        DocumentChunk.objects.filter(document=instance).delete()
        
        # Helper to delete any local file referenced by URL (original or extracted)
        def _delete_local_file(url: str):
            if not url:
                return
            try:
                file_path = self._get_file_path_from_url(url)
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Deleted file at {file_path}")
            except Exception as e:
                logger.warning(f"Error deleting file {url}: {str(e)}")
        
        # Delete original uploaded file
        _delete_local_file(instance.file_url)
        # Delete structured/extracted files if present
        _delete_local_file(getattr(instance, 'structured_text_qa_url', None))
        _delete_local_file(getattr(instance, 'structured_text_raw_url', None))
        
        # Update state to deleted before actual deletion
        instance.state = 'deleted'
        instance.save(update_fields=['state'])
        
        # Delete document
        super().perform_destroy(instance)
    
    @extend_schema(
        summary="Download document",
        description="Download a document file. Returns the file with appropriate content type for download.",
        responses={
            200: {'description': 'File download'},
            404: {'description': 'Document or file not found'}
        },
        tags=['Documents'],
    )
    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        """Download a document file."""
        # Validate document ID
        validation_error = self.validate_document_id(pk)
        if validation_error:
            return validation_error
        
        document = self.get_object()
        
        if not document.file_url:
            raise Http404("Document file URL not found")
        
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(document.file_url)
            
            # Get file path
            if parsed_url.netloc in ('localhost', '127.0.0.1', '') or 'localhost' in parsed_url.netloc:
                # Local file
                url_path = parsed_url.path
                if url_path.startswith(settings.MEDIA_URL):
                    url_path = url_path[len(settings.MEDIA_URL):]
                file_path = Path(settings.MEDIA_ROOT) / url_path.lstrip('/')
                
                if not file_path.exists():
                    raise Http404("File not found")
                
                # Determine content type
                content_type_map = {
                    'pdf': 'application/pdf',
                    'txt': 'text/plain',
                    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'html': 'text/html',
                }
                content_type = content_type_map.get(document.file_type, 'application/octet-stream')
                
                # Return file response for download
                response = FileResponse(
                    open(file_path, 'rb'),
                    content_type=content_type,
                    as_attachment=True,
                    filename=Path(file_path).name
                )
                return response
            else:
                # Remote URL - redirect to URL
                from django.shortcuts import redirect
                return redirect(document.file_url)
        except Exception as e:
            logger.error(f"Error downloading document {document.id}: {str(e)}")
            raise Http404("Error accessing file")
    
    @extend_schema(
        summary="View document in browser",
        description="View a document file in browser (inline display). Returns the file with appropriate content type for viewing.",
        responses={
            200: {'description': 'File view'},
            404: {'description': 'Document or file not found'}
        },
        tags=['Documents'],
    )
    @action(detail=True, methods=['get'], url_path='view')
    def view(self, request, pk=None):
        """View a document file in browser."""
        # Validate document ID
        validation_error = self.validate_document_id(pk)
        if validation_error:
            return validation_error
        
        document = self.get_object()
        
        if not document.file_url:
            raise Http404("Document file URL not found")
        
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(document.file_url)
            
            # Get file path
            if parsed_url.netloc in ('localhost', '127.0.0.1', '') or 'localhost' in parsed_url.netloc:
                # Local file
                url_path = parsed_url.path
                if url_path.startswith(settings.MEDIA_URL):
                    url_path = url_path[len(settings.MEDIA_URL):]
                file_path = Path(settings.MEDIA_ROOT) / url_path.lstrip('/')
                
                if not file_path.exists():
                    raise Http404("File not found")
                
                # Determine content type
                content_type_map = {
                    'pdf': 'application/pdf',
                    'txt': 'text/plain',
                    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'html': 'text/html',
                }
                content_type = content_type_map.get(document.file_type, 'application/octet-stream')
                
                # Return file response for inline viewing
                response = FileResponse(
                    open(file_path, 'rb'),
                    content_type=content_type,
                    as_attachment=False  # Inline viewing
                )
                return response
            else:
                # Remote URL - redirect to URL
                from django.shortcuts import redirect
                return redirect(document.file_url)
        except Exception as e:
            logger.error(f"Error viewing document {document.id}: {str(e)}")
            raise Http404("Error accessing file")
    
    @extend_schema(
        summary="Extract content from URL",
        description="Extract content from a URL and create a new document. The URL will be processed, chunked, and can be vectorized. Requires authentication.",
        request=ExtractFromURLSerializer,
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'document_id': {'type': 'string', 'format': 'uuid', 'example': '123e4567-e89b-12d3-a456-426614174000'},
                    'title': {'type': 'string', 'example': 'Example Article Title'},
                    'chunks_created': {'type': 'integer', 'example': 15},
                    'message': {'type': 'string', 'example': 'Successfully extracted content from URL. 15 chunks created.'},
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'message': {'type': 'string', 'example': 'URL is required'},
                }
            }
        },
        tags=['Documents'],
    )
    @action(detail=False, methods=['post'], url_path='extract-from-url')
    def extract_from_url(self, request):
        """Extract content from a URL and create a document."""
        serializer = ExtractFromURLSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message='Invalid request data',
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        url = serializer.validated_data['url']
        title = serializer.validated_data.get('title', '').strip()
        
        try:
            # Extract content from URL
            text, extracted_title = extract_content_from_url(url)
            
            if not text:
                return error_response('Could not extract content from URL. The URL may be inaccessible or contain no text content.', status_code=status.HTTP_400_BAD_REQUEST)
            
            # Use extracted title if provided and title is empty
            if not title:
                title = extracted_title or url
            
            # Create document
            document = Document.objects.create(
                title=title,
                file_url=url,
                file_type='url',
                uploaded_by=request.user,
                state='uploaded'
            )
            
            # Process and chunk the document
            processed_chunks = process_document(
                file_url=url,
                file_type='url',
                document_id=str(document.id),
                title=title,
                save_to_db=True
            )
            
            if not processed_chunks:
                return error_response('Document created but no chunks were generated', status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            return success_response({
                'document_id': str(document.id),
                'title': document.title,
                'chunks_created': len(processed_chunks),
                'message': f'Successfully extracted content from URL. {len(processed_chunks)} chunks created.'
            }, status_code=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error extracting content from URL {url}: {str(e)}", exc_info=True)
            return error_response(f'Error extracting content from URL: {str(e)}', status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @extend_schema(
        summary="Search documents using RAG",
        description="Search documents using vector similarity search (RAG). Returns relevant document chunks based on query.",
        request={
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Search query'},
                'top_k': {'type': 'integer', 'description': 'Number of results (default: 5)'},
                'document_id': {'type': 'string', 'description': 'Optional: Filter by specific document ID'}
            },
            'required': ['query']
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'query': {'type': 'string'},
                    'results': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'text': {'type': 'string'},
                                'url': {'type': 'string'},
                                'score': {'type': 'number'},
                                'document_id': {'type': 'string'},
                                'document_title': {'type': 'string'}
                            }
                        }
                    }
                }
            }
        },
        tags=['Knowledgebase'],
    )
    @action(detail=False, methods=['post'], url_path='search')
    def search(self, request):
        """Search documents using RAG (vector similarity search)."""
        query = request.data.get('query', '').strip()
        top_k = request.data.get('top_k', 5)
        document_id = request.data.get('document_id', None)
        
        if not query:
            return Response({
                'success': False,
                'error': 'Query is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Perform RAG search
        result = search_documents(query=query, top_k=top_k, document_id=document_id)
        
        if result['success']:
            return Response(result, status=status.HTTP_200_OK)
        else:
            return Response(result, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    summary="Get knowledgebase statistics",
    description="Retrieve statistics about the knowledgebase including total documents, active documents, documents by type, and vectorized documents.",
    responses={
        200: {
            'type': 'object',
            'properties': {
                'total_documents': {'type': 'integer'},
                'active_documents': {'type': 'integer'},
                'by_type': {'type': 'object'},
                'vectorized': {'type': 'integer'},
            }
        }
    },
    tags=['Knowledgebase'],
)
class KnowledgebaseStatsView(views.APIView):
    """
    View for knowledgebase statistics.
    
    Returns aggregated statistics about documents in the knowledgebase.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = Document.objects.all()
        if not request.user.is_superuser:
            queryset = queryset.filter(uploaded_by=request.user)
        
        stats = {
            'total_documents': queryset.count(),
            'active_documents': queryset.filter(is_active=True).count(),
            'by_type': {},
            'vectorized': queryset.filter(is_vectorized=True).count(),
        }
        
        for file_type, _ in Document.FILE_TYPE_CHOICES:
            stats['by_type'][file_type] = queryset.filter(file_type=file_type).count()
        
        return Response(stats)


@extend_schema(
    summary="Extract structured text from uploaded PDF",
    description=(
        "Upload a PDF file and extract structured content including page numbers, "
        "headings, paragraphs, and tables. The endpoint uses LLM to convert the content "
        "into Q&A format (default) suitable for RAG pipeline, with labeled question-answer "
        "pairs covering all information in the PDF. Alternatively, can output structured "
        "document format. The endpoint generates a structured `.txt` file with the same base "
        "name and saves it to `docs/extracted-docs/`. The response returns the relative path "
        "of the generated file."
    ),
    request={
        'multipart/form-data': {
            'type': 'object',
            'properties': {
                'file': {
                    'type': 'string',
                    'format': 'binary',
                    'description': 'PDF file to upload and extract structured text from'
                },
                'use_llm': {
                    'type': 'boolean',
                    'description': 'Whether to use LLM for structuring (default: true). Set to false to use basic formatting only.'
                },
                'qa_format': {
                    'type': 'boolean',
                    'description': 'Whether to convert to Q&A format for RAG pipeline (default: true). Set to false for structured document format.'
                },
                'filename': {
                    'type': 'string',
                    'description': 'User-provided filename for metadata (optional). If not provided, uses uploaded file name.'
                },
                'reference_url': {
                    'type': 'string',
                    'description': 'User-provided reference URL for metadata (optional). If not provided, uses "N/A".'
                }
            },
            'required': ['file']
        }
    },
    responses={
        200: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "filename": {"type": "string"},
                "output_path": {"type": "string", "description": "Main output path (processed if LLM used, otherwise raw)"},
                "raw_path": {"type": "string", "description": "Path to raw extracted text file with proper formatting (includes tables)"},
                "processed_path": {"type": "string", "description": "Path to LLM-processed Q&A format file (if LLM enabled)"},
                "message": {"type": "string"},
            },
        },
        400: {"description": "Invalid input or file format"},
        500: {"description": "Processing error"},
    },
    tags=["Documents"],
)
class PDFExtractView(views.APIView):
    """
    API endpoint to extract structured content from an uploaded PDF file
    and write a `.txt` file into `docs/extracted-docs/` with the same base name.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check if file was uploaded
        if 'file' not in request.FILES:
            return error_response(
                "No file provided. Please upload a PDF file using the 'file' field.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        
        uploaded_file = request.FILES['file']
        
        # Validate file is PDF
        if not uploaded_file.name.lower().endswith('.pdf'):
            return error_response(
                "Invalid file type. Only PDF files are supported.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        
        # Validate file size (optional: limit to 50MB)
        max_size = 50 * 1024 * 1024  # 50MB
        if uploaded_file.size > max_size:
            return error_response(
                f"File too large. Maximum size is {max_size / (1024*1024):.0f}MB.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        
        # Check if LLM structuring should be used (default: True)
        use_llm = request.data.get('use_llm', 'true').lower() in ('true', '1', 'yes')
        # Check if Q&A format should be used (default: True for RAG pipeline)
        qa_format = request.data.get('qa_format', 'true').lower() in ('true', '1', 'yes')
        # Get user-provided filename and reference_url
        user_filename = request.data.get('filename', '').strip() or None
        reference_url = request.data.get('reference_url', '').strip() or None
        
        try:
            from knowledgebase.services.pdf_extractor import process_uploaded_pdf
            result_paths = process_uploaded_pdf(uploaded_file, use_llm=use_llm, qa_format=qa_format, user_filename=user_filename, reference_url=reference_url, save_raw=True)
        except ValueError as e:
            return error_response(str(e), status_code=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error extracting PDF '{uploaded_file.name}': {e}", exc_info=True)
            return error_response(
                f"Unexpected error while processing PDF: {e}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Return paths relative to project root for convenience
        base_dir = Path(getattr(settings, "BASE_DIR", "."))
        
        response_data = {
            "filename": uploaded_file.name,
            "output_path": str(Path(result_paths["output_path"]).relative_to(base_dir)),
        }
        
        # Include raw and processed paths if available
        if "raw_path" in result_paths:
            response_data["raw_path"] = str(Path(result_paths["raw_path"]).relative_to(base_dir))
        if "processed_path" in result_paths:
            response_data["processed_path"] = str(Path(result_paths["processed_path"]).relative_to(base_dir))

        return success_response(
            response_data,
            message="PDF extracted successfully. Raw extracted file and processed Q&A file generated.",
        )
