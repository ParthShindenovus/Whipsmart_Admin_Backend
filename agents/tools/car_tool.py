"""
Car search tool (mock implementation).
In production, this will call the actual car search API.
"""
from agents.state import AgentState
import logging
import json

logger = logging.getLogger(__name__)


def car_tool_node(state) -> AgentState:
    """
    Car search tool node (mock implementation).
    Expects state.tool_result = {"action":"car","filters":{...}}
    Returns a list of car dicts matching the filters.
    In production, this will call the actual client API.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState.from_dict(state)
    
    try:
        logger.info("=" * 80)
        logger.info(f"[CAR] CAR TOOL NODE - Called")
        
        filters = {}
        if isinstance(state.tool_result, dict):
            filters = state.tool_result.get("filters", {})

        logger.info(f"[RAG] Search Filters: {filters}")
        
        if filters:
            filter_details = []
            if filters.get("max_price"):
                filter_details.append(f"Max Price: ${filters['max_price']}")
            if filters.get("min_price"):
                filter_details.append(f"Min Price: ${filters['min_price']}")
            if filters.get("min_range"):
                filter_details.append(f"Min Range: {filters['min_range']}km")
            if filters.get("max_range"):
                filter_details.append(f"Max Range: {filters['max_range']}km")
            if filters.get("make"):
                filter_details.append(f"Make: {filters['make']}")
            if filters.get("model"):
                filter_details.append(f"Model: {filters['model']}")
            logger.info(f"[INFO] Applied Filters: {', '.join(filter_details) if filter_details else 'None'}")
        else:
            logger.info("[INFO] No filters applied - searching all cars")

        # Mock car database
        all_cars = [
            {"car_id": 1, "make": "Tesla", "model": "Model 3", "price_month": 130, "range_km": 420, "year": 2024},
            {"car_id": 2, "make": "BYD", "model": "Atto 3", "price_month": 110, "range_km": 400, "year": 2024},
            {"car_id": 3, "make": "Tesla", "model": "Model Y", "price_month": 150, "range_km": 480, "year": 2024},
            {"car_id": 4, "make": "MG", "model": "ZS EV", "price_month": 95, "range_km": 320, "year": 2023},
            {"car_id": 5, "make": "Polestar", "model": "2", "price_month": 140, "range_km": 450, "year": 2024},
        ]
        
        logger.info(f"[STATS] Total cars in database: {len(all_cars)}")

        # Apply filters
        filtered_cars = all_cars.copy()
        initial_count = len(filtered_cars)
        
        if filters.get("max_price"):
            filtered_cars = [c for c in filtered_cars if c["price_month"] <= filters["max_price"]]
            logger.info(f"  -> After max_price filter: {len(filtered_cars)} cars")
        
        if filters.get("min_price"):
            filtered_cars = [c for c in filtered_cars if c["price_month"] >= filters["min_price"]]
            logger.info(f"  -> After min_price filter: {len(filtered_cars)} cars")
        
        if filters.get("min_range"):
            filtered_cars = [c for c in filtered_cars if c["range_km"] >= filters["min_range"]]
            logger.info(f"  -> After min_range filter: {len(filtered_cars)} cars")
        
        if filters.get("max_range"):
            filtered_cars = [c for c in filtered_cars if c["range_km"] <= filters["max_range"]]
            logger.info(f"  -> After max_range filter: {len(filtered_cars)} cars")
        
        if filters.get("make"):
            make_filter = filters["make"].lower()
            filtered_cars = [c for c in filtered_cars if c["make"].lower() == make_filter]
            logger.info(f"  -> After make filter: {len(filtered_cars)} cars")
        
        if filters.get("model"):
            model_filter = filters["model"].lower()
            filtered_cars = [c for c in filtered_cars if c["model"].lower() == model_filter]
            logger.info(f"  -> After model filter: {len(filtered_cars)} cars")

        logger.info(f"[OK] Car Tool Results: {len(filtered_cars)} cars found (from {initial_count} total)")
        
        if filtered_cars:
            logger.info("[INFO] Matching Cars:")
            for i, car in enumerate(filtered_cars, 1):
                logger.info(f"  [{i}] {car['make']} {car['model']} ({car['year']}) - ${car['price_month']}/month, {car['range_km']}km range")
        else:
            logger.warning("[WARN]  No cars match the search criteria")
        
        logger.info("=" * 80)

        state.tool_result = {
            "action": "car",
            "filters": filters,
            "results": filtered_cars
        }
        
        return state.to_dict() if hasattr(state, 'to_dict') else state

    except Exception as e:
        logger.error(f"Error in car_tool_node: {str(e)}", exc_info=True)
        state.tool_result = {
            "action": "car",
            "filters": filters if 'filters' in locals() else {},
            "results": [],
            "error": str(e)
        }
        return state.to_dict() if hasattr(state, 'to_dict') else state

