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
        or state.step in {"name", "email", "phone", "confirmation", "callback_schedule"}
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


def _build_callback_prompt(state: AgentState) -> str:
    known_tz = f" ({state.callback_timezone})" if state.callback_timezone else ""
    return (
        "Thanks — one more thing so we can schedule it properly.\n\n"
        "What is your **preferred date and time** for a callback"
        f"{known_tz}?\n\n"
        "Example: **Tomorrow 3pm**, **Friday 10:30am**, or **18 Mar at 2pm AEST**."
    )


def _callback_intent_llm(user_message: str, state: AgentState) -> Dict[str, Any]:
    """
    LLM interprets user's callback scheduling preference.
    We store free-text to avoid timezone/locale parsing bugs.
    """
    prompt = f"""
You are analyzing a user's message in a callback scheduling step.

Known contact details:
- name: {state.user_name or 'null'}
- email: {state.user_email or 'null'}
- phone: {state.user_phone or 'null'}
- current_step: {state.step}

Previously stored callback preference:
- callback_preferred_datetime: {state.callback_preferred_datetime or 'null'}
- callback_timezone: {state.callback_timezone or 'null'}

User message:
\"\"\"
{user_message}
\"\"\"

Return JSON only with this schema:
{{
  "intent": "provide_datetime" | "ask_clarify" | "decline" | "unclear",
  "preferred_datetime": string|null,
  "timezone": string|null,
  "needs_clarification": true/false,
  "clarification_question": string|null
}}

Rules:
1) Accept natural language date/time like "tomorrow 3pm", "Friday morning", "next week Tuesday 2pm".
2) If user provides a timezone ("AEST", "AEDT", "UTC+10", "GMT+5"), put it in timezone.
3) If they only provide a date OR only a time ("Friday" or "3pm"), set needs_clarification=true and ask the missing piece.
4) If they refuse ("anytime", "no preference", "you decide", "can't say"), set intent=decline.
5) Do NOT invent a datetime; only extract what the user wrote.
"""
    try:
        result = llm_call_json(prompt=prompt, temperature=0.1, max_tokens=250)
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        logger.warning("[CONTACT] Callback parse failed: %s", str(exc))
        return {}


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

    # Callback scheduling step (after confirmation).
    if state.step == "callback_schedule":
        parsed = _callback_intent_llm(user_message, state)
        intent = parsed.get("intent")

        if intent == "provide_datetime" and isinstance(parsed.get("preferred_datetime"), str) and parsed["preferred_datetime"].strip():
            state.callback_preferred_datetime = parsed["preferred_datetime"].strip()
            tz = parsed.get("timezone")
            if isinstance(tz, str) and tz.strip():
                state.callback_timezone = tz.strip()

            state.step = "complete"
            state.is_complete = True
            state.collecting_user_info = False
            state.needs_info = None
            pretty = state.callback_preferred_datetime
            if state.callback_timezone and state.callback_timezone.lower() not in pretty.lower():
                pretty = f"{pretty} ({state.callback_timezone})"
            state.final_response = f"Perfect — noted. **Our team will call you around {pretty}.**"
            return state

        if parsed.get("needs_clarification") is True:
            q = parsed.get("clarification_question")
            if isinstance(q, str) and q.strip():
                state.final_response = q.strip()
            else:
                state.final_response = "Sure — what **date** and what **time** works best for the callback?"
            return state

        if intent == "decline":
            state.step = "complete"
            state.is_complete = True
            state.collecting_user_info = False
            state.needs_info = None
            state.final_response = "No problem — **our team will reach out shortly**, and you can pick a convenient time then."
            return state

        state.final_response = "What **date and time** works best for a callback?"
        return state

    # Highest priority: if already in confirmation, process confirmation/change first.
    if state.step == "confirmation":
        parsed = _contact_intent_llm(user_message, state)
        intent = parsed.get("intent")

        if parsed.get("confirmed") is True or intent == "confirm":
            # After confirmation, ask for preferred callback date/time (unless already captured).
            if state.callback_preferred_datetime:
                state.step = "complete"
                state.is_complete = True
                state.collecting_user_info = False
                state.needs_info = None
                state.final_response = "Thanks, confirmed. **Our team will contact you shortly.**"
            else:
                state.step = "callback_schedule"
                state.is_complete = False
                state.collecting_user_info = True
                state.needs_info = "callback_schedule"
                state.final_response = _build_callback_prompt(state)
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
