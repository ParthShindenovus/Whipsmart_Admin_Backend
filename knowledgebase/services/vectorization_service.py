"""
Main service for vectorizing documents and uploading to Pinecone.
Properly stores document_id in metadata for easy deletion.
"""
import logging
from typing import List, Dict, Any
from django.conf import settings
from .pinecone_service import (
    get_pinecone_index, 
    upsert_vectors, 
    delete_vectors_by_ids,
    delete_vectors_by_document_id,
    query_vectors
)
from .embedding_service import embed, embed_batch
from .document_processor import process_document

logger = logging.getLogger(__name__)


def vectorize_document(document, use_db_chunks: bool = True) -> Dict[str, Any]:
    """
    Vectorize a document and upload to Pinecone.
    Uses chunks from database if available, otherwise processes document first.
    Updates document state throughout the process.
    
    Args:
        document: Document model instance
        use_db_chunks: Whether to use chunks from database (default: True)
        
    Returns:
        Dictionary with status and details
    """
    from django.utils import timezone
    from knowledgebase.models import DocumentChunk
    
    try:
        # Check if document is in valid state for vectorization
        if document.state == 'live':
            return {
                'success': False,
                'error': 'Document is already live in vector database'
            }
        
        # Get Pinecone index
        index = get_pinecone_index()
        if not index:
            return {
                'success': False,
                'error': 'Pinecone index not available. Check configuration.'
            }
        
        # Update state to processing
        document.state = 'processing'
        document.vector_status = 'embedding'
        document.save(update_fields=['state', 'vector_status'])
        
        # Get chunks from database or process document
        if use_db_chunks:
            chunks = DocumentChunk.objects.filter(document=document).order_by('chunk_index')
            if chunks.exists():
                processed_chunks = []
                for chunk in chunks:
                    # Include question in metadata if available (for Q&A chunks)
                    chunk_metadata = chunk.metadata.copy() if chunk.metadata else {}
                    if chunk.question:
                        chunk_metadata['question'] = chunk.question
                    # Add text to metadata for Pinecone storage
                    chunk_metadata['text'] = chunk.text
                    
                    processed_chunks.append((
                        chunk.text,
                        chunk.chunk_id,
                        chunk_metadata
                    ))
            else:
                # No chunks in DB, process document first
                if not document.file_url:
                    document.state = 'chunked'  # Revert state
                    document.vector_status = 'failed'
                    document.save(update_fields=['state', 'vector_status'])
                    return {
                        'success': False,
                        'error': 'Document file URL not found and no chunks in database'
                    }
                
                # Process and save chunks to DB
                processed_chunks = process_document(
                    file_url=document.file_url,
                    file_type=document.file_type,
                    document_id=str(document.id),
                    title=document.title,
                    save_to_db=True
                )
        else:
            # Process document without saving to DB (legacy mode)
            if not document.file_url:
                document.state = 'chunked'  # Revert state
                document.vector_status = 'failed'
                document.save(update_fields=['state', 'vector_status'])
                return {
                    'success': False,
                    'error': 'Document file URL not found'
                }
            
            processed_chunks = process_document(
                file_url=document.file_url,
                file_type=document.file_type,
                document_id=str(document.id),
                title=document.title,
                save_to_db=False
            )
        
        if not processed_chunks:
            document.state = 'chunked'  # Revert state
            document.vector_status = 'failed'
            document.save(update_fields=['state', 'vector_status'])
            return {
                'success': False,
                'error': 'No chunks available for vectorization'
            }
        
        # Update status to embedding
        document.vector_status = 'embedding'
        document.save(update_fields=['vector_status'])
        
        # Generate embeddings
        vectors_to_upsert = []
        chunk_texts = [chunk[0] for chunk in processed_chunks]
        
        try:
            # Generate embeddings in batch (using Azure OpenAI like reference)
            embeddings = embed_batch(chunk_texts, batch_size=100)
            
            # Prepare vectors for Pinecone with document_id in metadata
            for (chunk_text, chunk_id, metadata), embedding in zip(processed_chunks, embeddings):
                # Ensure text is in metadata (for DB chunks, it might not be there)
                if 'text' not in metadata or metadata.get('text') != chunk_text:
                    metadata['text'] = chunk_text
                
                vector_data = {
                    "id": chunk_id,
                    "values": embedding,
                    "metadata": metadata  # Contains document_id, text, and other metadata
                }
                vectors_to_upsert.append(vector_data)
        
        except Exception as e:
            logger.error(f"Error generating embeddings: {str(e)}")
            document.state = 'chunked'  # Revert state
            document.vector_status = 'failed'
            document.save(update_fields=['state', 'vector_status'])
            return {
                'success': False,
                'error': f'Error generating embeddings: {str(e)}'
            }
        
        # Update status to uploading
        document.vector_status = 'uploading'
        document.save(update_fields=['vector_status'])
        
        # Upload to Pinecone
        success = upsert_vectors(index, vectors_to_upsert, batch_size=50)
        
        if success:
            # Store all vector IDs and update chunk records
            vector_ids = []
            for idx, (chunk_text, chunk_id, metadata) in enumerate(processed_chunks):
                vector_ids.append(chunk_id)
                
                # Update chunk record if using DB chunks
                if use_db_chunks:
                    try:
                        chunk = DocumentChunk.objects.get(document=document, chunk_id=chunk_id)
                        chunk.is_vectorized = True
                        chunk.vector_id = chunk_id
                        chunk.vectorized_at = timezone.now()
                        chunk.save(update_fields=['is_vectorized', 'vector_id', 'vectorized_at'])
                    except DocumentChunk.DoesNotExist:
                        logger.warning(f"Chunk {chunk_id} not found in database")
            
            # Update document status
            document.vector_id = ','.join(vector_ids)  # Store all IDs
            document.is_vectorized = True
            document.vectorized_at = timezone.now()
            document.state = 'live'
            document.vector_status = 'completed'
            document.save(update_fields=['vector_id', 'is_vectorized', 'vectorized_at', 'state', 'vector_status'])
            
            logger.info(f"Successfully vectorized document {document.id} with {len(vector_ids)} chunks")
            
            return {
                'success': True,
                'chunks_created': len(processed_chunks),
                'vectors_uploaded': len(vectors_to_upsert),
                'vector_ids': vector_ids,
                'document_id': str(document.id)
            }
        else:
            document.state = 'chunked'  # Revert state
            document.vector_status = 'failed'
            document.save(update_fields=['state', 'vector_status'])
            return {
                'success': False,
                'error': 'Failed to upload vectors to Pinecone'
            }
    
    except Exception as e:
        logger.error(f"Error vectorizing document {document.id}: {str(e)}")
        document.state = 'chunked'  # Revert state on error
        document.vector_status = 'failed'
        document.save(update_fields=['state', 'vector_status'])
        return {
            'success': False,
            'error': str(e)
        }


