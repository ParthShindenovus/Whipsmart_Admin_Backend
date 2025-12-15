"""
Document processing service for chunking and extracting text from various file types.
Supports local media folder and cloud storage (S3/Azure Blob ready).
"""
import os
from pathlib import Path
from typing import List, Tuple, Dict
import PyPDF2
from docx import Document as DocxDocument
from django.conf import settings
from django.core.files.storage import default_storage
import logging

logger = logging.getLogger(__name__)


def dynamic_chunking(text: str, max_chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Dynamic chunking using spaCy for sentence-aware chunking.
    Creates smaller, semantically coherent chunks that respect sentence boundaries.
    
    Args:
        text: Text to chunk
        max_chunk_size: Maximum size of each chunk in characters
        overlap: Number of characters to overlap between chunks (approximate)
        
    Returns:
        List of text chunks
    """
    try:
        import spacy
    except ImportError:
        logger.warning("spaCy not installed. Falling back to simple character-based chunking. Install with: python -m spacy download en_core_web_sm")
        return _simple_chunking(text, max_chunk_size, overlap)
    
    # Try to load spaCy model, fallback to simple chunking if not available
    try:
        nlp = spacy.load('en_core_web_sm')
    except OSError:
        logger.warning("spaCy model 'en_core_web_sm' not found. Falling back to simple chunking. Install with: python -m spacy download en_core_web_sm")
        return _simple_chunking(text, max_chunk_size, overlap)
    
    if not text or len(text.strip()) == 0:
        return []
    
    if len(text) <= max_chunk_size:
        return [text]
    
    doc = nlp(text)
    chunks = []
    current_chunk = []
    current_size = 0
    
    for sent in doc.sents:
        sent_text = sent.text.strip()
        sent_length = len(sent_text)
        
        # If a single sentence is larger than max_chunk_size, split it
        if sent_length > max_chunk_size:
            # Save current chunk if it has content
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_size = 0
            
            # Split the long sentence using simple chunking
            sentence_chunks = _simple_chunking(sent_text, max_chunk_size, overlap)
            chunks.extend(sentence_chunks)
            continue
        
        # Check if adding this sentence would exceed max_chunk_size
        if current_size + sent_length + 1 > max_chunk_size:  # +1 for space
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            
            # Start new chunk with overlap (include last sentence of previous chunk)
            if chunks and overlap > 0:
                # Get last chunk for overlap
                last_chunk = chunks[-1]
                overlap_text = last_chunk[-overlap:] if len(last_chunk) > overlap else last_chunk
                current_chunk = [overlap_text, sent_text]
                current_size = len(overlap_text) + sent_length + 1
            else:
                current_chunk = [sent_text]
                current_size = sent_length
        else:
            current_chunk.append(sent_text)
            current_size += sent_length + 1  # +1 for space
    
    # Add remaining chunk
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    # Clean up chunks (remove empty ones)
    chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
    
    return chunks if chunks else [text]


def _simple_chunking(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Simple character-based chunking fallback.
    Used when spaCy is not available.
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i:i + chunk_size]
        chunks.append(chunk)
        i += chunk_size - overlap
        if i >= len(text):
            break
    
    return chunks


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Wrapper for backward compatibility.
    Uses dynamic chunking with smaller default chunk size.
    
    Args:
        text: Text to chunk
        chunk_size: Maximum size of each chunk in characters (default: 500)
        overlap: Number of characters to overlap (default: 50)
        
    Returns:
        List of text chunks
    """
    return dynamic_chunking(text, max_chunk_size=chunk_size, overlap=overlap)


def get_file_path_from_url(file_url: str) -> Path:
    """
    Get file path from URL, supporting both local media folder and cloud storage.
    
    Args:
        file_url: URL to the file (can be local media URL or cloud storage URL)
        
    Returns:
        Path object to the file
    """
    from urllib.parse import urlparse
    
    parsed_url = urlparse(file_url)
    
    # Normalize MEDIA_URL to handle both with and without leading slash
    media_url_normalized = settings.MEDIA_URL.rstrip('/')
    if not media_url_normalized.startswith('/'):
        media_url_normalized = '/' + media_url_normalized
    
    # Check if it's a relative path starting with MEDIA_URL (e.g., media/documents/... or /media/documents/...)
    # Handle both "media/documents/..." and "/media/documents/..." formats
    file_url_normalized = file_url.lstrip('/')
    media_url_normalized_no_slash = media_url_normalized.lstrip('/')
    
    if not parsed_url.scheme and (file_url.startswith(settings.MEDIA_URL) or file_url.startswith(media_url_normalized) or file_url_normalized.startswith(media_url_normalized_no_slash)):
        # Remove MEDIA_URL prefix (handle both with and without leading slash)
        if file_url.startswith(settings.MEDIA_URL):
            relative_path = file_url[len(settings.MEDIA_URL):].lstrip('/')
        elif file_url.startswith(media_url_normalized):
            relative_path = file_url[len(media_url_normalized):].lstrip('/')
        else:
            relative_path = file_url_normalized[len(media_url_normalized_no_slash):].lstrip('/')
        
        file_path = Path(settings.MEDIA_ROOT) / relative_path
        logger.info(f"Resolved relative media URL '{file_url}' to '{file_path}'")
        return file_path
    
    # Check if it's a local file URL (starts with http://localhost or http://127.0.0.1)
    if parsed_url.scheme in ('http', 'https'):
        # Check if it's a local development URL
        if parsed_url.netloc in ('localhost', '127.0.0.1', '') or 'localhost' in parsed_url.netloc:
            # Extract path from URL (remove MEDIA_URL prefix if present)
            url_path = parsed_url.path
            # Handle both /media/... and media/... formats
            if url_path.startswith(media_url_normalized):
                url_path = url_path[len(media_url_normalized):].lstrip('/')
            elif url_path.startswith('/' + settings.MEDIA_URL):
                url_path = url_path[len('/' + settings.MEDIA_URL):].lstrip('/')
            elif url_path.startswith(settings.MEDIA_URL):
                url_path = url_path[len(settings.MEDIA_URL):].lstrip('/')
            
            # Build local file path
            file_path = Path(settings.MEDIA_ROOT) / url_path
            logger.info(f"Resolved localhost URL '{file_url}' to '{file_path}'")
            return file_path
        else:
            # Remote URL - download to temp location
            import tempfile
            import requests
            logger.info(f"Downloading remote file from '{file_url}'")
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(parsed_url.path).suffix)
            temp_path = Path(temp_file.name)
            
            # Download from URL
            response = requests.get(file_url, stream=True, timeout=30)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_file.close()
            logger.info(f"Downloaded remote file to '{temp_path}'")
            return temp_path
    else:
        # Local file path (file:// or relative path)
        if parsed_url.scheme == 'file':
            return Path(parsed_url.path)
        else:
            # Assume it's a relative path - try both as-is and relative to MEDIA_ROOT
            # First try as absolute path if it starts with /
            if file_url.startswith('/'):
                file_path = Path(file_url)
                if file_path.exists():
                    return file_path
            # Otherwise, assume it's relative to MEDIA_ROOT
            file_path = Path(settings.MEDIA_ROOT) / file_url.lstrip('/')
            logger.info(f"Resolved relative path '{file_url}' to '{file_path}'")
            return file_path


