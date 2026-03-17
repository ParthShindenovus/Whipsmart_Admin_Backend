"""
RAG (Retrieval Augmented Generation) tools for LangGraph Agent V2.

Important: Do NOT import `search_knowledge_base` from `agents.tools.rag_tool` because that module exposes
`rag_tool_node` (LangGraph node), not a callable search function.

We reuse the proven tool implementation in `agents.langgraph_agent.tools.search_knowledge_base`.
"""
import logging
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from agents.langgraph_agent.tools import search_knowledge_base as v1_search_knowledge_base
from ..config import (
    ENABLE_RAG_QUERY_VARIATIONS_DOMAIN,
    ENABLE_RAG_QUERY_VARIATIONS_SERVICE_DISCOVERY,
    MAX_RAG_QUERY_VARIATIONS,
)

logger = logging.getLogger(__name__)


def _normalize_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize results into V2 internal chunk format:
    {
      "content": "...",
      "score": 0.0,
      "metadata": {"url": "..."}
    }
    """
    normalized: List[Dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict):
            continue
        normalized.append(
            {
                "content": r.get("text", "") or "",
                "score": r.get("score", 0.0) or 0.0,
                "metadata": {"url": r.get("source", "") or ""},
            }
        )
    return normalized


def search_knowledge_base(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Search knowledge base using the existing V1 tool, then normalize results for V2.
    """
    if not query:
        return []

    try:
        tool_result = v1_search_knowledge_base.run(query) if hasattr(v1_search_knowledge_base, "run") else v1_search_knowledge_base(query)

        if tool_result.get("success") and tool_result.get("results"):
            results = tool_result["results"][:top_k]
            normalized = _normalize_results(results)
            logger.info(f"[RAG_V2] Retrieved {len(normalized)} results for query: {query[:50]}...")
            return normalized

        logger.info(f"[RAG_V2] No results found for query: {query[:50]}...")
        return []

    except Exception as e:
        logger.error(f"[RAG_V2] Error searching knowledge base: {str(e)}", exc_info=True)
        return []


def generate_query_variations(base_query: str, question_type: str) -> List[str]:
    """
    Generate query variations for better retrieval.
    
    Args:
        base_query: Original query
        question_type: Type of question (service_discovery, domain_question, etc.)
    
    Returns:
        List of query variations
    """
    variations = [base_query]
    
    if question_type == "service_discovery":
        if ENABLE_RAG_QUERY_VARIATIONS_SERVICE_DISCOVERY:
            variations.extend([
                "WhipSmart services",
                "WhipSmart features",
                "what does WhipSmart offer",
                "WhipSmart capabilities",
                "WhipSmart what we do",
            ])
    elif question_type == "domain_question":
        # Add domain-specific variations (optional)
        if ENABLE_RAG_QUERY_VARIATIONS_DOMAIN:
            variations.extend([
                f"{base_query} WhipSmart",
                f"{base_query} novated lease",
                f"{base_query} electric vehicle",
            ])
    
    # Cap extra variations to control cost/latency
    base = variations[0:1]
    extra = variations[1 : 1 + max(0, int(MAX_RAG_QUERY_VARIATIONS))]
    return base + extra


def search_with_variations(
    base_query: str,
    question_type: str,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Search knowledge base with multiple query variations in parallel.
    
    Args:
        base_query: Original query
        question_type: Type of question
        top_k: Number of results per query
    
    Returns:
        Combined and ranked results
    """
    # Generate variations
    queries = generate_query_variations(base_query, question_type)
    
    # Search in parallel
    with ThreadPoolExecutor(max_workers=min(len(queries), 4)) as executor:
        search_futures = [
            executor.submit(search_knowledge_base, query, top_k)
            for query in queries
        ]
        all_results = [f.result() for f in search_futures]
    
    # Combine and deduplicate
    seen_ids = set()
    combined_results = []
    
    for results in all_results:
        for result in results:
            # Use URL or content hash as unique identifier
            result_id = result.get("metadata", {}).get("url") or hash(result.get("content", ""))
            if result_id not in seen_ids:
                seen_ids.add(result_id)
                combined_results.append(result)
    
    # Sort by relevance score if available
    combined_results.sort(
        key=lambda x: x.get("score", 0.0),
        reverse=True
    )
    
    # Return top_k
    logger.info(f"[RAG] Combined {len(combined_results)} unique results from {len(queries)} queries")
    return combined_results[:top_k]
