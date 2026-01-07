"""
Agent nodes for LangGraph.
"""
import json
from openai import AzureOpenAI
from django.conf import settings
from agents.prompts import SYSTEM_PROMPT, FINAL_SYNTHESIS_PROMPT, VALIDATION_PROMPT, DECISION_MAKER_PROMPT
from agents.state import AgentState
from agents.utils import is_greeting, get_greeting_response
from chats.models import Session
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Initialize Azure OpenAI client
_client = None
_model = None


def _expand_query_for_rag(query: str) -> str:
    """
    Expand query to improve matching with knowledge base content.
    Adds related terms that are likely to appear in the knowledge base.
    """
    if not query:
        return query
    
    query_lower = query.lower()
    
    # Map user queries to expanded queries with related terms
    expansion_map = {
        "services": "services solutions customer approach platform",
        "platform": "platform services features website profile management",
        "features": "features platform services website profile",
        "whipsmart's services": "WhipSmart services solutions customer approach platform features",
        "whipsmart services": "WhipSmart services solutions customer approach platform features",
        "platform features": "platform features services website profile management",
    }
    
    # Check if query contains any key phrases that need expansion
    expanded_query = query
    for key_phrase, expansion in expansion_map.items():
        if key_phrase in query_lower:
            # Add expansion terms if not already present
            expansion_terms = expansion.split()
            existing_terms = set(query_lower.split())
            new_terms = [term for term in expansion_terms if term not in existing_terms]
            if new_terms:
                expanded_query = f"{query} {' '.join(new_terms)}"
                logger.info(f"[QUERY EXPANSION] Expanded query: '{query}' -> '{expanded_query}'")
            break
    
    return expanded_query


def _get_openai_client():
    """Initialize Azure OpenAI client (singleton)"""
    global _client, _model
    
    if _client is not None:
        return _client, _model
    
    api_key = getattr(settings, 'AZURE_OPENAI_API_KEY', None)
    endpoint = getattr(settings, 'AZURE_OPENAI_ENDPOINT', None)
    api_version = getattr(settings, 'AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
    deployment_name = getattr(settings, 'AZURE_OPENAI_DEPLOYMENT_NAME', 'gpt-4o')
    
    if not api_key or not endpoint:
        logger.error("Azure OpenAI credentials not configured in settings")
        return None, None
    
    try:
        _client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint
        )
        _model = deployment_name
        logger.info(f"Initialized Azure OpenAI client with deployment: {deployment_name}")
        return _client, _model
    except Exception as e:
        logger.error(f"Failed to initialize Azure OpenAI client: {str(e)}")
        return None, None


