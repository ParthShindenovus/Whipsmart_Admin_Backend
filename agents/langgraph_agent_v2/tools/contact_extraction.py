"""
Contact information extraction tools for LangGraph Agent V2.
"""
import re
import logging
from typing import Dict, Optional
from .llm import llm_call_json

logger = logging.getLogger(__name__)


def extract_with_llm(message: str, force: bool = False) -> Dict[str, Optional[str]]:
    """
    Extract contact information using LLM.
    VERY STRICT - only extract if explicitly present.
    
    Args:
        message: User message
    
    Returns:
        Dictionary with name, email, phone (or None)
    """
    # First check if message even looks like it could contain contact info
    message_lower = message.lower().strip()
    
    # Reject common casual phrases immediately
    casual_phrases = [
        "surprise me", "tell me", "what are", "what is", "how do", "why", "when", "where",
        "yes", "no", "ok", "okay", "thanks", "thank you", "please", "help", "hello", "hi", "hey"
    ]
    
    if (not force) and any(phrase in message_lower for phrase in casual_phrases):
        # Very likely not contact info - skip LLM call
        logger.info(f"[CONTACT] Skipping LLM extraction for casual phrase: {message[:30]}")
        return {"name": None, "email": None, "phone": None}
    
    prompt = f"""
Extract contact information from the following message. BE STRICT and return ONLY what is explicitly present.

You may see contact details in many formats, including comma-separated like:
- "jete, jete@yopmail.com, 61411372823"

CRITICAL RULES:
1) name:
   - Extract if the user provides a name explicitly OR provides it as a standalone name token near their email/phone.
   - Accept lowercase names.
   - Do NOT guess a name from unrelated text.

2) email:
   - Extract ONLY if an actual email address appears (must contain '@' and a domain).

3) phone:
   - Extract ONLY if a phone number appears with at least 8 digits (may include spaces, +, etc).

Message: \"{message}\"

If no explicit contact info is present, return null for all fields.

Return JSON ONLY:
{{"name": string|null, "email": string|null, "phone": string|null}}
"""
    
    try:
        result = llm_call_json(
            prompt=prompt,
            temperature=0.1,  # Very low temperature for strict extraction
            max_tokens=150
        )
        
        # Additional strict validation
        name = result.get("name")
        email = result.get("email")
        phone = result.get("phone")
        
        # Validate name - reject if it's a common word
        if name:
            name_lower = name.lower().strip()
            if name_lower in ["surprise", "me", "tell", "more", "what", "how", "why", "when", "where", 
                             "yes", "no", "ok", "okay", "thanks", "thank", "you", "please", "help"]:
                name = None
            # Reject if name is too long (likely not a name)
            if len(name.split()) > 3:
                name = None
        
        # Validate email - must have @
        if email and "@" not in email:
            email = None
        
        # Validate phone - must have digits
        if phone:
            digits = re.sub(r'\D', '', phone)
            if len(digits) < 8:
                phone = None
        
        return {
            "name": name,
            "email": email,
            "phone": phone
        }
    except Exception as e:
        logger.warning(f"[CONTACT] LLM extraction failed: {str(e)}")
        return {"name": None, "email": None, "phone": None}


def extract_contact_info(message: str, force_llm: bool = False) -> Dict[str, Optional[str]]:
    """
    Extract contact information using LLM only.
    We intentionally avoid regex to keep behaviour consistent and avoid false positives.
    
    Args:
        message: User message
    
    Returns:
        Dictionary with name, email, phone (or None)
    """
    message_stripped = message.strip()
    message_lower = message_stripped.lower()

    # Call LLM if:
    # - forced (during contact flow), OR
    # - message contains strong signals of contact info (email / digits / separators)
    has_email_signal = "@" in message_stripped
    has_phone_signal = len(re.sub(r"\D", "", message_stripped)) >= 8
    has_separator_signal = any(sep in message_stripped for sep in [",", ";"])
    should_use_llm = bool(force_llm or has_email_signal or has_phone_signal or has_separator_signal)

    if not should_use_llm:
        return {"name": None, "email": None, "phone": None}

    result = extract_with_llm(message, force=True if force_llm else False)
    
    # Final strict validation
    if result["email"] and "@" not in result["email"]:
        result["email"] = None
    
    if result["phone"]:
        # Remove spaces and validate
        digits = re.sub(r'\D', '', result["phone"])
        if len(digits) < 8:
            result["phone"] = None
    
    # For name, be extra strict - must look like a real name
    name_val = result.get("name")
    if isinstance(name_val, str) and name_val.strip():
        name_val = name_val.strip()
        name_lower = name_val.lower()
        # Reject common words/phrases
        common_words = [
            "surprise", "me", "tell", "more", "what", "how", "why", "when", "where",
            "yes", "no", "ok", "okay", "thanks", "thank", "you", "please", "help",
            "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
        ]
        if name_lower in common_words:
            result["name"] = None
        # Reject if too long (likely not a name)
        elif len(name_val.split()) > 3:
            result["name"] = None
        # Reject if it's the entire message and message is a question/casual phrase
        elif name_lower == message_lower and any(q in message_lower for q in ["?", "what", "how", "why", "tell", "surprise"]):
            result["name"] = None
        else:
            result["name"] = name_val
    else:
        result["name"] = None
    
    # Only return contact info if at least one field is valid
    # But be strict - don't return false positives
    if not (result["name"] or result["email"] or result["phone"]):
        return {"name": None, "email": None, "phone": None}
    
    logger.info(f"[CONTACT] Extracted - name: {bool(result['name'])}, email: {bool(result['email'])}, phone: {bool(result['phone'])}")
    
    return result
