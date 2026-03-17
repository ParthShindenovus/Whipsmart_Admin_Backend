"""
Contact collection node.
LLM-driven flow for collecting, confirming, and updating contact details.
"""
import logging
from typing import Any, Dict, Literal

from ..state import AgentState
from ..tools.llm import llm_call_json

logger = logging.getLogger(__name__)


def should_route_to_collection(state: AgentState) -> Literal["contact", "continue"]:
    """
    Route to contact flow when user wants connection or contact data is being handled.
    """
    if (
        (state.contact_info_detected and state.question_type != "service_discovery")
        or state.question_type == "contact_request"
        or state.collecting_user_info
        or state.step in {"name", "email", "phone", "confirmation"}
    ):
        logger.info("[CONTACT] Routing to contact flow")
        return "contact"

    return "continue"


def _build_confirmation_message(state: AgentState, intro: str = "Before I connect you, please confirm these details:") -> str:
    return (
        f"{intro}\n\n"
        f"- **Name**: {state.user_name or 'Not set'}\n"
        f"- **Email**: {state.user_email or 'Not set'}\n"
        f"- **Phone**: {state.user_phone or 'Not set'}\n\n"
        "Reply with confirmation (for example: **yes**, **ok done**, **confirmed**), or tell me what to change."
    )


def _contact_intent_llm(user_message: str, state: AgentState) -> Dict[str, Any]:
    """
    LLM interprets user intent and extracts contact updates.
    """
    prompt = f"""
You are analyzing a user's message in a contact-confirmation flow.

Current known details:
- name: {state.user_name or 'null'}
- email: {state.user_email or 'null'}
- phone: {state.user_phone or 'null'}
- current_step: {state.step}

User message:
\"\"\"
{user_message}
\"\"\"

Return JSON only with this schema:
{{
  "intent": "confirm" | "change" | "provide_details" | "ask_field" | "unclear" | "decline",
  "confirmed": true/false,
  "updates": {{
    "name": string|null,
    "email": string|null,
    "phone": string|null
  }},
  "requested_field": "name" | "email" | "phone" | null,
  "reply_message": string
}}

Rules:
1) Treat confirmations broadly: "yes", "ok", "ok done", "looks good", "confirmed", "go ahead" => confirm.
2) If message asks to change details, extract the new values in updates.
3) If message provides name/email/phone directly, capture them in updates.
4) requested_field should be set only when user asks to change just one field without value.
5) reply_message should be short and context-aware.
"""

    try:
        result = llm_call_json(prompt=prompt, temperature=0.1, max_tokens=350)
        if not isinstance(result, dict):
            return {}
        return result
    except Exception as exc:
        logger.warning("[CONTACT] LLM intent parse failed: %s", str(exc))
        return {}


def _apply_updates(state: AgentState, updates: Dict[str, Any]) -> bool:
    """Apply LLM-extracted updates to state."""
    if not isinstance(updates, dict):
        return False

    changed = False

    name = updates.get("name")
    if isinstance(name, str) and name.strip():
        state.user_name = name.strip()
        changed = True

    email = updates.get("email")
    if isinstance(email, str) and email.strip():
        state.user_email = email.strip().lower()
        changed = True

    phone = updates.get("phone")
    if isinstance(phone, str) and phone.strip():
        state.user_phone = phone.strip()
        changed = True

    return changed


def _all_contact_present(state: AgentState) -> bool:
    return bool(state.user_name and state.user_email and state.user_phone)


def _next_missing_field(state: AgentState) -> str:
    if not state.user_name:
        return "name"
    if not state.user_email:
        return "email"
    return "phone"


def contact_collection_node(state: AgentState) -> AgentState:
    """
    Handle contact information collection with LLM-driven interpretation.
    """
    logger.info("[CONTACT] Processing contact flow")

    user_message = state.messages[-1]["content"] if state.messages else ""

    # Highest priority: if already in confirmation, process confirmation/change first.
    if state.step == "confirmation":
        parsed = _contact_intent_llm(user_message, state)
        intent = parsed.get("intent")

        if parsed.get("confirmed") is True or intent == "confirm":
            state.step = "complete"
            state.is_complete = True
            state.collecting_user_info = False
            state.needs_info = None
            state.final_response = "Thanks, confirmed. **Our team will contact you shortly.**"
            return state

        updated = _apply_updates(state, parsed.get("updates", {}))
        if updated and _all_contact_present(state):
            state.final_response = _build_confirmation_message(state, "Updated. Please confirm these details:")
            return state

        requested_field = parsed.get("requested_field")
        if requested_field in {"name", "email", "phone"}:
            state.step = requested_field
            state.needs_info = requested_field
            state.final_response = f"Sure - what should I update your **{requested_field}** to?"
            return state

        reply_message = parsed.get("reply_message")
        if isinstance(reply_message, str) and reply_message.strip():
            state.final_response = reply_message.strip()
        else:
            state.final_response = (
                "Please tell me what to change in one line, for example: \"change name to Noah\" "
                "or \"change email to noah@example.com\"."
            )
        return state

    # If user explicitly requested connection and all details are known, ask confirmation.
    if state.question_type == "contact_request" and _all_contact_present(state):
        state.step = "confirmation"
        state.needs_info = None
        state.collecting_user_info = False
        state.final_response = _build_confirmation_message(state)
        return state

    # Collect details flow.
    state.collecting_user_info = True
    parsed = _contact_intent_llm(user_message, state)
    _apply_updates(state, parsed.get("updates", {}))

    if _all_contact_present(state):
        state.step = "confirmation"
        state.needs_info = None
        state.collecting_user_info = False
        state.final_response = _build_confirmation_message(state)
        return state

    # Ask for next missing detail.
    next_field = _next_missing_field(state)
    state.step = next_field
    state.needs_info = next_field

    if next_field == "name":
        state.final_response = "What is your **name** so I can connect you with our team?"
    elif next_field == "email":
        state.final_response = "Thanks - what is your **email** so our team can reach you?"
    else:
        state.final_response = "What is the best **phone number** for our team to call you on?"

    return state