def delete_document_vectors(document) -> bool:
    """
    Delete all vectors associated with a document from Pinecone.
    Uses document_id stored in metadata for efficient deletion.
    Updates document state to 'removed_from_vectordb'.
    
    Args:
        document: Document model instance
        
    Returns:
        True if successful, False otherwise
    """
    from knowledgebase.models import DocumentChunk
    
    try:
        # Check if document is live
        if document.state != 'live':
            logger.warning(f"Document {document.id} is not live, cannot remove from vector DB")
            return False
        
        # Get Pinecone index
        index = get_pinecone_index()
        if not index:
            logger.warning("Pinecone index not available for deletion")
            return False
        
        document_id = str(document.id)
        
        # Method 1: Delete by document_id pattern (more efficient)
        success = delete_vectors_by_document_id(index, document_id)
        
        # Method 2: Fallback - delete by stored vector IDs
        if not success and document.vector_id:
            vector_ids = document.vector_id.split(',')
            success = delete_vectors_by_ids(index, vector_ids)
        
        if success:
            # Update chunk records
            DocumentChunk.objects.filter(document=document).update(
                is_vectorized=False,
                vector_id=None,
                vectorized_at=None
            )
            
            # Update document state
            document.vector_id = None
            document.is_vectorized = False
            document.vectorized_at = None
            document.state = 'removed_from_vectordb'
            document.vector_status = 'not_started'
            document.save(update_fields=['vector_id', 'is_vectorized', 'vectorized_at', 'state', 'vector_status'])
            
            logger.info(f"Deleted vectors for document {document.id}")
            return True
        else:
            logger.warning(f"Failed to delete vectors for document {document.id}")
            return False
    
    except Exception as e:
        logger.error(f"Error deleting vectors for document {document.id}: {str(e)}")
        return False


def search_documents(query: str, top_k: int = 3, document_id: str = None) -> Dict[str, Any]:
    """
    Search documents using RAG (Retrieval Augmented Generation).
    Matches reference implementation from rag_tool.py
    
    Args:
        query: Search query text
        top_k: Number of results to return
        document_id: Optional filter by specific document
        
    Returns:
        Dictionary with search results
    """
    try:
        # Generate query embedding
        query_vector = embed(query)
        
        # Get Pinecone index
        index = get_pinecone_index()
        if not index:
            return {
                'success': False,
                'error': 'Pinecone index not available',
                'results': []
            }
        
        # Query Pinecone
        results = query_vectors(
            index=index,
            query_vector=query_vector,
            top_k=top_k,
            document_id=document_id,
            include_metadata=True
        )
        
        if not results:
            return {
                'success': True,
                'query': query,
                'results': []
            }
        
        # Format results (like reference rag_tool.py)
        docs = []
        for match in results.matches:
            metadata = match.metadata or {}
            doc = {
                "text": metadata.get("text", "")[:2000],  # Limit text length
                "url": metadata.get("url") or metadata.get("source", ""),
                "score": float(match.score),
                "chunk_index": metadata.get("chunk_index", 0),
                "document_id": metadata.get("document_id", ""),
                "document_title": metadata.get("document_title", ""),
                "file_name": metadata.get("file_name", "")
            }
            docs.append(doc)
        
        logger.info(f"RAG search found {len(docs)} documents for query: {query}")
        
        return {
            'success': True,
            'query': query,
            'results': docs
        }
    
    except Exception as e:
        logger.error(f"Error in RAG search: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'query': query,
            'results': []
        }
