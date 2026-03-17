"""
Routing node - Intelligent routing based on LLM decision.
"""
import logging
from typing import Literal
from ..state import AgentState
from ..tools.llm import llm_call_json

logger = logging.getLogger(__name__)


def route_decision(state: AgentState) -> Literal["knowledge", "vehicle", "direct", "contact"]:
    """
    Decide routing based on state.
    Returns the next node to execute.
    """
    # If contact info detected, route to contact collection
    if state.contact_info_detected:
        logger.info("[ROUTING] Contact info detected, routing to contact collection")
        return "contact"

    # If user explicitly requested team connection, route to contact collection
    if state.question_type == "contact_request":
        logger.info("[ROUTING] Contact request intent, routing to contact collection")
        return "contact"

    # Greetings / goodbyes should not use tools or RAG
    if state.question_type in {"greeting", "goodbye"}:
        logger.info("[ROUTING] Greeting/goodbye detected, routing to direct")
        return "direct"
    
    # Special handling for service_discovery - always use knowledge
    if state.question_type == "service_discovery":
        logger.info("[ROUTING] Service discovery detected, routing to knowledge")
        state.next_action = "knowledge"
        state.routing_reason = "Service discovery query requires knowledge base search"
        return "knowledge"
    
    # Use LLM to decide routing
    prompt = f"""
    Analyze the user's message and determine the best action:
    
    User Message: {state.messages[-1]["content"] if state.messages else ""}
    Intent: {state.question_type}
    Context: {state.context_analysis}
    
    Available actions:
    - knowledge: Search knowledge base for information (use for domain questions, service discovery)
    - vehicle: Search for vehicles (only if user explicitly wants to search for cars)
    - direct: Respond directly without tools (only for greetings, goodbyes, simple acknowledgments)
    
    IMPORTANT: 
    - For service_discovery or domain_question, ALWAYS use "knowledge"
    - For vehicle_search intent, use "vehicle"
    - For greeting/goodbye, use "direct"
    
    Decide which action to take.
    Return JSON: {{"action": "knowledge"|"vehicle"|"direct", "reason": "..."}}
    """
    
    try:
        decision = llm_call_json(prompt, temperature=0.3, max_tokens=200)
        action = decision.get("action", "knowledge")  # Default to knowledge for safety
        state.next_action = action
        state.routing_reason = decision.get("reason", "")
        logger.info(f"[ROUTING] Decided: {action} - {state.routing_reason}")
        return action
    except Exception as e:
        logger.error(f"[ROUTING] Decision failed: {str(e)}")
        # Fallback to knowledge search for domain questions and service discovery
        if state.question_type in ["domain_question", "service_discovery"]:
            return "knowledge"
        return "direct"


def routing_node(state: AgentState) -> AgentState:
    """Routing node - prepares state for next action."""
    # Decision is made in route_decision function
    # This node just passes through
    return state