def extract_text_from_file(file_path: Path, file_type: str) -> str:
    """
    Extract text from various file types.
    Supports both local and cloud storage files.
    
    Args:
        file_path: Path to the file (local or temp from cloud)
        file_type: Type of file (pdf, txt, docx, html)
        
    Returns:
        Extracted text content
    """
    try:
        if file_type == 'txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read().strip()
        
        elif file_type == 'pdf':
            text = ""
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            return text.strip()
        
        elif file_type == 'docx':
            doc = DocxDocument(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text.strip()
        
        elif file_type == 'html':
            from bs4 import BeautifulSoup
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                return soup.get_text().strip()
        
        else:
            logger.warning(f"Unsupported file type: {file_type}")
            return ""
    
    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {str(e)}")
        raise


def process_document(file_url: str, file_type: str, document_id: str, title: str, save_to_db: bool = True) -> List[Tuple[str, str, dict]]:
    """
    Process a document: extract text, chunk it, and optionally store chunks in DB.
    Stores document_id in metadata for easy deletion.
    
    Args:
        file_url: URL to the file (local media URL or cloud storage URL) or web URL
        file_type: Type of file (pdf, txt, docx, html, url)
        document_id: UUID of the document (stored in metadata)
        title: Document title
        save_to_db: Whether to save chunks to database (default: True)
        
    Returns:
        List of tuples: (chunk_text, chunk_id, metadata)
    """
    from urllib.parse import urlparse
    from knowledgebase.models import Document, DocumentChunk
    from django.utils import timezone
    
    # Handle URL type documents differently
    if file_type == 'url':
        return process_url_document(file_url, document_id, title, save_to_db)
    
    # Get file path (handles both local and cloud storage)
    try:
        file_path = get_file_path_from_url(file_url)
        logger.info(f"Resolved file URL '{file_url}' to path '{file_path}'")
    except Exception as e:
        logger.error(f"Error resolving file path from URL '{file_url}': {str(e)}", exc_info=True)
        raise ValueError(f"Could not resolve file path from URL: {file_url}. Error: {str(e)}")
    
    # Check if file exists
    if not file_path.exists():
        error_msg = f"File not found at path: {file_path} (resolved from URL: {file_url})"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    
    parsed_url = urlparse(file_url)
    is_temp_file = parsed_url.scheme in ('http', 'https') and parsed_url.netloc not in ('localhost', '127.0.0.1', '') and 'localhost' not in parsed_url.netloc
    
    try:
        # Extract text
        logger.info(f"Extracting text from file '{file_path}' (type: {file_type})")
        text = extract_text_from_file(file_path, file_type)
        
        if not text or len(text.strip()) == 0:
            logger.warning(f"No text extracted from {file_url} (file_path: {file_path})")
            return []
        
        logger.info(f"Extracted {len(text)} characters from file '{file_path}'")
        
        # Chunk the text
        chunks = chunk_text(text)
        logger.info(f"Created {len(chunks)} chunks from {title}")
        
        # Extract file name from URL
        file_name = Path(parsed_url.path).name if parsed_url.path else Path(file_url).name
        
        # Get document instance if saving to DB
        document = None
        if save_to_db:
            try:
                document = Document.objects.get(id=document_id)
            except Document.DoesNotExist:
                logger.warning(f"Document {document_id} not found, skipping DB save")
                save_to_db = False
        
        # Prepare chunks with metadata (including document_id for easy deletion)
        processed_chunks = []
        chunk_objects = []
        
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{document_id}-chunk-{idx}"
            metadata = {
                "text": chunk[:2000],  # Limit metadata text length (Pinecone limit)
                "source": "whipsmart",
                "document_id": str(document_id),  # CRITICAL: Store document_id for easy deletion
                "document_title": title,
                "chunk_index": idx,
                "file_type": file_type,
                "file_name": file_name,
                "url": file_url  # File URL (local or cloud storage)
            }
            processed_chunks.append((chunk, chunk_id, metadata))
            
            # Prepare chunk objects for bulk insert
            if save_to_db and document:
                chunk_objects.append(
                    DocumentChunk(
                        document=document,
                        chunk_id=chunk_id,
                        chunk_index=idx,
                        text=chunk,
                        text_length=len(chunk),
                        metadata=metadata,
                    )
                )
        
        # Save chunks to database using bulk operations (much faster!)
        if save_to_db and document and chunk_objects:
            from django.db import transaction
            
            with transaction.atomic():
                # Delete existing chunks first (in case of re-chunking)
                DocumentChunk.objects.filter(document=document).delete()
                
                # Bulk create all chunks in a single query
                DocumentChunk.objects.bulk_create(chunk_objects, batch_size=500)
                
                # Update document state and chunk count
                document.chunk_count = len(chunks)
                document.state = 'chunked'
                document.save(update_fields=['chunk_count', 'state'])
                
            logger.info(f"Bulk saved {len(chunks)} chunks to database for document {document_id} (using bulk_create)")
        
        return processed_chunks
    
    finally:
        # Clean up temp file if downloaded from remote URL
        if is_temp_file and file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"Error deleting temp file {file_path}: {str(e)}")


