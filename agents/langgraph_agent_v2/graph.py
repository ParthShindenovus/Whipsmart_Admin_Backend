"""
LangGraph structure for Agent V2.
"""
import logging
from langgraph.graph import StateGraph, END
from typing import Literal
from .state import AgentState
from .nodes import (
    preprocess_node,
    routing_node,
    route_decision,
    knowledge_retrieval_node,
    vehicle_search_node,
    contact_collection_node,
    should_route_to_collection,
    reasoning_node,
    response_generation_node,
    validation_node,
    validation_decision,
    postprocess_node,
    final_node
)

logger = logging.getLogger(__name__)

# Conditional edge: only validate if we used RAG (knowledge retrieval).
def should_run_validation(state: AgentState) -> Literal["validate", "skip"]:
    return "validate" if getattr(state, "used_rag", False) else "skip"

# Global graph instance
_graph = None


def build_graph():
    """Build and compile the LangGraph agent graph."""
    global _graph
    
    if _graph is not None:
        return _graph
    
    # Create graph with AgentState
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("preprocess", preprocess_node)
    graph.add_node("route", routing_node)
    graph.add_node("knowledge", knowledge_retrieval_node)
    graph.add_node("vehicle", vehicle_search_node)
    graph.add_node("contact", contact_collection_node)
    graph.add_node("reason", reasoning_node)
    graph.add_node("generate", response_generation_node)
    graph.add_node("validate", validation_node)
    graph.add_node("postprocess", postprocess_node)
    graph.add_node("final", final_node)
    
    # Set entry point
    graph.set_entry_point("preprocess")
    
    # Conditional: preprocess -> contact or route
    graph.add_conditional_edges(
        "preprocess",
        should_route_to_collection,
        {
            "contact": "contact",
            "continue": "route"
        }
    )
    
    # Conditional: route -> knowledge, vehicle, or direct
    graph.add_conditional_edges(
        "route",
        route_decision,
        {
            "knowledge": "knowledge",
            "vehicle": "vehicle",
            "direct": "reason"
        }
    )
    
    # After knowledge/vehicle, go to reasoning
    graph.add_edge("knowledge", "reason")
    graph.add_edge("vehicle", "reason")
    
    # Sequential: reasoning -> generation -> (validation if RAG was used)
    graph.add_edge("reason", "generate")
    graph.add_conditional_edges(
        "generate",
        should_run_validation,
        {
            "validate": "validate",
            "skip": "postprocess",
        },
    )
    
    # Conditional: validation -> retry or continue
    graph.add_conditional_edges(
        "validate",
        validation_decision,
        {
            "retry": "generate",  # Loop back to generation
            "continue": "postprocess"
        }
    )
    
    # After postprocess, go to final
    graph.add_edge("postprocess", "final")
    
    # Contact collection can end or continue
    graph.add_edge("contact", "final")
    
    # Final node ends
    graph.add_edge("final", END)
    
    # Compile graph
    _graph = graph.compile()
    logger.info("[GRAPH] LangGraph compiled successfully")
    
    return _graph


def get_graph():
    """Get the compiled graph (singleton)."""
    if _graph is None:
        return build_graph()
    return _graph
