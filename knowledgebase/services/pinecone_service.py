"""
Pinecone service for document vectorization and storage.
Matches reference implementation from app/services/pinecone_client.py
"""
import os
from typing import List, Dict, Any, Optional
from pinecone import Pinecone
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Initialize Pinecone client (like reference)
_pinecone_client = None
_pinecone_index = None


def _get_pinecone_client():
    """Initialize Pinecone client (singleton pattern like reference)"""
    global _pinecone_client
    
    if _pinecone_client is None:
        api_key = settings.PINECONE_API_KEY
        if not api_key:
            raise ValueError("PINECONE_API_KEY is required but not set in settings")
        
        _pinecone_client = Pinecone(api_key=api_key)
        logger.info("Initialized Pinecone client")
    
    return _pinecone_client


def get_pinecone_index():
    """
    Get or create Pinecone index.
    Matches reference implementation from app/services/pinecone_client.py
    
    Returns:
        Pinecone index object for vector operations
    """
    global _pinecone_index
    
    try:
        api_key = settings.PINECONE_API_KEY
        index_name = settings.PINECONE_INDEX_NAME
        
        if not api_key:
            logger.error("PINECONE_API_KEY not set in settings")
            return None
        
        if not index_name:
            logger.error("PINECONE_INDEX_NAME not set in settings")
            return None
        
        # Initialize Pinecone client
        pc = _get_pinecone_client()
        
        # Get index (like reference - try to get, create if needed)
        try:
            _pinecone_index = pc.Index(index_name)
            logger.info(f"Connected to Pinecone index: {index_name}")
            return _pinecone_index
        except Exception as e:
            # Index doesn't exist, create it
            logger.info(f"Index {index_name} not found. Creating new index...")
            existing_indexes = [idx.name for idx in pc.list_indexes()]
            
            if index_name not in existing_indexes:
                pc.create_index(
                    name=index_name,
                    dimension=1536,  # OpenAI ada-002 dimension
                    metric='cosine',
                    spec={
                        'serverless': {
                            'cloud': 'aws',
                            'region': 'us-east-1'
                        }
                    }
                )
                logger.info(f"Index {index_name} created successfully")
            
            _pinecone_index = pc.Index(index_name)
            logger.info(f"Connected to Pinecone index: {index_name}")
            return _pinecone_index
    
    except Exception as e:
        logger.error(f"Error connecting to Pinecone: {str(e)}")
        return None


def upsert_vectors(index, vectors: List[Dict[str, Any]], batch_size: int = 50) -> bool:
    """
    Upsert vectors to Pinecone in batches.
    
    Args:
        index: Pinecone index object
        vectors: List of vectors in format [{"id": ..., "values": ..., "metadata": ...}, ...]
        batch_size: Number of vectors to upsert per batch
        
    Returns:
        True if successful, False otherwise
    """
    if not index:
        logger.error("Pinecone index not available")
        return False
    
    try:
        total_vectors = len(vectors)
        for i in range(0, total_vectors, batch_size):
            batch = vectors[i:i + batch_size]
            index.upsert(vectors=batch)
            logger.info(f"Upserted batch {i//batch_size + 1} ({len(batch)} vectors)")
        
        logger.info(f"Successfully upserted {total_vectors} vectors to Pinecone")
        return True
    
    except Exception as e:
        logger.error(f"Error upserting vectors to Pinecone: {str(e)}")
        return False


def delete_vectors_by_ids(index, vector_ids: List[str]) -> bool:
    """
    Delete vectors from Pinecone by vector IDs.
    
    Args:
        index: Pinecone index object
        vector_ids: List of vector IDs to delete
        
    Returns:
        True if successful, False otherwise
    """
    if not index:
        logger.error("Pinecone index not available")
        return False
    
    if not vector_ids:
        return True
    
    try:
        # Delete in batches (Pinecone has limits)
        batch_size = 100
        for i in range(0, len(vector_ids), batch_size):
            batch = vector_ids[i:i + batch_size]
            index.delete(ids=batch)
            logger.info(f"Deleted batch {i//batch_size + 1} ({len(batch)} vectors)")
        
        logger.info(f"Successfully deleted {len(vector_ids)} vectors from Pinecone")
        return True
    
    except Exception as e:
        logger.error(f"Error deleting vectors from Pinecone: {str(e)}")
        return False


def delete_vectors_by_document_id(index, document_id: str, max_chunks: int = 1000) -> bool:
    """
    Delete all vectors associated with a document_id from Pinecone.
    Uses pattern-based deletion: {document_id}-chunk-{index}
    
    Note: Pinecone doesn't support delete by metadata filter directly.
    We use the known ID pattern to delete vectors.
    
    Args:
        index: Pinecone index object
        document_id: Document UUID as string
        max_chunks: Maximum number of chunks to attempt deletion (default: 1000)
        
    Returns:
        True if successful, False otherwise
    """
    if not index:
        logger.error("Pinecone index not available")
        return False
    
    try:
        # Generate vector IDs using the pattern: {document_id}-chunk-{index}
        # This matches how we create IDs in process_document()
        vector_ids_to_delete = [
            f"{document_id}-chunk-{i}" 
            for i in range(max_chunks)
        ]
        
        # Delete in batches (Pinecone has batch limits)
        batch_size = 100
        deleted_count = 0
        errors = 0
        
        for i in range(0, len(vector_ids_to_delete), batch_size):
            batch = vector_ids_to_delete[i:i + batch_size]
            try:
                index.delete(ids=batch)
                deleted_count += len(batch)
                logger.debug(f"Deleted batch {i//batch_size + 1} for document {document_id}")
            except Exception as e:
                # Some IDs might not exist (document might have fewer chunks)
                # This is expected, continue with next batch
                errors += 1
                if errors > 10:  # Too many errors, probably no more vectors
                    break
        
        logger.info(f"Deleted vectors for document {document_id} (attempted {deleted_count} IDs)")
        return True
    
    except Exception as e:
        logger.error(f"Error deleting vectors by document_id {document_id}: {str(e)}")
        return False


def query_vectors(index, query_vector: List[float], top_k: int = 5, 
                  document_id: Optional[str] = None, include_metadata: bool = True):
    """
    Query Pinecone for similar vectors.
    Matches reference implementation from rag_tool.py
    
    Args:
        index: Pinecone index object
        query_vector: Query embedding vector
        top_k: Number of results to return
        document_id: Optional filter by document_id
        include_metadata: Whether to include metadata in results
        
    Returns:
        Query results with matches
    """
    if not index:
        logger.error("Pinecone index not available")
        return None
    
    try:
        filter_dict = {}
        if document_id:
            filter_dict = {"document_id": {"$eq": document_id}}
        
        results = index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=include_metadata,
            filter=filter_dict if filter_dict else None
        )
        
        return results
    
    except Exception as e:
        logger.error(f"Error querying Pinecone: {str(e)}")
        return None