def chunk_by_headings(structured_content: List[Dict], max_chunk_size: int = 1000) -> List[Dict]:
    """
    Chunk structured content by headings and topics.
    Each chunk represents a complete topic/section with its heading hierarchy.
    
    Args:
        structured_content: List of dicts with 'heading', 'level', 'main_heading', 'content' keys
        max_chunk_size: Maximum size of each chunk in characters
        
    Returns:
        List of dicts with 'heading', 'level', 'main_heading', 'content', 'chunk_text' keys
    """
    chunks = []
    
    for section in structured_content:
        heading = section.get('heading', '')
        main_heading = section.get('main_heading', '') or heading
        level = section.get('level', 0)
        content = section.get('content', '').strip()
        
        if not content or len(content) < 10:  # Skip very short or empty content
            continue
        
        # Create chunk text with heading prefix for better context
        if heading:
            section_text = f"{heading}\n\n{content}"
        else:
            section_text = content
        
        # If chunk is too large, split it further using sentence-based chunking
        if len(section_text) > max_chunk_size:
            # Split large sections into smaller chunks while preserving heading context
            sub_chunks = chunk_text(section_text, chunk_size=max_chunk_size, overlap=50)
            
            for idx, sub_chunk in enumerate(sub_chunks):
                # Preserve heading context in each sub-chunk
                if heading and idx > 0:
                    sub_chunk = f"{heading}\n\n{sub_chunk}"
                
                chunks.append({
                    'heading': heading,
                    'main_heading': main_heading,
                    'level': level,
                    'content': content if idx == 0 else '',  # Only full content for first chunk
                    'chunk_text': sub_chunk
                })
        else:
            chunks.append({
                'heading': heading,
                'main_heading': main_heading,
                'level': level,
                'content': content,
                'chunk_text': section_text
            })
    
    return chunks


