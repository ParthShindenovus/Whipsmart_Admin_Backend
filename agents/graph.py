"""
LangGraph agent graph builder.
"""
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from agents.nodes import decision_maker_node, llm_node, router_node, final_node
from agents.tools.rag_tool import rag_tool_node
from agents.tools.car_tool import car_tool_node
import logging

logger = logging.getLogger(__name__)

# Global graph instance
_graph = None


def build_graph():
    """Build and compile the LangGraph agent graph"""
    global _graph
    
    if _graph is not None:
        return _graph
    
    # Use dict-based state for LangGraph compatibility
    graph = StateGraph(dict)

    # Add nodes
    graph.add_node("decision", decision_maker_node)  # Decision maker - first node
    graph.add_node("llm", llm_node)  # LLM node (kept for backward compatibility, but decision_maker is primary)
    graph.add_node("rag", rag_tool_node)
    graph.add_node("car", car_tool_node)
    graph.add_node("final", final_node)

    # Set entry point to decision maker
    graph.set_entry_point("decision")

    # Add conditional routing from decision maker node
    graph.add_conditional_edges(
        "decision",
        router_node,
        {
            "rag": "rag",
            "car": "car",
            "final": "final"
        }
    )

    # After tools return, go to final node
    graph.add_edge("rag", "final")
    graph.add_edge("car", "final")
    
    # Final node ends the graph
    graph.add_edge("final", END)

    _graph = graph.compile()
    logger.info("LangGraph compiled successfully")
    return _graph


def get_graph():
    """Get the compiled graph (singleton)"""
    if _graph is None:
        return build_graph()
    return _graph

