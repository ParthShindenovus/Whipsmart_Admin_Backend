from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import llm_node, router_node, final_node
from app.agent.tools.rag_tool import rag_tool_node
from app.agent.tools.car_tool import car_tool_node
from app.utils.logger import logger

def build_graph():
    """Build and compile the LangGraph agent graph"""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("llm", llm_node)
    graph.add_node("rag", rag_tool_node)
    graph.add_node("car", car_tool_node)
    graph.add_node("final", final_node)

    # Set entry point
    graph.set_entry_point("llm")

    # Add conditional routing from LLM node
    graph.add_conditional_edges(
        "llm",
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

    compiled_graph = graph.compile()
    logger.info("LangGraph compiled successfully")
    return compiled_graph