def decision_maker_node(state) -> AgentState:
    """
    Decision maker node: Analyzes user message and determines if tool assistance is needed.
    This is the first node that decides routing strategy.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState.from_dict(state)
    
    logger.info("=" * 80)
    logger.info(f"[DECISION] DECISION MAKER NODE - Analyzing User Message")
    
    # Extract user's last message
    user_message = ""
    for msg in reversed(state.messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    logger.info(f"[USER] User message: {user_message[:100]}...")
    
    # Quick check: if it's a greeting, handle directly
    if user_message and is_greeting(user_message):
        logger.info(f"[DECISION] Detected greeting - routing to final without tool")
        greeting_response = get_greeting_response(user_message)
        state.next_action = "final"
        state.tool_result = {
            "action": "final",
            "answer": greeting_response
        }
        state.last_activity = datetime.now()
        logger.info("=" * 80)
        return state.to_dict()
    
    client, model = _get_openai_client()
    if not client or not model:
        logger.error("[ERROR] OpenAI client not available")
        # Fallback: assume RAG search needed
        state.next_action = "rag"
        state.tool_result = {
            "action": "rag",
            "query": user_message
        }
        return state.to_dict()
    
    try:
        # Build conversation context
        recent_messages = state.messages[-4:] if len(state.messages) > 4 else state.messages
        conversation_context = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in recent_messages
        ])
        
        # Create decision prompt
        decision_prompt = DECISION_MAKER_PROMPT.format(
            user_message=user_message,
            conversation_context=conversation_context
        )
        
        logger.info("[PROC]  Analyzing message with decision maker...")
        
        # Get decision from LLM
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": decision_prompt}],
                response_format={"type": "json_object"},
                max_tokens=256,
                temperature=0.3  # Lower temperature for more consistent decisions
            )
            decision_text = response.choices[0].message.content.strip()
            decision_data = json.loads(decision_text)
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            logger.warning(f"JSON mode failed in decision maker: {str(e)}")
            # Fallback: use simple heuristics
            if any(word in user_message.lower() for word in ['car', 'vehicle', 'ev', 'tesla', 'find', 'search', 'available']):
                decision_data = {"needs_tool": True, "tool_type": "car", "reason": "Vehicle search detected"}
            elif any(word in user_message.lower() for word in ['what', 'how', 'why', 'when', 'where', 'explain', 'tell me']):
                decision_data = {"needs_tool": True, "tool_type": "rag", "query": user_message, "reason": "Question detected"}
            else:
                decision_data = {"needs_tool": False, "tool_type": "final", "reason": "Simple statement/greeting"}
        
        needs_tool = decision_data.get("needs_tool", True)
        tool_type = decision_data.get("tool_type", "rag")
        reason = decision_data.get("reason", "No reason provided")
        
        logger.info(f"[DECISION] Decision Made:")
        logger.info(f"  - Needs Tool: {needs_tool}")
        logger.info(f"  - Tool Type: {tool_type}")
        logger.info(f"  - Reason: {reason}")
        
        # Set up state based on decision
        if tool_type == "rag":
            query = decision_data.get("query") or user_message
            # Expand query for better matching with knowledge base
            query = _expand_query_for_rag(query)
            state.next_action = "rag"
            state.tool_result = {
                "action": "rag",
                "query": query
            }
            logger.info(f"  -> Routing to RAG search with query: {query[:50]}...")
        elif tool_type == "car":
            filters = decision_data.get("filters", {})
            state.next_action = "car"
            state.tool_result = {
                "action": "car",
                "filters": filters
            }
            logger.info(f"  -> Routing to car search with filters: {filters}")
        else:  # final
            direct_answer = decision_data.get("direct_answer")
            if direct_answer:
                state.next_action = "final"
                state.tool_result = {
                    "action": "final",
                    "answer": direct_answer
                }
                logger.info(f"  -> Routing to final with direct answer")
            else:
                # Generate appropriate response
                if is_greeting(user_message):
                    answer = get_greeting_response(user_message)
                else:
                    answer = f"I'm here to help you with WhipSmart's electric vehicle leasing services and novated leases. How can I assist you today?"
                state.next_action = "final"
                state.tool_result = {
                    "action": "final",
                    "answer": answer
                }
                logger.info(f"  -> Routing to final with generated response")
        
        state.last_activity = datetime.now()
        logger.info("=" * 80)
        return state.to_dict()
        
    except Exception as e:
        logger.error(f"Error in decision_maker_node: {str(e)}", exc_info=True)
        # Fallback: route to RAG search
        state.next_action = "rag"
        state.tool_result = {
            "action": "rag",
            "query": user_message
        }
        return state.to_dict()


def llm_node(state) -> AgentState:
    """
    Calls the LLM with system prompt + conversation in state.messages.
    Uses structured output to ensure JSON response with action and parameters.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState.from_dict(state)
    
    logger.info("=" * 80)
    logger.info(f"[LLM] LLM NODE - Processing")
    logger.info(f"[MSGS] Total messages in context: {len(state.messages)}")
    if state.messages:
        last_user_msg = next((msg.get("content", "")[:100] for msg in reversed(state.messages) if msg.get("role") == "user"), "N/A")
        logger.info(f"[USER] Last user message: {last_user_msg}...")
    logger.info("=" * 80)
    
    client, model = _get_openai_client()
    if not client or not model:
        logger.error("[ERROR] OpenAI client not available")
        state.next_action = "final"
        state.tool_result = {
            "action": "final",
            "answer": "I'm sorry, the AI service is currently unavailable. Please try again later."
        }
        return state.to_dict()
    
    try:
        # Build messages with system prompt
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += state.messages
        logger.info(f"[SEND] Sending {len(messages)} messages to LLM (including system prompt)")

        # Use JSON mode for structured output (compatible with OpenAI API)
        try:
            # Try using response_format with json_object (for newer models)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=512,
                temperature=0.7
            )
            text = response.choices[0].message.content.strip()
            action_data = json.loads(text)
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            # Fallback: use function calling for structured output
            logger.warning(f"JSON mode failed, using function calling: {str(e)}")
            functions = [
                {
                    "name": "agent_action",
                    "description": "Choose the action to take based on the user's query",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["rag", "car", "final"],
                                "description": "The action to take: rag for document search, car for vehicle search, final for direct answer"
                            },
                            "query": {
                                "type": "string",
                                "description": "Search query for RAG tool (required if action is 'rag')"
                            },
                            "filters": {
                                "type": "object",
                                "description": "Filters for car search (required if action is 'car')",
                                "properties": {
                                    "max_price": {"type": "number"},
                                    "min_price": {"type": "number"},
                                    "min_range": {"type": "number"},
                                    "max_range": {"type": "number"},
                                    "make": {"type": "string"},
                                    "model": {"type": "string"}
                                }
                            },
                            "answer": {
                                "type": "string",
                                "description": "Direct answer to user (required if action is 'final')"
                            }
                        },
                        "required": ["action"]
                    }
                }
            ]
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[{"type": "function", "function": func} for func in functions],
                tool_choice={"type": "function", "function": {"name": "agent_action"}},
                max_tokens=512,
                temperature=0.7
            )
            
            # Check for tool calls
            if response.choices[0].message.tool_calls:
                tool_call = response.choices[0].message.tool_calls[0]
                if tool_call.function.name == "agent_action":
                    action_data = json.loads(tool_call.function.arguments)
            else:
                # Last resort: try to parse as JSON from content
                text = response.choices[0].message.content.strip()
                action_data = json.loads(text)
        
        # Extract user's last message for potential use
        user_question = ""
        for msg in reversed(state.messages):
            if msg.get("role") == "user":
                user_question = msg.get("content", "")
                break
        
        # Check if message is a greeting or common statement - handle directly without RAG search
        if user_question and is_greeting(user_question):
            logger.info(f"[GREETING] Detected greeting/common statement: '{user_question[:50]}...'")
            greeting_response = get_greeting_response(user_question)
            state.next_action = "final"
            state.tool_result = {
                "action": "final",
                "answer": greeting_response
            }
            state.last_activity = datetime.now()
            logger.info(f"[GREETING] Responding with greeting message ({len(greeting_response)} characters)")
            logger.info("=" * 80)
            return state.to_dict()
        
        # Validate action data
        if action_data.get("action") == "rag":
            if not action_data.get("query"):
                logger.warning("RAG action missing query, using user's last message as query")
                if user_question:
                    action_data["query"] = user_question
                else:
                    action_data = {"action": "final", "answer": "I need more information to search. Could you clarify your question?"}
            else:
                # Expand query for better matching
                action_data["query"] = _expand_query_for_rag(action_data["query"])
        elif action_data.get("action") == "car" and not action_data.get("filters"):
            action_data["filters"] = {}
        elif action_data.get("action") == "final":
            # Check if it's a greeting - if so, keep the final action
            if user_question and is_greeting(user_question):
                logger.info("LLM chose 'final' for greeting - keeping final action")
                # Ensure answer is provided
                if not action_data.get("answer"):
                    action_data["answer"] = get_greeting_response(user_question)
            elif action_data.get("answer"):
                # If LLM provided an answer in final action, check if it's appropriate
                answer = action_data.get("answer", "").lower()
                # If answer looks like a greeting response or decline message, keep it
                if any(phrase in answer for phrase in ["hello", "hi", "whipsmart", "can help", "assist"]):
                    logger.info("LLM provided appropriate final answer - keeping it")
                else:
                    # Otherwise, redirect to RAG to check knowledge base
                    logger.warning("LLM chose 'final' action without clear answer, redirecting to RAG search")
                    if user_question:
                        query = _expand_query_for_rag(user_question)
                        action_data = {"action": "rag", "query": query}
                    else:
                        action_data = {"action": "rag", "query": "WhipSmart services"}
            else:
                # No answer provided, redirect to RAG
                logger.warning("LLM chose 'final' action without answer, redirecting to RAG search")
                if user_question:
                    query = _expand_query_for_rag(user_question)
                    action_data = {"action": "rag", "query": query}
                else:
                    action_data = {"action": "rag", "query": "WhipSmart services"}

        state.next_action = action_data.get("action")
        state.tool_result = action_data
        state.last_activity = datetime.now()
        
        # Track tool call
        if state.next_action != "final":
            state.tool_calls.append({
                "action": state.next_action,
                "timestamp": datetime.now().isoformat(),
                "parameters": action_data
            })
        
        logger.info("=" * 80)
        logger.info(f"[LLM] LLM NODE - Decision Made")
        logger.info(f"[INFO] Action Chosen: {state.next_action.upper()}")
        logger.info(f"[DATA] Action Data: {json.dumps(action_data, indent=2, ensure_ascii=False)}")
        if state.next_action == "rag":
            logger.info(f"[RAG] RAG Query: {action_data.get('query', 'N/A')}")
        elif state.next_action == "car":
            logger.info(f"[CAR] Car Filters: {json.dumps(action_data.get('filters', {}), indent=2, ensure_ascii=False)}")
        elif state.next_action == "final":
            logger.info(f"[TEXT] Direct Answer: {action_data.get('answer', 'N/A')[:100]}...")
        logger.info("=" * 80)
        return state.to_dict()

    except Exception as e:
        logger.error(f"Error in llm_node: {str(e)}", exc_info=True)
        # Fallback to final action with error message
        if isinstance(state, AgentState):
            state.next_action = "final"
            state.tool_result = {
                "action": "final",
                "answer": "I encountered an error processing your request. Please try again."
            }
            return state.to_dict()
        else:
            # If state is already a dict
            state["next_action"] = "final"
            state["tool_result"] = {
                "action": "final",
                "answer": "I encountered an error processing your request. Please try again."
            }
            return state


