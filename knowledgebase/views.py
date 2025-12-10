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
        description="Upload a new document (PDF, TXT, DOCX, HTML) using form-data. The file will be saved to the media folder and the URL will be stored in the database. Title and file_type are automatically extracted from the uploaded file (title from filename, file_type from extension). Requires authentication.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Document file to upload (PDF, TXT, DOCX, HTML). Title and file_type are auto-detected from the file.'
                    },
                    'title': {
                        'type': 'string',
                        'description': 'Document title (optional, defaults to filename without extension)'
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
        
        # Extract file name and extension
        from pathlib import Path
        from datetime import datetime
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
        
        # Generate file path in media folder
        now = datetime.now()
        file_path = f'documents/{now.year}/{now.month:02d}/{now.day:02d}/{file_name}'
        
        # Save file to media folder
        file_name_saved = default_storage.save(file_path, uploaded_file)
        
        # Build file URL
        if settings.DEBUG:
            # In development, use request to build absolute URL
            file_url = self.request.build_absolute_uri(settings.MEDIA_URL + file_name_saved)
        else:
            # In production, use MEDIA_URL setting
            file_url = f"{settings.MEDIA_URL}{file_name_saved}"
        
        # Save document with file_url, title, file_type, and state
        serializer.save(
            uploaded_by=self.request.user,
            file_url=file_url,
            title=title,
            file_type=file_type,
            state='uploaded'
        )
    
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
        """Chunk a document and store chunks in database."""
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
            
            processed_chunks = process_document(
                file_url=document.file_url,
                file_type=document.file_type,
                document_id=str(document.id),
                title=document.title,
                save_to_db=True
            )
            
            if processed_chunks:
                logger.info(f"Successfully created {len(processed_chunks)} chunks for document {document.id}")
                return success_response(
                    {
                        'chunks_created': len(processed_chunks),
                        'document_id': str(document.id),
                        'document_title': document.title,
                        'state': document.state
                    },
                    message=f'Document chunked successfully. {len(processed_chunks)} chunks created.'
                )
            else:
                logger.warning(f"No chunks created for document {document.id} - no text extracted")
                return error_response(
                    'No text extracted from document. The file may be empty, corrupted, or in an unsupported format.',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
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
        
        # Delete file from storage
        if instance.file_url:
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(instance.file_url)
                if parsed_url.netloc in ('localhost', '127.0.0.1', '') or 'localhost' in parsed_url.netloc:
                    # Local file
                    url_path = parsed_url.path
                    if url_path.startswith(settings.MEDIA_URL):
                        url_path = url_path[len(settings.MEDIA_URL):]
                    file_path = Path(settings.MEDIA_ROOT) / url_path.lstrip('/')
                    if file_path.exists():
                        file_path.unlink()
            except Exception as e:
                logger.warning(f"Error deleting file {instance.file_url}: {str(e)}")
        
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
