"""
Response generation node.
"""
import logging
from typing import Optional
from ..state import AgentState
from ..tools.llm import llm_call
from ..prompts.system import build_system_prompt
from ..config import LLM_TEMPERATURE_RESPONSE, LLM_MAX_TOKENS_RESPONSE

logger = logging.getLogger(__name__)


def assemble_generation_prompt(
    user_question: str,
    rag_context: list,
    reasoning_output: dict,
    user_name: Optional[str],
    conversation_history: list,
    system_prompt: str,
    question_type: str = "domain_question"
) -> str:
    """Assemble comprehensive generation prompt."""
    # Format RAG context
    rag_text = ""
    if rag_context:
        for i, chunk in enumerate(rag_context[:5], 1):
            content = chunk.get("content", "")
            url = chunk.get("metadata", {}).get("url", "")
            rag_text += f"\n[Source {i}]\n{content}\n"
            if url:
                rag_text += f"Source: {url}\n"
    
    # Format reasoning outputs
    intent_analysis = reasoning_output.get("intent", {})
    structure_plan = reasoning_output.get("structure", {})
    coverage_plan = reasoning_output.get("coverage", {})
    
    # Special handling for service discovery
    if question_type == "service_discovery":
        special_instructions = """
CRITICAL: This is a SERVICE DISCOVERY query. The user is asking "what are my options?" or "what services do you offer?"
- DO NOT talk about lease options or end-of-lease choices
- DO NOT assume they're asking about novated lease options
- Provide a structured list of WhipSmart's SERVICES and FEATURES
- List what WhipSmart offers (vehicle search, lease application, quotes, consultation, etc.)
- Use the knowledge base context to find information about WhipSmart services
"""
    else:
        special_instructions = ""
    
    prompt = f"""
{system_prompt}

USER QUESTION: {user_question}
QUESTION TYPE: {question_type}

{special_instructions}

KNOWLEDGE BASE CONTEXT:
{rag_text if rag_text else "No relevant context found."}

REASONING OUTPUTS:
- Required Depth: {intent_analysis.get('required_depth', 'medium')}
- Key Dimensions: {', '.join(intent_analysis.get('key_dimensions', []))}
- Structure: {structure_plan.get('structure', 'bullets')}
- Ideal Length: {structure_plan.get('ideal_length', 4)} key points
- Must Include: {', '.join(coverage_plan.get('must_include', []))}

CONVERSATION HISTORY:
{chr(10).join([f"{msg.get('role', 'user')}: {msg.get('content', '')[:100]}" for msg in conversation_history[-3:]])}

INSTRUCTIONS:
1. Generate a response following the structure plan
2. Cover all topics in the "must include" list
3. Use knowledge base context accurately - cite sources with URLs
4. Keep answer concise ({structure_plan.get('ideal_length', 4)} key points)
5. Use markdown formatting (bold, headings, lists)
6. Use single \\n for line breaks, \\n\\n for paragraph separation
7. Address user by name if provided: {user_name or 'Not provided'}
8. NO follow-up phrases - just the answer
9. DO NOT ask for contact information unless user explicitly wants to connect

Generate the response now:"""
    
    return prompt


def response_generation_node(state: AgentState) -> AgentState:
    """
    Generate response using all reasoning outputs.
    """
    user_question = state.messages[-1]["content"] if state.messages else ""
    rag_context = state.rag_context
    reasoning = state.reasoning_output or {}
    conversation_history = state.messages[:-1] if len(state.messages) > 1 else []
    question_type = state.question_type or "domain_question"
    
    logger.info(f"[GENERATION] Generating response for question type: {question_type}")
    
    # Build system prompt
    system_prompt = build_system_prompt(
        name=state.user_name,
        email=state.user_email,
        phone=state.user_phone,
        step=state.step
    )
    
    # Assemble generation prompt
    generation_prompt = assemble_generation_prompt(
        user_question=user_question,
        rag_context=rag_context,
        reasoning_output=reasoning,
        user_name=state.user_name,
        conversation_history=conversation_history,
        system_prompt=system_prompt,
        question_type=question_type
    )
    
    # Generate response
    try:
        response = llm_call(
            prompt=generation_prompt,
            temperature=LLM_TEMPERATURE_RESPONSE,
            max_tokens=LLM_MAX_TOKENS_RESPONSE
        )
        
        state.draft_response = response
        state.last_assistant_message = response
        
        logger.info(f"[GENERATION] Generated response ({len(response)} chars)")
        
    except Exception as e:
        logger.error(f"[GENERATION] Failed: {str(e)}", exc_info=True)
        state.draft_response = "I apologize, but I encountered an error generating a response. Please try again."
    
    return state
