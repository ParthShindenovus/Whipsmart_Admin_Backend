"""
Streaming Document Upload API with Server-Sent Events (SSE)
Provides real-time progress updates during document processing.
"""
import json
import logging
import threading
import time
from rest_framework import views, status
from rest_framework.permissions import IsAuthenticated
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from pathlib import Path
from datetime import datetime

from core.utils import success_response, error_response
from .models import Document
from .serializers import DocumentSerializer

logger = logging.getLogger(__name__)


def send_sse_event(event_type: str, data: dict):
    """Format data as SSE event."""
    json_data = json.dumps(data)
    return f"event: {event_type}\ndata: {json_data}\n\n"


def process_document_with_progress(document_id: str, file_path: Path, file_name: str, 
                                   file_type: str, title: str, user, request, progress_callback):
    """
    Process document with progress callbacks.
    
    Args:
        document_id: Document UUID
        file_path: Path to uploaded file
        file_name: Original filename
        file_type: File type (pdf, txt, docx, html)
        title: Document title
        user: User who uploaded
        request: Django request object (for building URLs)
        progress_callback: Function to call with progress updates (percentage, message, status)
    """
    try:
        from knowledgebase.models import Document
        from knowledgebase.services.pdf_extractor import process_uploaded_pdf
        from knowledgebase.services.document_processor import process_document
        
        document = Document.objects.get(id=document_id)
        
        # Step 1: File Uploaded (10%) - Already sent before thread started
        # progress_callback(10, "File uploaded successfully", "uploaded")
        
        # Step 2: PDF Processing (if PDF)
        if file_type == 'pdf':
            # 2a: Extracting (20%)
            progress_callback(20, "Extracting text from PDF", "extracting")
            document.processing_status = 'extracting'
            document.processing_error = None
            document.save(update_fields=['processing_status', 'processing_error'])
            
            # 2b: Structuring with LLM (40%)
            progress_callback(40, "Structuring content with LLM", "structuring")
            document.processing_status = 'structuring'
            document.save(update_fields=['processing_status'])
            
            # Process PDF
            class FileWrapper:
                def __init__(self, file_path, name):
                    self.file_path = Path(file_path) if not isinstance(file_path, Path) else file_path
                    self.name = name
                    self.size = self.file_path.stat().st_size if self.file_path.exists() else 0
                
                def read(self, size=-1):
                    with open(self.file_path, 'rb') as f:
                        return f.read(size)
                
                def chunks(self, chunk_size=8192):
                    with open(self.file_path, 'rb') as f:
                        while True:
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            yield chunk
            
            wrapped_file = FileWrapper(file_path, file_name)
            
            # Note: process_uploaded_pdf doesn't support progress callbacks yet
            # We'll add progress updates before and after the call
            # The actual processing happens inside, so we can't get granular updates
            # TODO: Add progress callback support to process_uploaded_pdf
            
            output_paths = process_uploaded_pdf(
                uploaded_file=wrapped_file,
                use_llm=True,
                qa_format=True,
                user_filename=None,
                reference_url=None,
                save_raw=False
            )
            
            # Send update after PDF processing completes
            progress_callback(49, "PDF processing completed", "completed")
            time.sleep(0.1)
            
            # Build URL for structured Q&A text file
            processed_path = output_paths.get('processed_path')
            
            if processed_path and processed_path.exists():
                # Convert absolute path to relative path from BASE_DIR
                base_dir = Path(settings.BASE_DIR)
                rel_processed_path = processed_path.relative_to(base_dir)
                
                # Build URL based on environment
                if settings.DEBUG:
                    protocol = 'https' if request.is_secure() else 'http'
                    host = request.get_host() if hasattr(request, 'get_host') else 'localhost:8000'
                    structured_text_qa_url = f"{protocol}://{host}/{rel_processed_path.as_posix()}"
                else:
                    structured_text_qa_url = f"/{rel_processed_path.as_posix()}"
                
                document.structured_text_qa_url = structured_text_qa_url
                document.processing_status = 'completed'
                document.processing_error = None
                document.save(update_fields=['structured_text_qa_url', 'processing_status', 'processing_error'])
                progress_callback(50, "PDF processing completed", "completed")
                time.sleep(0.1)  # Delay to ensure event is sent and flushed
            else:
                error_msg = "Failed to generate structured Q&A file"
                logger.error(f"{error_msg} for document {document_id}. Output paths: {output_paths}")
                raise Exception(error_msg)
        else:
            # Non-PDF files skip PDF processing
            progress_callback(50, "File ready for processing", "completed")
        
        # Step 3: Chunking (60-70%)
        progress_callback(60, "Starting document chunking", "chunking")
        time.sleep(0.1)  # Delay to ensure event is sent
        document.vector_status = 'chunking'
        document.save(update_fields=['vector_status'])
        
        # Create a wrapper progress callback that updates percentage
        def chunking_progress_callback(message: str):
            """Progress callback for chunking steps."""
            # Map messages to percentages (60-70%)
            if "Resolving" in message or "Extracting text" in message:
                progress_callback(62, message, "chunking")
            elif "Extracted" in message and "characters" in message:
                progress_callback(64, message, "chunking")
            elif "Splitting" in message or "Split text" in message:
                progress_callback(66, message, "chunking")
            elif "Preparing" in message:
                progress_callback(68, message, "chunking")
            elif "Saving" in message and "chunks" in message:
                progress_callback(69, message, "chunking")
            elif "Saved" in message:
                progress_callback(70, message, "chunking")
            else:
                progress_callback(65, message, "chunking")
            time.sleep(0.05)  # Small delay to ensure event is sent
        
        processed_chunks = process_document(
            file_url=document.file_url,
            file_type=file_type,
            document_id=str(document.id),
            title=title,
            save_to_db=True,
            progress_callback=chunking_progress_callback
        )
        
        if not processed_chunks:
            raise Exception("Failed to chunk document")
        
        document.state = 'chunked'
        document.chunk_count = len(processed_chunks)
        document.save(update_fields=['state', 'chunk_count'])
        progress_callback(70, f"Document chunked into {len(processed_chunks)} chunks", "chunked")
        time.sleep(0.1)  # Delay to ensure event is sent and flushed
        
        # Step 4: Mark as live (vectorization will be handled by separate API)
        document.state = 'live'
        document.vector_status = 'pending'  # Vectorization will be done separately
        document.save(update_fields=['state', 'vector_status'])
        progress_callback(100, "Document uploaded and chunked successfully. Vectorization will be processed separately.", "live")
            
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {str(e)}", exc_info=True)
        try:
            document = Document.objects.get(id=document_id)
            document.processing_status = 'failed'
            document.vector_status = 'failed'
            document.processing_error = str(e)
            document.save(update_fields=['processing_status', 'vector_status', 'processing_error'])
        except:
            pass
        progress_callback(-1, f"Error: {str(e)}", "failed")


