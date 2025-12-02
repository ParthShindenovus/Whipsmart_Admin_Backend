"""
Agent nodes for LangGraph.
"""
import json
from openai import AzureOpenAI
from django.conf import settings
from agents.prompts import SYSTEM_PROMPT, FINAL_SYNTHESIS_PROMPT
from agents.state import AgentState
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Initialize Azure OpenAI client
_client = None
_model = None


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
        
        # Validate action data
        if action_data.get("action") == "rag" and not action_data.get("query"):
            logger.warning("RAG action missing query, defaulting to final")
            action_data = {"action": "final", "answer": "I need more information to search. Could you clarify your question?"}
        elif action_data.get("action") == "car" and not action_data.get("filters"):
            action_data["filters"] = {}
        elif action_data.get("action") == "final" and not action_data.get("answer"):
            action_data["answer"] = "I'm here to help! Could you provide more details about what you're looking for?"

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

        # Format tool result for synthesis
        tool_result_str = json.dumps(state.tool_result, indent=2, ensure_ascii=False)
        
        logger.info(f"[TOOL] Tool Result Type: {state.tool_result.get('action') if isinstance(state.tool_result, dict) else 'N/A'}")
        if isinstance(state.tool_result, dict):
            if state.tool_result.get('action') == 'rag':
                results_count = len(state.tool_result.get('results', []))
                logger.info(f"[DOCS] RAG Results: {results_count} documents found")
            elif state.tool_result.get('action') == 'car':
                results_count = len(state.tool_result.get('results', []))
                logger.info(f"[CAR] Car Results: {results_count} cars found")
        
        logger.info("[PROC]  Generating final synthesized answer...")

        # Create synthesis prompt
        synthesis_prompt = FINAL_SYNTHESIS_PROMPT.format(
            tool_result=tool_result_str,
            conversation_context=conversation_context,
            user_question=user_question
        )

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": synthesis_prompt}],
            max_tokens=1024,
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

