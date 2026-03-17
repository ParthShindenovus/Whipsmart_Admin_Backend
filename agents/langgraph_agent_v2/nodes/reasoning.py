"""
Reasoning node - Parallel multi-agent reasoning.
"""
import logging
from typing import Dict
from concurrent.futures import ThreadPoolExecutor
from ..state import AgentState
from ..tools.llm import llm_call_json
from ..config import MAX_PARALLEL_WORKERS, LLM_TEMPERATURE_REASONING

logger = logging.getLogger(__name__)


def analyze_intent_deep(user_question: str, rag_context: list, conversation_history: list) -> Dict:
    """Deep intent analysis."""
    prompt = f"""
    Analyze the user's question in depth:
    
    Question: {user_question}
    Available Context: {len(rag_context)} knowledge base chunks
    Conversation History: {conversation_history[-3:] if len(conversation_history) > 3 else conversation_history}
    
    Determine:
    1. Required depth (short, medium, detailed)
    2. Key dimensions to cover (financial, operational, customer experience)
    3. Answer structure needs
    
    Return JSON: {{
        "required_depth": "short"|"medium"|"detailed",
        "key_dimensions": ["..."],
        "structure_needs": "..."
    }}
    """
    
    try:
        return llm_call_json(prompt, temperature=LLM_TEMPERATURE_REASONING, max_tokens=500)
    except Exception as e:
        logger.error(f"[REASONING] Intent analysis failed: {str(e)}")
        return {
            "required_depth": "medium",
            "key_dimensions": [],
            "structure_needs": "bullets"
        }


def plan_structure(user_question: str, question_type: str) -> Dict:
    """Plan answer structure."""
    prompt = f"""
    Plan the answer structure for this question:
    
    Question: {user_question}
    Question Type: {question_type}
    
    Determine:
    1. Best structure (bullets, sections, lifecycle, comparison)
    2. Ideal length (number of key points)
    3. Information ordering
    
    Return JSON: {{
        "structure": "bullets"|"sections"|"lifecycle"|"comparison",
        "ideal_length": 4,
        "ordering": "..."
    }}
    """
    
    try:
        return llm_call_json(prompt, temperature=LLM_TEMPERATURE_REASONING, max_tokens=300)
    except Exception as e:
        logger.error(f"[REASONING] Structure planning failed: {str(e)}")
        return {
            "structure": "bullets",
            "ideal_length": 4,
            "ordering": "importance"
        }


def define_coverage(user_question: str, rag_context: list, question_type: str) -> Dict:
    """Define what must be covered."""
    prompt = f"""
    Define what MUST be covered in the answer:
    
    Question: {user_question}
    Question Type: {question_type}
    Available Context: {len(rag_context)} knowledge base chunks
    
    List:
    1. MUST INCLUDE topics
    2. OPTIONAL topics (if context supports)
    3. EXCLUDE (fluff, speculation)
    
    Return JSON: {{
        "must_include": ["..."],
        "optional": ["..."],
        "exclude": ["..."]
    }}
    """
    
    try:
        return llm_call_json(prompt, temperature=LLM_TEMPERATURE_REASONING, max_tokens=500)
    except Exception as e:
        logger.error(f"[REASONING] Coverage definition failed: {str(e)}")
        return {
            "must_include": [],
            "optional": [],
            "exclude": []
        }


def reasoning_node(state: AgentState) -> AgentState:
    """
    Parallel multi-agent reasoning:
    1. Intent analyzer
    2. Structure planner
    3. Coverage definer
    """
    user_question = state.messages[-1]["content"] if state.messages else ""
    rag_context = state.rag_context
    conversation_history = state.messages[:-1] if len(state.messages) > 1 else []
    question_type = state.question_type or "domain_question"
    
    logger.info("[REASONING] Starting parallel reasoning")
    
    # Parallel execution
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        intent_future = executor.submit(
            analyze_intent_deep, user_question, rag_context, conversation_history
        )
        structure_future = executor.submit(plan_structure, user_question, question_type)
        coverage_future = executor.submit(define_coverage, user_question, rag_context, question_type)
        
        intent_analysis = intent_future.result()
        structure_plan = structure_future.result()
        coverage_plan = coverage_future.result()
    
    # Combine reasoning outputs
    state.reasoning_output = {
        "intent": intent_analysis,
        "structure": structure_plan,
        "coverage": coverage_plan
    }
    
    logger.info("[REASONING] Reasoning complete")
    
    return state
