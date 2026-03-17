"""
Validation node - Multi-layer LLM-based validation.
"""
import logging
from typing import Literal, Dict
from concurrent.futures import ThreadPoolExecutor
from ..state import AgentState
from ..tools.llm import llm_call_json
from ..prompts.validation import VALIDATION_PROMPTS
from ..config import MAX_PARALLEL_WORKERS, MAX_VALIDATION_RETRIES, VALIDATION_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)


def validate_facts(draft_response: str, rag_context: list) -> Dict:
    """Validate facts against RAG context."""
    rag_text = "\n".join([chunk.get("content", "")[:500] for chunk in rag_context[:3]])
    
    prompt = VALIDATION_PROMPTS["fact_check"].format(
        draft_response=draft_response,
        rag_context=rag_text
    )
    
    try:
        return llm_call_json(prompt, temperature=0.3, max_tokens=300)
    except Exception as e:
        logger.error(f"[VALIDATION] Fact check failed: {str(e)}")
        return {"valid": True, "issues": [], "confidence": 0.5}


def validate_completeness(draft_response: str, coverage_plan: dict, user_question: str) -> Dict:
    """Validate completeness."""
    prompt = VALIDATION_PROMPTS["completeness"].format(
        draft_response=draft_response,
        coverage_plan=coverage_plan,
        user_question=user_question
    )
    
    try:
        return llm_call_json(prompt, temperature=0.3, max_tokens=300)
    except Exception as e:
        logger.error(f"[VALIDATION] Completeness check failed: {str(e)}")
        return {"valid": True, "missing_topics": [], "completeness_score": 0.5}


def validate_tone(draft_response: str) -> Dict:
    """Validate tone."""
    prompt = VALIDATION_PROMPTS["tone"].format(draft_response=draft_response)
    
    try:
        return llm_call_json(prompt, temperature=0.3, max_tokens=300)
    except Exception as e:
        logger.error(f"[VALIDATION] Tone check failed: {str(e)}")
        return {"valid": True, "tone_issues": [], "tone_score": 0.5}


def validation_node(state: AgentState) -> AgentState:
    """
    Multi-layer LLM-based validation.
    """
    draft_response = state.draft_response or ""
    rag_context = state.rag_context
    coverage_plan = state.reasoning_output.get("coverage", {}) if state.reasoning_output else {}
    user_question = state.messages[-1]["content"] if state.messages else ""
    
    logger.info("[VALIDATION] Starting validation")
    
    # Parallel validation
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        fact_future = executor.submit(validate_facts, draft_response, rag_context)
        completeness_future = executor.submit(validate_completeness, draft_response, coverage_plan, user_question)
        tone_future = executor.submit(validate_tone, draft_response)
        
        fact_check = fact_future.result()
        completeness_check = completeness_future.result()
        tone_check = tone_future.result()
    
    # Combine validation results
    confidence = min(
        fact_check.get("confidence", 0.5),
        completeness_check.get("completeness_score", 0.5),
        tone_check.get("tone_score", 0.5)
    )

    overall_valid = all([
        fact_check.get("valid", False),
        completeness_check.get("valid", False),
        tone_check.get("valid", False)
    ])

    validation_result = {
        "fact_check": fact_check,
        "completeness": completeness_check,
        "tone": tone_check,
        "overall_valid": overall_valid,
        "confidence": confidence,
        # decision hint computed here because state mutations in the conditional edge function
        # are not guaranteed to persist in LangGraph
        "should_retry": False,
    }
    
    state.validation_result = validation_result
    
    if not validation_result["overall_valid"]:
        # Generate improvement suggestions
        issues = []
        if not fact_check.get("valid"):
            issues.extend(fact_check.get("issues", []))
        if not completeness_check.get("valid"):
            issues.extend(completeness_check.get("missing_topics", []))
        if not tone_check.get("valid"):
            issues.extend(tone_check.get("tone_issues", []))
        
        state.improvement_suggestions = issues
        logger.warning(f"[VALIDATION] Validation failed: {issues}")

        # Retry ONLY when we detect likely hallucination/fact issues.
        # Do not retry for generic completeness complaints (it can loop and waste tokens).
        should_retry_for_facts = (fact_check.get("valid") is False)
        if should_retry_for_facts and confidence < VALIDATION_CONFIDENCE_THRESHOLD and state.validation_retry_count < MAX_VALIDATION_RETRIES:
            state.validation_retry_count += 1
            validation_result["should_retry"] = True
            logger.info(f"[VALIDATION] Retrying (attempt {state.validation_retry_count})")
    else:
        logger.info("[VALIDATION] Validation passed")
    
    return state


def validation_decision(state: AgentState) -> Literal["retry", "continue"]:
    """
    Decide if should retry generation or continue.
    """
    validation_result = state.validation_result
    if not validation_result:
        return "continue"
    
    # Read-only decision. Retry count is incremented in validation_node().
    if validation_result.get("should_retry") is True:
        return "retry"

    if state.validation_retry_count >= MAX_VALIDATION_RETRIES:
        logger.warning("[VALIDATION] Max retries reached, continuing anyway")

    return "continue"
