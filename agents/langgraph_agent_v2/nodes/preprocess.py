"""
Preprocessing node - Parallel intent classification, contact extraction, and context analysis.
"""
import logging
import re
from typing import Dict
from concurrent.futures import ThreadPoolExecutor
from ..state import AgentState
from ..tools.llm import llm_call_json
from ..tools.contact_extraction import extract_contact_info
from ..config import MAX_PARALLEL_WORKERS

logger = logging.getLogger(__name__)

def _is_affirmative(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"yes", "y", "yep", "yeah", "sure", "ok", "okay", "please do", "sounds good", "go ahead"}

def _is_negative(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    # handle "no ..." sentences like "No can you just answer me here?"
    if t.startswith("no "):
        return True
    return t in {"no", "n", "nope", "nah", "not now", "later", "don't", "do not"}


def classify_intent(user_message: str, conversation_history: list) -> Dict:
    """Classify user intent using LLM."""
    # Fast-path: greetings / small-talk should never use RAG
    message_lower = user_message.lower().strip()
    greeting_phrases = [
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "how are you", "how's it going", "hows it going", "how are you going",
    ]
    if any(p == message_lower or p in message_lower for p in greeting_phrases):
        return {
            "intent": "greeting",
            "rag_query": None,
            "confidence": 0.95,
            "reasoning": "Detected greeting/small-talk"
        }

    # Quick check for common service discovery phrases
    service_discovery_phrases = [
        "surprise me", "what are my options", "what options", "what services", 
        "what can you", "what do you offer", "what do you have", "show me what",
        "tell me about", "what all", "what else", "what other"
    ]
    
    if any(phrase in message_lower for phrase in service_discovery_phrases):
        logger.info(f"[PREPROCESS] Detected service_discovery from phrase: {user_message[:50]}")
        return {
            "intent": "service_discovery",
            "rag_query": "WhipSmart services features capabilities offerings",
            "confidence": 0.9,
            "reasoning": "Detected service discovery phrase"
        }
    
    prompt = f"""
    Classify the user's message intent:
    
    Message: {user_message}
    Conversation History: {conversation_history[-3:] if len(conversation_history) > 3 else conversation_history}
    
    Classify as one of:
    - service_discovery: User asking "what are my options?", "what services do you offer?", "what can you help with?", "surprise me", "what do you have?"
    - domain_question: Questions about WhipSmart, novated leases, EVs, tax, benefits, etc.
    - vehicle_search: User wants to search for vehicles ("find me a car", "show me EVs under $X")
    - contact_request: User wants to connect with team ("I want to speak with someone", "connect me")
    - greeting: Greetings (hi, hello, hey, good morning)
    - goodbye: Thank you, goodbye, done, I'm finished
    - clarification_needed: Unclear intent (ONLY use if truly unclear)
    
    IMPORTANT: 
    - "surprise me", "what are my options", "what do you have" = service_discovery
    - Questions about services/offerings = service_discovery
    - Only use clarification_needed if the message is truly ambiguous
    
    For service_discovery, generate search query: "WhipSmart services features capabilities offerings"
    For domain_question, generate optimized RAG query based on the question.
    
    Return JSON: {{
        "intent": "...",
        "rag_query": "...",
        "confidence": 0.0-1.0,
        "reasoning": "..."
    }}
    """
    
    try:
        result = llm_call_json(prompt, temperature=0.2, max_tokens=300)
        
        # Post-process: if confidence is low and intent is clarification_needed, 
        # check if it might be service_discovery
        if result.get("intent") == "clarification_needed" and result.get("confidence", 1.0) < 0.7:
            if any(phrase in message_lower for phrase in ["what", "options", "services", "offer", "have", "surprise"]):
                logger.info(f"[PREPROCESS] Reclassifying clarification_needed -> service_discovery")
                result["intent"] = "service_discovery"
                result["rag_query"] = "WhipSmart services features capabilities offerings"
                result["confidence"] = 0.8
        
        return result
    except Exception as e:
        logger.error(f"[PREPROCESS] Intent classification failed: {str(e)}")
        # Fallback: if message contains "what" or "options", assume service_discovery
        if any(word in message_lower for word in ["what", "options", "services", "surprise"]):
            return {
                "intent": "service_discovery",
                "rag_query": "WhipSmart services features capabilities offerings",
                "confidence": 0.6,
                "reasoning": "Fallback: detected service discovery keywords"
            }
        return {
            "intent": "domain_question",
            "rag_query": user_message,
            "confidence": 0.5,
            "reasoning": "Fallback classification"
        }


def analyze_context(user_message: str, conversation_history: list) -> Dict:
    """Analyze conversation context using LLM."""
    prompt = f"""
    Analyze the conversation context:
    
    User Message: {user_message}
    Recent History: {conversation_history[-3:] if len(conversation_history) > 3 else conversation_history}
    
    Determine:
    1. What is the user responding to? (if "yes", what question?)
    2. Is the user correcting a previous mistake?
    3. What is the conversation flow?
    4. Any clarifications needed?
    
    Return JSON: {{
        "responding_to": "...",
        "is_correction": true/false,
        "conversation_flow": "...",
        "needs_clarification": true/false,
        "clarification_question": "..."
    }}
    """
    
    try:
        result = llm_call_json(prompt, temperature=0.3, max_tokens=300)
        return result
    except Exception as e:
        logger.error(f"[PREPROCESS] Context analysis failed: {str(e)}")
        return {
            "responding_to": "",
            "is_correction": False,
            "conversation_flow": "normal",
            "needs_clarification": False,
            "clarification_question": ""
        }


def preprocess_node(state: AgentState) -> AgentState:
    """
    Preprocess user message in parallel:
    1. Intent classification
    2. Contact info extraction
    3. Context analysis
    """
    user_message = state.messages[-1]["content"] if state.messages else ""
    conversation_history = state.messages[:-1] if len(state.messages) > 1 else []
    
    logger.info(f"[PREPROCESS] Processing message: {user_message[:50]}...")
    # Default: assume we won't use RAG unless knowledge node runs
    state.used_rag = False

    # If we're waiting for the user to confirm team connection, handle it deterministically
    if state.step == "awaiting_team_connection":
        # If they paste details without saying "yes", treat it as acceptance too.
        details = extract_contact_info(user_message, force_llm=True)
        if details.get("email") or details.get("phone") or details.get("name"):
            state.user_name = details.get("name") or state.user_name
            state.user_email = details.get("email") or state.user_email
            state.user_phone = details.get("phone") or state.user_phone
            logger.info("[PREPROCESS] Detected contact details while awaiting team connection - accepting")
            state.awaiting_team_connection_confirm = False
            state.question_type = "contact_request"
            state.rag_query = None
            state.context_analysis = {"team_connection": "accepted_via_details"}
            state.contact_info_detected = True
            return state

        if _is_affirmative(user_message):
            logger.info("[PREPROCESS] User accepted team connection offer")
            state.awaiting_team_connection_confirm = False
            state.question_type = "contact_request"
            state.rag_query = None
            state.context_analysis = {"team_connection": "accepted"}
            state.contact_info_detected = False
            return state
        # Any non-affirmative response is treated as "not now" so we can answer their question.
        # We'll re-offer gently later (postprocess).
        logger.info("[PREPROCESS] Team connection offer not accepted (continuing with answer)")
        state.awaiting_team_connection_confirm = False
        state.step = "chatting"
        # continue normal classification below
    
    # Parallel execution
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        intent_future = executor.submit(classify_intent, user_message, conversation_history)
        force_llm = bool(state.collecting_user_info or state.step in {"name", "email", "phone", "confirmation"})
        contact_future = executor.submit(extract_contact_info, user_message, force_llm)
        context_future = executor.submit(analyze_context, user_message, conversation_history)
        
        intent_result = intent_future.result()
        contact_result = contact_future.result()
        context_result = context_future.result()
    
    # Update state
    state.question_type = intent_result.get("intent", "domain_question")
    state.rag_query = intent_result.get("rag_query")
    state.context_analysis = context_result
    
    # Update contact info if detected - be very strict
    # Only set contact_info_detected if we have clear, valid contact information
    has_contact = False
    in_contact_flow = bool(state.collecting_user_info or state.step in {"name", "email", "phone", "confirmation"})
    
    if contact_result.get("name"):
        # Validate name is not a casual phrase
        name = contact_result["name"].strip()
        # During contact flow, accept lowercase names too (e.g., "jete")
        looks_like_name = bool(re.fullmatch(r"[A-Za-z][A-Za-z\s\-']{1,40}", name))
        if looks_like_name and name.lower() not in ["surprise", "me", "tell", "more", "yes", "no", "ok", "okay"]:
            state.user_name = name
            has_contact = True
    
    if contact_result.get("email"):
        email = contact_result["email"].strip()
        if "@" in email and "." in email.split("@")[-1]:
            state.user_email = email
            has_contact = True
    
    if contact_result.get("phone"):
        phone = contact_result["phone"].strip()
        digits = len([c for c in phone if c.isdigit()])
        if digits >= 8:
            state.user_phone = phone
            has_contact = True
    
    # Only set contact_info_detected if we have at least one valid contact field
    state.contact_info_detected = has_contact
    
    logger.info(f"[PREPROCESS] Intent: {state.question_type}, Contact detected: {state.contact_info_detected} (name={bool(state.user_name)}, email={bool(state.user_email)}, phone={bool(state.user_phone)})")
    
    return state
