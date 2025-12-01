"""
Document processing service for chunking and extracting text from various file types.
Supports local media folder and cloud storage (S3/Azure Blob ready).
"""
import os
from pathlib import Path
from typing import List, Tuple
import PyPDF2
from docx import Document as DocxDocument
from django.conf import settings
from django.core.files.storage import default_storage
import logging

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """
    Simple chunker by characters with overlap.
    Matches reference implementation from upload_to_pinecone.py
    For production, consider using token-aware chunking (tiktoken).
    
    Args:
        text: Text to chunk
        chunk_size: Size of each chunk in characters
        overlap: Number of characters to overlap between chunks
        
    Returns:
        List of text chunks
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
    
    # Check if it's a local file URL (starts with http://localhost or http://127.0.0.1 or relative)
    if parsed_url.scheme in ('http', 'https'):
        # Check if it's a local development URL
        if parsed_url.netloc in ('localhost', '127.0.0.1', '') or 'localhost' in parsed_url.netloc:
            # Extract path from URL (remove MEDIA_URL prefix)
            url_path = parsed_url.path
            if url_path.startswith(settings.MEDIA_URL):
                url_path = url_path[len(settings.MEDIA_URL):]
            # Build local file path
            return Path(settings.MEDIA_ROOT) / url_path.lstrip('/')
        else:
            # Remote URL - download to temp location
            import tempfile
            import requests
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(parsed_url.path).suffix)
            temp_path = Path(temp_file.name)
            
            # Download from URL
            response = requests.get(file_url, stream=True)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_file.close()
            return temp_path
    else:
        # Local file path (file:// or relative path)
        if parsed_url.scheme == 'file':
            return Path(parsed_url.path)
        else:
            # Assume it's a relative path in MEDIA_ROOT
            return Path(settings.MEDIA_ROOT) / file_url.lstrip('/')


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
        file_url: URL to the file (local media URL or cloud storage URL)
        file_type: Type of file
        document_id: UUID of the document (stored in metadata)
        title: Document title
        save_to_db: Whether to save chunks to database (default: True)
        
    Returns:
        List of tuples: (chunk_text, chunk_id, metadata)
    """
    from urllib.parse import urlparse
    from knowledgebase.models import Document, DocumentChunk
    from django.utils import timezone
    
    # Get file path (handles both local and cloud storage)
    file_path = get_file_path_from_url(file_url)
    parsed_url = urlparse(file_url)
    is_temp_file = parsed_url.scheme in ('http', 'https') and parsed_url.netloc not in ('localhost', '127.0.0.1', '') and 'localhost' not in parsed_url.netloc
    
    try:
        # Extract text
        text = extract_text_from_file(file_path, file_type)
        
        if not text:
            logger.warning(f"No text extracted from {file_url}")
            return []
        
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
            
            # Save chunk to database if requested
            if save_to_db and document:
                DocumentChunk.objects.update_or_create(
                    document=document,
                    chunk_id=chunk_id,
                    defaults={
                        'chunk_index': idx,
                        'text': chunk,
                        'text_length': len(chunk),
                        'metadata': metadata,
                    }
                )
        
        # Update document state and chunk count
        if save_to_db and document:
            document.chunk_count = len(chunks)
            document.state = 'chunked'
            document.save(update_fields=['chunk_count', 'state'])
            logger.info(f"Saved {len(chunks)} chunks to database for document {document_id}")
        
        return processed_chunks
    
    finally:
        # Clean up temp file if downloaded from remote URL
        if is_temp_file and file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"Error deleting temp file {file_path}: {str(e)}")
