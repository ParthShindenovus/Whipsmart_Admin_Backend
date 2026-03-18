"""
Postprocessing node - Suggestions and formatting.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from ..state import AgentState
from ..config import MAX_PARALLEL_WORKERS, TEAM_CONNECTION_THRESHOLD
from agents.suggestions import generate_suggestions

logger = logging.getLogger(__name__)

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BARE_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>()\]]+")


def _strip_links(text: str) -> str:
    """
    Remove URLs from model output. Keeps the visible link text for markdown links.
    """
    if not text:
        return text
    # Convert markdown links to just their label: [label](url) -> label
    text = _MD_LINK_RE.sub(r"\1", text)
    # Remove any remaining bare URLs
    text = _BARE_URL_RE.sub("", text)
    # Clean up whitespace introduced by removals
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_response(response: str, rag_context: list) -> str:
    """
    Format response (sanitize links, etc.).
    """
    # Intentionally do not append citations/sources to the user-facing response.
    # Also ensure the response itself contains no links.
    return _strip_links(response)


def postprocess_node(state: AgentState) -> AgentState:
    """
    Final processing: suggestions and formatting.
    """
    logger.info("[POSTPROCESS] Starting postprocessing")

    # Always format response (cheap)
    formatted_response = format_response(state.draft_response or "", state.rag_context)
    state.final_response = formatted_response or state.draft_response

    # Bypass suggestion generation entirely during follow-ups / info collection
    in_followup_flow = bool(
        state.collecting_user_info
        or state.needs_info
        or state.step in {"awaiting_team_connection", "name", "email", "phone", "confirmation", "callback_schedule"}
        or state.awaiting_team_connection_confirm
    )

    if in_followup_flow:
        suggestions = []
        logger.info("[POSTPROCESS] Skipping suggestion generation (follow-up/info flow)")
    else:
        # Generate suggestions only in normal chat flow
        try:
            suggestions = generate_suggestions(state.messages, state.draft_response, 3)
        except Exception as e:
            logger.warning(f"[POSTPROCESS] Suggestion generation failed: {str(e)}")
            suggestions = []

    state.suggestions = suggestions

    # Persistent, gentle team connection offer after threshold until connected
    missing_contact = (not state.user_name) or (not state.user_email) or (not state.user_phone)
    if (
        not state.is_complete
        and not state.collecting_user_info
        and not state.needs_info
        and state.step == "chatting"
        and state.question_count >= TEAM_CONNECTION_THRESHOLD
    ):
        state.should_offer_team_connection = True
        state.followup_type = "team_connection"
        if missing_contact:
            state.followup_message = (
                "If you’d like, I can **connect you with our team** and they can help you with the next steps.\n\n"
                "Reply **yes** to connect, and I’ll grab your **name, email, and phone** so we can reach you."
            )
        else:
            state.followup_message = (
                "If you’d like, I can **connect you with our team** to help with next steps.\n\n"
                "Reply **yes** to connect — I’ll quickly confirm your saved details before we proceed."
            )
        state.awaiting_team_connection_confirm = True
        state.step = "awaiting_team_connection"
        state.last_team_offer_count = state.question_count
        logger.info(f"[POSTPROCESS] Offering team connection (persistent) at question_count={state.question_count}")
    
    logger.info(f"[POSTPROCESS] Generated {len(suggestions)} suggestions")
    
    return state
