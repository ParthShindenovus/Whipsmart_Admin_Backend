"""
Final node - Prepare final response.
"""
import logging
from ..state import AgentState

logger = logging.getLogger(__name__)


def final_node(state: AgentState) -> AgentState:
    """
    Final node - ensures response is ready.
    """
    # Use final_response if available, otherwise draft_response
    if not state.final_response and state.draft_response:
        state.final_response = state.draft_response
    
    logger.info("[FINAL] Response ready")
    
    return state
