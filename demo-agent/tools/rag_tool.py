from app.services.embeddings import embed
from app.services.pinecone_client import get_index
from app.agent.state import AgentState
from app.utils.logger import logger

def rag_tool_node(state, top_k: int = 5) -> AgentState:
    """
    RAG tool node: searches WhipSmart documents using Pinecone vector search.
    Expects state.tool_result to contain {"action":"rag","query":"..."}
    Replaces state.tool_result with a list of document dicts with text, url, and score.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState(**state)
    
    try:
        query = ""
        if isinstance(state.tool_result, dict):
            query = state.tool_result.get("query", "")
        
        if not query:
            logger.warning("RAG tool called without query")
            state.tool_result = {
                "action": "rag",
                "results": [],
                "error": "No query provided"
            }
            return state

        logger.info(f"RAG search: query='{query}'")
        
        # Generate embedding for query
        query_vector = embed(query)
        
        # Query Pinecone
        index = get_index()
        results = index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True
        )

        # Format results
        docs = []
        for match in results.matches:
            metadata = match.metadata or {}
            doc = {
                "text": metadata.get("text", "")[:2000],  # Limit text length
                "url": metadata.get("url") or metadata.get("source", ""),
                "score": float(match.score),
                "chunk_index": metadata.get("chunk_index", 0)
            }
            docs.append(doc)

        logger.info(f"RAG found {len(docs)} documents")
        
        state.tool_result = {
            "action": "rag",
            "query": query,
            "results": docs
        }
        
        return state

    except Exception as e:
        logger.error(f"Error in rag_tool_node: {str(e)}")
        state.tool_result = {
            "action": "rag",
            "query": query if 'query' in locals() else "",
            "results": [],
            "error": str(e)
        }
        return state

