from app.agent.state import AgentState
from app.utils.logger import logger

def car_tool_node(state) -> AgentState:
    """
    Car search tool node (mock implementation).
    Expects state.tool_result = {"action":"car","filters":{...}}
    Returns a list of car dicts matching the filters.
    In production, this will call the actual client API.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState(**state)
    
    try:
        filters = {}
        if isinstance(state.tool_result, dict):
            filters = state.tool_result.get("filters", {})

        logger.info(f"Car search: filters={filters}")

        # Mock car database
        all_cars = [
            {"car_id": 1, "make": "Tesla", "model": "Model 3", "price_month": 130, "range_km": 420, "year": 2024},
            {"car_id": 2, "make": "BYD", "model": "Atto 3", "price_month": 110, "range_km": 400, "year": 2024},
            {"car_id": 3, "make": "Tesla", "model": "Model Y", "price_month": 150, "range_km": 480, "year": 2024},
            {"car_id": 4, "make": "MG", "model": "ZS EV", "price_month": 95, "range_km": 320, "year": 2023},
            {"car_id": 5, "make": "Polestar", "model": "2", "price_month": 140, "range_km": 450, "year": 2024},
        ]

        # Apply filters
        filtered_cars = all_cars.copy()
        
        if filters.get("max_price"):
            filtered_cars = [c for c in filtered_cars if c["price_month"] <= filters["max_price"]]
        
        if filters.get("min_price"):
            filtered_cars = [c for c in filtered_cars if c["price_month"] >= filters["min_price"]]
        
        if filters.get("min_range"):
            filtered_cars = [c for c in filtered_cars if c["range_km"] >= filters["min_range"]]
        
        if filters.get("max_range"):
            filtered_cars = [c for c in filtered_cars if c["range_km"] <= filters["max_range"]]
        
        if filters.get("make"):
            make_filter = filters["make"].lower()
            filtered_cars = [c for c in filtered_cars if c["make"].lower() == make_filter]
        
        if filters.get("model"):
            model_filter = filters["model"].lower()
            filtered_cars = [c for c in filtered_cars if c["model"].lower() == model_filter]

        logger.info(f"Car search found {len(filtered_cars)} cars")

        state.tool_result = {
            "action": "car",
            "filters": filters,
            "results": filtered_cars
        }
        
        return state

    except Exception as e:
        logger.error(f"Error in car_tool_node: {str(e)}")
        state.tool_result = {
            "action": "car",
            "filters": filters if 'filters' in locals() else {},
            "results": [],
            "error": str(e)
        }
        return state