def process_url_document(url: str, document_id: str, title: str, save_to_db: bool = True) -> List[Tuple[str, str, dict]]:
    """
    Process a URL document: extract content with structure, chunk by headings/topics, and optionally store chunks in DB.
    
    Args:
        url: URL to extract content from
        document_id: UUID of the document (stored in metadata)
        title: Document title
        save_to_db: Whether to save chunks to database (default: True)
        
    Returns:
        List of tuples: (chunk_text, chunk_id, metadata)
    """
    from knowledgebase.models import Document, DocumentChunk
    from knowledgebase.services.url_extractor import extract_content_with_structure
    
    try:
        # Extract structured content from URL (with headings and sections)
        structured_content, extracted_title = extract_content_with_structure(url)
        
        if not structured_content:
            logger.warning(f"No structured content extracted from URL: {url}")
            return []
        
        # Use extracted title if provided and title is empty/not provided
        if not title or title == url:
            title = extracted_title or url
        
        # Chunk by headings and topics
        heading_chunks = chunk_by_headings(structured_content, max_chunk_size=1000)
        logger.info(f"Created {len(heading_chunks)} topic-based chunks from URL: {url}")
        
        # Get document instance if saving to DB
        document = None
        if save_to_db:
            try:
                document = Document.objects.get(id=document_id)
            except Document.DoesNotExist:
                logger.warning(f"Document {document_id} not found, skipping DB save")
                save_to_db = False
        
        # Prepare chunks with metadata (including document_id for easy deletion)
        processed_chunks = []
        chunk_objects = []
        
        for idx, heading_chunk in enumerate(heading_chunks):
            chunk_id = f"{document_id}-chunk-{idx}"
            chunk_text = heading_chunk['chunk_text']
            heading = heading_chunk.get('heading')
            main_heading = heading_chunk.get('main_heading', heading)
            level = heading_chunk.get('level', 0)
            
            metadata = {
                "text": chunk_text[:2000],  # Limit metadata text length (Pinecone limit)
                "source": "whipsmart",
                "document_id": str(document_id),  # CRITICAL: Store document_id for easy deletion
                "document_title": title,
                "chunk_index": idx,
                "file_type": "url",
                "url": url,  # Store the original URL
                "heading": heading,  # Store full heading path for context
                "main_heading": main_heading,  # Store main heading for quick reference
                "heading_level": level  # Store heading level
            }
            processed_chunks.append((chunk_text, chunk_id, metadata))
            
            # Prepare chunk objects for bulk insert
            if save_to_db and document:
                chunk_objects.append(
                    DocumentChunk(
                        document=document,
                        chunk_id=chunk_id,
                        chunk_index=idx,
                        text=chunk_text,
                        text_length=len(chunk_text),
                        metadata=metadata,
                    )
                )
        
        # Save chunks to database using bulk operations (much faster!)
        if save_to_db and document and chunk_objects:
            from django.db import transaction
            
            with transaction.atomic():
                # Delete existing chunks first (in case of re-chunking)
                DocumentChunk.objects.filter(document=document).delete()
                
                # Bulk create all chunks in a single query
                DocumentChunk.objects.bulk_create(chunk_objects, batch_size=500)
                
                # Update document state and chunk count
                document.chunk_count = len(heading_chunks)
                document.state = 'chunked'
                document.save(update_fields=['chunk_count', 'state'])
                
            logger.info(f"Bulk saved {len(heading_chunks)} topic-based chunks to database for document {document_id} (using bulk_create)")
        
        return processed_chunks
    
    except Exception as e:
        logger.error(f"Error processing URL document {url}: {str(e)}", exc_info=True)
        raise
