"""
Vehicle search node.
"""
import logging
from ..state import AgentState
from ..tools.vehicle_search import search_vehicles

logger = logging.getLogger(__name__)


def vehicle_search_node(state: AgentState) -> AgentState:
    """
    Search for vehicles based on user query.
    """
    user_message = state.messages[-1]["content"] if state.messages else ""
    
    logger.info(f"[VEHICLE] Searching vehicles for: {user_message[:50]}...")
    
    # Extract filters from message (simplified - could be enhanced with LLM)
    filters = {}
    
    # Search
    result = search_vehicles(filters)
    
    if result.get("success"):
        vehicles = result.get("vehicles", [])
        logger.info(f"[VEHICLE] Found {len(vehicles)} vehicles")
        # Store in state for use in response generation
        state.tool_calls.append({
            "tool": "vehicle_search",
            "result": result
        })
    else:
        logger.warning(f"[VEHICLE] Search failed: {result.get('error')}")
    
    return state
