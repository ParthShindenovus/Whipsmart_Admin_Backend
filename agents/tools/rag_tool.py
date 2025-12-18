"""
RAG tool for searching documents using Pinecone.
Integrates with Django's knowledgebase services.
"""
from agents.state import AgentState
from knowledgebase.services.embedding_service import embed
from knowledgebase.services.pinecone_service import get_pinecone_index, query_vectors
import logging

logger = logging.getLogger(__name__)


def rag_tool_node(state, top_k: int = 3) -> AgentState:
    """
    RAG tool node: searches WhipSmart documents using Pinecone vector search.
    Expects state.tool_result to contain {"action":"rag","query":"..."}
    Replaces state.tool_result with a list of document dicts with text, url, and score.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState.from_dict(state)
    
    try:
        logger.info("=" * 80)
        logger.info(f"[RAG] RAG TOOL NODE - Called")
        
        query = ""
        if isinstance(state.tool_result, dict):
            query = state.tool_result.get("query", "")
        
        if not query:
            logger.warning("[WARN]  RAG tool called without query")
            state.tool_result = {
                "action": "rag",
                "results": [],
                "error": "No query provided"
            }
            logger.info("=" * 80)
            return state.to_dict() if hasattr(state, 'to_dict') else state

        logger.info(f"[MSG] Query: {query}")
        logger.info(f"[INFO] Top K: {top_k}")
        
        # Generate embedding for query
        logger.info("[PROC]  Generating embedding for query...")
        query_vector = embed(query)
        logger.info(f"[OK] Embedding generated (dimension: {len(query_vector)})")
        
        # Get Pinecone index (already initialized at startup)
        index = get_pinecone_index()
        if not index:
            logger.error("[ERROR] Pinecone index not available")
            state.tool_result = {
                "action": "rag",
                "query": query,
                "results": [],
                "error": "Pinecone index not available"
            }
            logger.info("=" * 80)
            return state.to_dict() if hasattr(state, 'to_dict') else state
        
        # Query Pinecone (index already initialized at startup)
        logger.info(f"[SEARCH] Querying Pinecone with top_k={top_k}...")
        results = query_vectors(
            index=index,
            query_vector=query_vector,
            top_k=top_k,
            include_metadata=True
        )

        # Format results and fetch full chunk text from database
        docs = []
        if results and hasattr(results, 'matches'):
            logger.info(f"[STATS] Found {len(results.matches)} matches from Pinecone")

            retrieved_chunk_ids = []

            for i, match in enumerate(results.matches, 1):
                metadata = match.metadata or {}
                document_id = metadata.get("document_id", "")
                chunk_index = metadata.get("chunk_index", 0)
                chunk_id = getattr(match, "id", None)
                
                # Use text directly from Pinecone metadata instead of hitting the database
                # Limit to 2000 characters to avoid excessively long context
                full_text = metadata.get("text", "")[:2000]
                
                # Only include primary URL if document type is 'url', not for file-based documents
                file_type = metadata.get("file_type", "")
                url_value = ""
                
                if file_type == "url":
                    # For URL documents, include the URL
                    url_value = metadata.get("url") or ""

                # Optional reference URL (e.g., PDF Q&A chunks with a source page)
                reference_url = metadata.get("reference_url") or ""
                retrieved_chunk_ids.append(chunk_id or f"{document_id}-chunk-{chunk_index}")

                doc = {
                    "text": full_text,  # Use full text from DB or metadata
                    "url": url_value,  # Only URLs for URL document type
                    "score": float(match.score) if hasattr(match, 'score') else 0.0,
                    "chunk_index": chunk_index,
                    "document_id": document_id,
                    "document_title": metadata.get("document_title", ""),
                    "file_type": file_type,  # Include file type for reference
                    "chunk_id": chunk_id,  # Pinecone vector ID, if available
                    "reference_url": reference_url,  # Optional source/reference URL for this chunk
                }
                docs.append(doc)
                
                # Improved logging with more context
                preview_length = 150
                text_preview = doc['text'][:preview_length] if doc['text'] else "N/A"
                logger.info(
                    f"  [{i}] Score: {doc['score']:.4f} | "
                    f"Chunk ID: {doc.get('chunk_id') or f'{document_id}-chunk-{chunk_index}'} | "
                    f"Doc: {doc.get('document_title', 'N/A')[:30]} | "
                    f"Chunk #{chunk_index} | Text: {text_preview}..."
                )
        else:
            logger.warning("[WARN]  No matches found in Pinecone")

        # Log summary of retrieved chunk IDs for this query
        if docs:
            logger.info(f"[RAG] Query: '{query}' | Retrieved chunk_ids: {retrieved_chunk_ids}")
        else:
            logger.info(f"[RAG] Query: '{query}' | Retrieved no chunks")

        logger.info(f"[OK] RAG Tool Results: {len(docs)} documents found")
        logger.info("=" * 80)
        
        state.tool_result = {
            "action": "rag",
            "query": query,
            "results": docs
        }
        
        return state.to_dict() if hasattr(state, 'to_dict') else state

    except Exception as e:
        logger.error(f"Error in rag_tool_node: {str(e)}", exc_info=True)
        state.tool_result = {
            "action": "rag",
            "query": query if 'query' in locals() else "",
            "results": [],
            "error": str(e)
        }
        return state.to_dict() if hasattr(state, 'to_dict') else state

