"""
Vehicle search tools for LangGraph Agent V2.
"""
import logging
from typing import Dict, Any, Optional
from agents.langgraph_agent.tools import search_vehicles as v1_search_vehicles

logger = logging.getLogger(__name__)


def search_vehicles(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Search for available vehicles.
    
    Args:
        filters: Search filters (max_price, min_price, min_range, max_range, make, model)
    
    Returns:
        Search results with vehicles
    """
    try:
        tool_result = v1_search_vehicles.run(filters) if hasattr(v1_search_vehicles, "run") else v1_search_vehicles(filters)

        if tool_result.get("success"):
            vehicles = tool_result.get("vehicles", []) or []
            logger.info(f"[VEHICLE_V2] Found {len(vehicles)} vehicles")
            return {
                "success": True,
                "vehicles": vehicles,
                "count": tool_result.get("count", len(vehicles)),
            }

        logger.warning(f"[VEHICLE_V2] Search failed: {tool_result.get('error', 'Unknown error')}")
        return {
            "success": False,
            "error": tool_result.get("error", "Vehicle search failed"),
            "vehicles": [],
        }
            
    except Exception as e:
        logger.error(f"[VEHICLE] Error searching vehicles: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "vehicles": []
        }
