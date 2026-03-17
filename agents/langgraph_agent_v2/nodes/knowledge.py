"""
Knowledge retrieval node - Enhanced RAG search with parallel queries.
"""
import logging
from ..state import AgentState
from ..tools.rag import search_knowledge_base
from ..config import RAG_TOP_K

logger = logging.getLogger(__name__)


def knowledge_retrieval_node(state: AgentState) -> AgentState:
    """
    Enhanced RAG search with query variations.
    Special handling for service_discovery queries.
    """
    query = state.rag_query or state.messages[-1]["content"] if state.messages else ""
    question_type = state.question_type or "domain_question"
    
    logger.info(f"[KNOWLEDGE] Question type: {question_type}, Query: {query[:50]}...")
    
    # Special handling for service discovery
    if question_type == "service_discovery":
        # Force service discovery query
        query = "WhipSmart services features capabilities what we offer what does WhipSmart do"
        logger.info(f"[KNOWLEDGE] Service discovery detected - using service query")
    
    # Single RAG call (avoid multiple Pinecone searches per message)
    results = search_knowledge_base(query, top_k=RAG_TOP_K)
    
    state.rag_context = results
    state.knowledge_results = results
    state.used_rag = True
    
    logger.info(f"[KNOWLEDGE] Retrieved {len(results)} results")
    
    return state
