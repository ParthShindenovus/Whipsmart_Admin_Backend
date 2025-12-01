"""
Embedding service for generating vector embeddings.
Uses Azure OpenAI (preferred) or OpenAI API.
Based on reference implementation from Whipsmart Chatbot.
"""
import os
from typing import List
from openai import AzureOpenAI, OpenAI
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Initialize Azure OpenAI client for embeddings (like reference)
_embedding_client = None
_embedding_deployment = None
_embedding_service_type = None


def _get_embedding_client():
    """
    Initialize and return Azure OpenAI client for embeddings.
    Matches reference implementation from app/services/embeddings.py
    """
    global _embedding_client, _embedding_deployment, _embedding_service_type
    
    if _embedding_client is not None:
        return _embedding_client, _embedding_deployment, _embedding_service_type
    
    # Try Azure OpenAI Embedding (separate from chat/completion)
    azure_embedding_key = getattr(settings, 'AZURE_EMBEDDING_API_KEY', None) or getattr(settings, 'AZURE_OPENAI_API_KEY', None)
    azure_embedding_endpoint = getattr(settings, 'AZURE_EMBEDDING_API_URI', None) or getattr(settings, 'AZURE_OPENAI_ENDPOINT', None)
    azure_embedding_version = getattr(settings, 'AZURE_EMBEDDING_API_VERSION', None) or getattr(settings, 'AZURE_OPENAI_API_VERSION', None)
    azure_embedding_deployment = getattr(settings, 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', None) or getattr(settings, 'AZURE_OPENAI_DEPLOYMENT_NAME', None)
    
    if azure_embedding_key and azure_embedding_endpoint and azure_embedding_deployment:
        try:
            _embedding_client = AzureOpenAI(
                api_key=azure_embedding_key,
                azure_endpoint=azure_embedding_endpoint,
                api_version=azure_embedding_version or "2024-02-15-preview"
            )
            _embedding_deployment = azure_embedding_deployment
            _embedding_service_type = 'azure'
            logger.info("Using Azure OpenAI for embeddings")
            return _embedding_client, _embedding_deployment, _embedding_service_type
        except Exception as e:
            logger.warning(f"Failed to initialize Azure OpenAI: {str(e)}")
    
    # Fallback to OpenAI
    openai_key = getattr(settings, 'OPENAI_API_KEY', None) or os.getenv('OPENAI_API_KEY')
    if openai_key:
        try:
            _embedding_client = OpenAI(api_key=openai_key)
            _embedding_deployment = 'text-embedding-ada-002'
            _embedding_service_type = 'openai'
            logger.info("Using OpenAI for embeddings")
            return _embedding_client, _embedding_deployment, _embedding_service_type
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI: {str(e)}")
    
    logger.error("No embedding service available. Please configure Azure OpenAI or OpenAI API key.")
    return None, None, None


def embed(text: str) -> List[float]:
    """
    Generate embedding for a single text.
    Matches reference implementation from app/services/embeddings.py
    
    Args:
        text: Text to embed
        
    Returns:
        List of floats representing the embedding vector
    """
    client, deployment, service_type = _get_embedding_client()
    
    if not client:
        raise ValueError("Embedding service not available. Please configure Azure OpenAI or OpenAI API key.")
    
    try:
        resp = client.embeddings.create(
            model=deployment,
            input=[text]
        )
        return resp.data[0].embedding
    
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        raise


def embed_batch(texts: List[str], batch_size: int = 100) -> List[List[float]]:
    """
    Generate embeddings for a batch of texts.
    Matches reference implementation from app/services/embeddings.py
    
    Args:
        texts: List of texts to embed
        batch_size: Number of texts to process per batch
        
    Returns:
        List of embedding vectors
    """
    client, deployment, service_type = _get_embedding_client()
    
    if not client:
        raise ValueError("Embedding service not available. Please configure Azure OpenAI or OpenAI API key.")
    
    all_embeddings = []
    
    try:
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = client.embeddings.create(
                model=deployment,
                input=batch
            )
            all_embeddings.extend([item.embedding for item in resp.data])
            logger.info(f"Generated embeddings for batch {i//batch_size + 1} ({len(batch)} texts)")
        
        return all_embeddings
    
    except Exception as e:
        logger.error(f"Error generating batch embeddings: {str(e)}")
        raise