class StreamingDocumentUploadView(views.APIView):
    """
    Streaming document upload with Server-Sent Events (SSE).
    Provides real-time progress updates during document processing.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Upload Document with Streaming Progress",
        description="Upload a document and receive real-time progress updates via Server-Sent Events (SSE). "
                    "Progress is sent as percentage (0-100) with status messages. "
                    "Connect with EventSource in frontend to receive updates.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Document file to upload'
                    },
                    'title': {
                        'type': 'string',
                        'description': 'Optional document title'
                    }
                },
                'required': ['file']
            }
        },
        tags=['Documents']
    )
    def post(self, request):
        """Upload document with streaming progress."""
        try:
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return error_response(
                    'file is required',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Check file size
            max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 100 * 1024 * 1024)
            if uploaded_file.size > max_size:
                return error_response(
                    f'File size exceeds maximum allowed size of {max_size / (1024 * 1024):.1f}MB',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Extract file info
            from pathlib import Path
            file_path_obj = Path(uploaded_file.name)
            file_name = uploaded_file.name
            file_stem = file_path_obj.stem
            file_extension = file_path_obj.suffix.lower()
            
            # Detect file type
            file_type_map = {
                '.pdf': 'pdf',
                '.txt': 'txt',
                '.docx': 'docx',
                '.html': 'html'
            }
            
            file_type = file_type_map.get(file_extension)
            if not file_type:
                return error_response(
                    f'Unsupported file type. Supported extensions: {", ".join(file_type_map.keys())}',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Get title
            title = request.data.get('title', file_stem)
            
            # Generate file path
            env_folder = 'development' if settings.DEBUG else 'production'
            now = datetime.now()
            file_path = f'{env_folder}/documents/{now.year}/{now.month:02d}/{now.day:02d}/{file_name}'
            
            # Save file
            file_name_saved = default_storage.save(file_path, uploaded_file)
            
            # Build file URL
            if settings.DEBUG:
                file_url = request.build_absolute_uri(settings.MEDIA_URL + file_name_saved)
            else:
                file_url = f"{settings.MEDIA_URL}{file_name_saved}"
            
            # Create document record
            document = Document.objects.create(
                uploaded_by=request.user,
                file_url=file_url,
                title=title,
                file_type=file_type,
                state='uploaded',
                processing_status='pending' if file_type == 'pdf' else 'completed',
                vector_status='not_started'
            )
            
            # Get full file path
            file_path_full = Path(settings.MEDIA_ROOT) / file_name_saved
            
            # Create progress tracking with thread-safe queue
            import queue
            progress_queue = queue.Queue()
            processing_complete = threading.Event()
            
            def progress_callback(percentage: int, message: str, status: str):
                """Callback to send progress updates."""
                # Use put_nowait to avoid blocking and ensure immediate queuing
                try:
                    progress_queue.put_nowait({
                        'percentage': percentage,
                        'message': message,
                        'status': status,
                        'document_id': str(document.id)
                    })
                except queue.Full:
                    # Queue is full, use blocking put as fallback
                    progress_queue.put({
                        'percentage': percentage,
                        'message': message,
                        'status': status,
                        'document_id': str(document.id)
                    })
                if percentage == 100 or percentage == -1:
                    processing_complete.set()
            
            # Create processing thread but DON'T start it yet
            # The generator will start it after initial events are yielded
            processing_thread = threading.Thread(
                target=process_document_with_progress,
                args=(str(document.id), file_path_full, file_name, file_type, title, request.user, request, progress_callback),
                daemon=True
            )
            # Thread will be started inside event_stream() after initial events are yielded
            # This ensures streaming starts immediately when API is hit are yielded
            
            # Stream progress updates - CRITICAL: Generator yields immediately
            def event_stream():
                """Generator for SSE events - yields immediately for real-time streaming."""
                # CRITICAL: Yield initial events IMMEDIATELY before starting thread
                yield send_sse_event('document_created', {
                    'document_id': str(document.id),
                    'title': title,
                    'file_type': file_type,
                    'message': 'Document created, starting processing...'
                })
                
                yield send_sse_event('progress', {
                    'percentage': 10,
                    'message': 'File uploaded successfully',
                    'status': 'uploaded',
                    'document_id': str(document.id)
                })
                
                # CRITICAL: Start processing thread AFTER initial events are yielded
                # This ensures events stream immediately when API is hit
                processing_thread.start()
                
                # Read from queue ONE item at a time and yield immediately
                last_percentage = 10
                last_heartbeat_time = time.time()
                heartbeat_interval = 2  # Send heartbeat every 2 seconds (more frequent updates)
                max_idle_time = 1800  # 30 minutes max idle (for very long processing like large PDFs)
                last_update_time = time.time()
                
                while True:
                    try:
                        # Wait for progress update with very short timeout for immediate streaming
                        update = progress_queue.get(timeout=0.05)  # Very short timeout for immediate streaming
                        last_percentage = update['percentage']
                        last_update_time = time.time()
                        last_heartbeat_time = time.time()  # Reset heartbeat timer
                        
                        if update['percentage'] == -1:
                            # Error occurred
                            event = send_sse_event('error', update)
                            yield event
                            # Force flush
                            import sys
                            sys.stdout.flush()
                            break
                        elif update['percentage'] == 100:
                            # Completed (uploaded and chunked)
                            event1 = send_sse_event('progress', update)
                            yield event1
                            # Force flush before next event
                            import sys
                            sys.stdout.flush()
                            
                            event2 = send_sse_event('complete', {
                                'document_id': str(document.id),
                                'message': 'Document uploaded and chunked successfully. Vectorization will be processed separately.',
                                'status': 'live',
                                'note': 'Vectorization will be handled by a separate API endpoint'
                            })
                            yield event2
                            # Force flush
                            sys.stdout.flush()
                            break
                        else:
                            event = send_sse_event('progress', update)
                            yield event
                            # Force flush immediately after each progress update
                            import sys
                            sys.stdout.flush()
                    
                    except queue.Empty:
                        # No update received
                        current_time = time.time()
                        
                        # Check if processing is complete
                        if processing_complete.is_set():
                            # Processing finished, check final status
                            if last_percentage < 100:
                                yield send_sse_event('error', {
                                    'message': 'Processing completed but final status unknown',
                                    'status': 'unknown'
                                })
                            break
                        
                        # Check if processing thread is still alive
                        if not processing_thread.is_alive():
                            # Thread died unexpectedly
                            if last_percentage < 100:
                                yield send_sse_event('error', {
                                    'message': 'Processing thread terminated unexpectedly',
                                    'status': 'failed'
                                })
                            break
                        
                        # Send heartbeat periodically (every 2 seconds) to keep connection alive
                        if current_time - last_heartbeat_time >= heartbeat_interval:
                            event = send_sse_event('heartbeat', {
                                'message': f'Processing... (Current progress: {last_percentage}%)',
                                'percentage': last_percentage
                            })
                            yield event
                            # Force flush immediately
                            import sys
                            sys.stdout.flush()
                            last_heartbeat_time = current_time
                            # Update last_update_time when sending heartbeat to prevent false timeouts
                            # This shows the connection is alive even if processing takes a while
                            last_update_time = current_time
                        
                        # Only timeout if thread is dead AND no updates for a very long time (30 minutes)
                        # Since we're checking thread.is_alive() above, this is just a safety net
                        if current_time - last_update_time > max_idle_time:
                            # Double-check thread is actually dead before timing out
                            if not processing_thread.is_alive() and not processing_complete.is_set():
                                yield send_sse_event('error', {
                                    'message': 'Processing timeout - no updates received for too long',
                                    'status': 'timeout'
                                })
                                break
                            # If thread is still alive, just reset the timer (processing is ongoing)
                            last_update_time = current_time
            
            # Return streaming response - generator yields immediately
            response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'  # Disable buffering in nginx
            response['Connection'] = 'keep-alive'
            # Ensure no buffering
            response['X-Content-Type-Options'] = 'nosniff'
            return response
            
        except Exception as e:
            logger.error(f"Error in StreamingDocumentUploadView: {str(e)}", exc_info=True)
            return error_response(
                f'An error occurred while uploading document: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

