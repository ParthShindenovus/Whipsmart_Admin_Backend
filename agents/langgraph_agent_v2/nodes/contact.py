"""
Contact collection node.
"""
import logging
import re
from typing import Literal, Optional, Tuple

from ..state import AgentState
from ..tools.contact_extraction import extract_contact_info

logger = logging.getLogger(__name__)


def _is_yes(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"yes", "y", "yep", "yeah", "correct", "looks good", "that is correct", "confirm"}


def _render_confirmation(state: AgentState, intro: str) -> str:
    return (
        f"{intro}\n\n"
        f"- **Name**: {state.user_name or 'Not set'}\n"
        f"- **Email**: {state.user_email or 'Not set'}\n"
        f"- **Phone**: {state.user_phone or 'Not set'}\n\n"
        "Reply **yes** to confirm, or tell me what to change (for example: \"change name to meteor\")."
    )


def _extract_field_update(message: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract explicit field update instructions from free text."""
    msg = (message or "").strip()
    if not msg:
        return None, None

    patterns = [
        r"(?:change|update)\s+(?:my\s+)?(name|email|phone)(?:\s+number)?(?:\s+to)?\s+(.+)$",
        r"^(name|email|phone)\s*[:\-]?\s+(.+)$",
    ]

    for pat in patterns:
        match = re.search(pat, msg, flags=re.IGNORECASE)
        if match:
            field = match.group(1).lower().strip()
            value = match.group(2).strip().strip('"\'').strip()
            return field, value

    return None, None


def _apply_field_update(state: AgentState, field: str, value: str) -> bool:
    """Apply a single field update if valid."""
    if not field or not value:
        return False

    if field == "name":
        if not re.fullmatch(r"[A-Za-z][A-Za-z\s\-']{1,40}", value):
            return False
        state.user_name = value.strip()
        return True

    if field == "email":
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            return False
        state.user_email = email
        return True

    if field == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) < 8:
            return False
        state.user_phone = value.strip()
        return True

    return False


def should_route_to_collection(state: AgentState) -> Literal["contact", "continue"]:
    """
    Check if should route to contact collection.
    Only route if user explicitly provided contact info, not for service discovery queries.
    """
    if (
        (state.contact_info_detected and state.question_type != "service_discovery")
        or state.question_type == "contact_request"
        or state.collecting_user_info
        or state.step in {"name", "email", "phone", "confirmation"}
    ):
        logger.info("[CONTACT] Contact info detected, routing to collection")
        return "contact"

    if state.question_type == "service_discovery":
        logger.info("[CONTACT] Service discovery query - NOT routing to contact collection")
        return "continue"

    return "continue"


def contact_collection_node(state: AgentState) -> AgentState:
    """
    Handle contact information collection.
    """
    logger.info("[CONTACT] Processing contact collection")

    user_message = state.messages[-1]["content"] if state.messages else ""
    msg_lower = user_message.lower().strip()

    if state.question_type == "contact_request" and state.user_name and state.user_email and state.user_phone:
        state.step = "confirmation"
        state.needs_info = None
        state.collecting_user_info = False
        state.final_response = _render_confirmation(
            state,
            "Too easy - before I connect you, can you confirm these details?",
        )
        return state

    if state.step == "confirmation":
        is_pure_yes = _is_yes(user_message) and not any(
            word in msg_lower for word in ["change", "update", "wrong", "incorrect", "different"]
        )

        if is_pure_yes:
            state.step = "complete"
            state.is_complete = True
            state.collecting_user_info = False
            state.needs_info = None
            state.final_response = "Thanks - confirmed. **Our team will contact you shortly.**"
            return state

        field, value = _extract_field_update(user_message)
        if field and value and _apply_field_update(state, field, value):
            logger.info("[CONTACT] Explicit update applied: %s=%s", field, value)
            state.final_response = _render_confirmation(state, "No worries - I have updated that.")
            return state

        updates = extract_contact_info(user_message, force_llm=True)
        updated_any = False
        if updates.get("name") and updates.get("name") != state.user_name:
            state.user_name = updates["name"]
            updated_any = True
        if updates.get("email") and updates.get("email") != state.user_email:
            state.user_email = updates["email"]
            updated_any = True
        if updates.get("phone") and updates.get("phone") != state.user_phone:
            state.user_phone = updates["phone"]
            updated_any = True

        if updated_any:
            state.final_response = _render_confirmation(state, "No worries - updated.")
            return state

        if msg_lower in {"name", "email", "phone"}:
            state.needs_info = msg_lower
            state.step = msg_lower
            current_value = {"name": state.user_name, "email": state.user_email, "phone": state.user_phone}.get(msg_lower)
            if current_value:
                state.final_response = f"No worries - what should I update your **{msg_lower}** to? (Current: {current_value})"
            else:
                state.final_response = f"No worries - what is your **{msg_lower}**?"
            return state

        state.final_response = (
            "Got it - tell me exactly what to change in one line, like:\n"
            "- \"change name to meteor\"\n"
            "- \"change email to meteor@example.com\"\n"
            "- \"change phone to 61400000000\""
        )
        return state

    state.collecting_user_info = True

    missing = []
    if not state.user_name:
        missing.append("name")
    if not state.user_email:
        missing.append("email")
    if not state.user_phone:
        missing.append("phone")

    if missing:
        state.needs_info = missing[0]
        state.step = missing[0]
        if state.needs_info == "name":
            state.final_response = "Too easy - what is your **name** and I will connect you with our team?"
        elif state.needs_info == "email":
            state.final_response = "Thanks - what is your **email** so our team can reach you?"
        elif state.needs_info == "phone":
            state.final_response = "Cheers - what is the best **phone number** for our team to call you on?"
    elif state.step in {"name", "email", "phone"}:
        updates = extract_contact_info(user_message, force_llm=True)

        if state.step == "name":
            if updates.get("name"):
                state.user_name = updates["name"]
            else:
                candidate = user_message.strip()
                if re.fullmatch(r"[A-Za-z][A-Za-z\s\-']{1,40}", candidate):
                    state.user_name = candidate
        elif state.step == "email" and updates.get("email"):
            state.user_email = updates["email"]
        elif state.step == "phone" and updates.get("phone"):
            state.user_phone = updates["phone"]

        if state.user_name and state.user_email and state.user_phone:
            state.step = "confirmation"
            state.needs_info = None
            state.final_response = _render_confirmation(
                state,
                "Too easy - before I connect you, can you confirm these details?",
            )
        else:
            missing = []
            if not state.user_name:
                missing.append("name")
            if not state.user_email:
                missing.append("email")
            if not state.user_phone:
                missing.append("phone")
            if missing:
                state.needs_info = missing[0]
                state.step = missing[0]
                if state.needs_info == "name":
                    state.final_response = "Thanks - what is your **name**?"
                elif state.needs_info == "email":
                    state.final_response = "Cheers - what is your **email**?"
                elif state.needs_info == "phone":
                    state.final_response = "Too easy - what is your **phone number**?"
    else:
        state.step = "complete"
        state.needs_info = None
        state.collecting_user_info = False
        state.is_complete = True
        state.final_response = "Thanks - I have got your details. **Our team will contact you shortly.**"

    return state