def router_node(state) -> str:
    """
    Router returns the next node name based on state.next_action.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState.from_dict(state)
    
    action = state.next_action or "final"
    logger.info("=" * 80)
    logger.info(f"[ROUTER] ROUTER NODE - Routing Decision")
    logger.info(f"[->] Routing to: {action.upper()} node")
    if action == "rag":
        logger.info("   -> Will search documents using RAG")
    elif action == "car":
        logger.info("   -> Will search for cars")
    else:
        logger.info("   -> Will generate final answer directly")
    logger.info("=" * 80)
    return action


def final_node(state) -> AgentState:
    """
    Final node: synthesize a user-facing answer using the previous tool result and conversation context.
    Returns updated state with final answer in messages.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState.from_dict(state)
    
    logger.info("=" * 80)
    logger.info(f"[FINAL] FINAL NODE - Synthesizing Answer")
    
    client, model = _get_openai_client()
    if not client or not model:
        logger.error("[ERROR] OpenAI client not available in final_node")
        error_msg = "I apologize, but I encountered an error while generating a response. Please try again."
        state.messages.append({"role": "assistant", "content": error_msg})
        state.last_activity = datetime.now()
        return state.to_dict()
    
    try:
        # Extract user's last question
        user_question = ""
        for msg in reversed(state.messages):
            if msg.get("role") == "user":
                user_question = msg.get("content", "")
                break

        logger.info(f"[Q] User Question: {user_question}")

        # Build context from recent messages (last 5 for context)
        recent_messages = state.messages[-6:] if len(state.messages) > 6 else state.messages
        conversation_context = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in recent_messages
        ])

        # Validate retrieved results for RAG queries
        has_relevant_results = False
        validation_result = None
        
        if isinstance(state.tool_result, dict):
            action = state.tool_result.get('action')
            
            if action == 'rag':
                results = state.tool_result.get('results', [])
                results_count = len(results)
                
                # Check if results are empty
                if results_count == 0:
                    logger.info(f"[WARN]  No RAG results found for query")
                    has_relevant_results = False
                else:
                    # Validate retrieved content using LLM
                    logger.info(f"[VALIDATE] Validating {results_count} retrieved results...")
                    
                    # Prepare content for validation
                    retrieved_texts = []
                    scores = []
                    for r in results:
                        if isinstance(r, dict):
                            text = r.get('text', '')[:500]  # Limit text length for validation
                            score = r.get('score', 0.0)
                            retrieved_texts.append(f"Score: {score:.4f}\n{text}")
                            scores.append(score)
                    
                    retrieved_content = "\n\n---\n\n".join(retrieved_texts)
                    scores_str = ", ".join([f"{s:.4f}" for s in scores])
                    max_score = max(scores) if scores else 0.0
                    
                    # Run validation using LLM
                    try:
                        validation_prompt = VALIDATION_PROMPT.format(
                            user_question=user_question,
                            retrieved_content=retrieved_content[:3000],  # Limit content length
                            scores=scores_str
                        )
                        
                        validation_response = client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": validation_prompt}],
                            response_format={"type": "json_object"},
                            max_tokens=256,
                            temperature=0.3  # Lower temperature for more consistent validation
                        )
                        
                        validation_text = validation_response.choices[0].message.content.strip()
                        validation_result = json.loads(validation_text)
                        
                        is_suitable = validation_result.get('is_suitable', False)
                        reason = validation_result.get('reason', 'No reason provided')
                        relevance_score = validation_result.get('relevance_score', max_score)
                        has_sufficient_info = validation_result.get('has_sufficient_info', False)
                        
                        logger.info(f"[VALIDATE] Validation Result:")
                        logger.info(f"  - Suitable: {is_suitable}")
                        logger.info(f"  - Reason: {reason}")
                        logger.info(f"  - Relevance Score: {relevance_score:.4f}")
                        logger.info(f"  - Has Sufficient Info: {has_sufficient_info}")
                        
                        # Consider results suitable if validation passes OR if score is reasonable
                        # Be more lenient: accept if validation passes OR if score is decent (>= 0.35)
                        # This ensures we don't reject valid results due to overly strict validation
                        score_threshold = 0.35  # Lowered from 0.5 to be more lenient
                        has_relevant_results = (
                            (is_suitable and has_sufficient_info) or 
                            (relevance_score >= score_threshold and is_suitable)
                        )
                        
                        if not has_relevant_results:
                            logger.info(f"[WARN]  Validation failed or low relevance - will decline to answer")
                            logger.info(f"  - Validation suitable: {is_suitable}")
                            logger.info(f"  - Sufficient info: {has_sufficient_info}")
                            logger.info(f"  - Score threshold: {relevance_score >= 0.5}")
                    except Exception as e:
                        logger.error(f"[ERROR] Validation failed: {str(e)}")
                        # Fallback to score-based validation (more lenient threshold)
                        max_score = max(scores) if scores else 0.0
                        logger.info(f"[FALLBACK] Using score-based validation: {max_score:.4f}")
                        # Lowered threshold from 0.5 to 0.35 to be more lenient
                        has_relevant_results = max_score >= 0.35
                        
            elif action == 'car':
                results_count = len(state.tool_result.get('results', []))
                logger.info(f"[CAR] Car Results: {results_count} cars found")
                has_relevant_results = results_count > 0
        
        # Format tool result for synthesis
        tool_result_str = json.dumps(state.tool_result, indent=2, ensure_ascii=False)
        
        logger.info("[PROC]  Generating final synthesized answer...")

        # Get user name from session for personalization
        user_name = ""
        first_name = ""
        try:
            session = Session.objects.filter(id=state.session_id).first()
            if session and session.conversation_data:
                user_name = session.conversation_data.get('name', '')
                if user_name:
                    # Extract first name only (more natural in conversation)
                    first_name = user_name.strip().split()[0] if user_name.strip() else ""
                    logger.info(f"[PERSONALIZATION] Found user name: {user_name}, using first name: {first_name}")
        except Exception as e:
            logger.warning(f"[PERSONALIZATION] Could not get user name: {str(e)}")

        # Use first name for personalization (more natural than full name)
        name_to_use = first_name if first_name else (user_name if user_name else "Not provided")

        # Create synthesis prompt with enhanced instructions for no-answer scenarios
        synthesis_prompt = FINAL_SYNTHESIS_PROMPT.format(
            tool_result=tool_result_str,
            conversation_context=conversation_context,
            user_question=user_question,
            user_name=name_to_use
        )
        
        # If no relevant results found or validation failed, enhance the prompt with specific instructions
        if not has_relevant_results and isinstance(state.tool_result, dict) and state.tool_result.get('action') == 'rag':
            validation_info = ""
            if validation_result:
                validation_info = f"\nValidation Reason: {validation_result.get('reason', 'Not provided')}"
            
            synthesis_prompt += f"""
            
CRITICAL: The retrieved knowledge base content has been reviewed and validated. The validation determined that the content is NOT suitable to answer the user's question.{validation_info}

This means we do NOT have appropriate information about the user's question in our WhipSmart knowledge base.

YOU MUST DECLINE TO ANSWER AND RESPOND WITH THIS EXACT MESSAGE:

"I'm sorry, but I don't have information about that topic in my knowledge base. I can only help with questions about WhipSmart's electric vehicle leasing services, novated leases, and related topics.

Here are some topics I can help you with:
- Electric vehicle (EV) leasing options and processes
- Novated leases and how they work
- Tax implications and benefits of leasing (including FBT exemptions)
- Vehicle selection and availability
- Leasing terms, conditions, and policies
- Pricing, payments, and running costs
- End-of-lease options and residual payments
- WhipSmart's services and platform features

Please feel free to ask me about any of these topics! 😊"

DO NOT attempt to answer the question using general knowledge. DO NOT try to be helpful by answering anyway. ONLY suggest topics we can help with.
"""

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": synthesis_prompt}],
            max_tokens=512,  # Reduced from 1024 to encourage concise responses
            temperature=0.7
        )

        final_answer = response.choices[0].message.content.strip()
        
        # Update state with final answer
        state.messages.append({"role": "assistant", "content": final_answer})
        state.last_activity = datetime.now()
        
        logger.info("=" * 80)
        logger.info(f"[FINAL] FINAL NODE - Answer Synthesized")
        logger.info(f"[MSG] Final Answer ({len(final_answer)} characters):")
        logger.info(f"{final_answer}")
        logger.info("=" * 80)
        return state.to_dict()

    except Exception as e:
        logger.error(f"Error in final_node: {str(e)}", exc_info=True)
        # Add error message to state
        error_msg = "I apologize, but I encountered an error while generating a response. Please try again."
        if isinstance(state, AgentState):
            state.messages.append({"role": "assistant", "content": error_msg})
            state.last_activity = datetime.now()
            return state.to_dict()
        else:
            # If state is already a dict
            state["messages"].append({"role": "assistant", "content": error_msg})
            state["last_activity"] = datetime.now().isoformat()
            return state

