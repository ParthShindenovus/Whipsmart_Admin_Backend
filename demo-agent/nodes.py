import json
from openai import AzureOpenAI
from app.config import Config
from app.agent.prompts import SYSTEM_PROMPT, FINAL_SYNTHESIS_PROMPT
from app.agent.state import AgentState
from app.utils.logger import logger
from datetime import datetime

client = AzureOpenAI(
    api_key=Config.AZURE_OPENAI_API_KEY,
    api_version=Config.AZURE_OPENAI_API_VERSION,
    azure_endpoint=Config.AZURE_OPENAI_ENDPOINT
)
MODEL = Config.AZURE_OPENAI_DEPLOYMENT_NAME

def llm_node(state) -> AgentState:
    """
    Calls the LLM with system prompt + conversation in state.messages.
    Uses structured output to ensure JSON response with action and parameters.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState(**state)
    
    try:
        # Build messages with system prompt
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += state.messages

        # Use JSON mode for structured output (compatible with OpenAI API)
        try:
            # Try using response_format with json_object (for newer models)
            response = client.chat.completions.create(
                model=MODEL,
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
                model=MODEL,
                messages=messages,
                functions=functions,
                function_call={"name": "agent_action"},
                max_tokens=512,
                temperature=0.7
            )
            function_call = response.choices[0].message.function_call
            if function_call and function_call.name == "agent_action":
                action_data = json.loads(function_call.arguments)
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
        
        logger.info(f"LLM node: action={state.next_action}")
        return state

    except Exception as e:
        logger.error(f"Error in llm_node: {str(e)}")
        # Fallback to final action with error message
        state.next_action = "final"
        state.tool_result = {
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
        state = AgentState(**state)
    
    action = state.next_action or "final"
    logger.info(f"Router: routing to {action}")
    return action

def final_node(state) -> AgentState:
    """
    Final node: synthesize a user-facing answer using the previous tool result and conversation context.
    Returns updated state with final answer in messages.
    """
    # Handle dict input from LangGraph
    if isinstance(state, dict):
        state = AgentState(**state)
    
    try:
        # Extract user's last question
        user_question = ""
        for msg in reversed(state.messages):
            if msg.get("role") == "user":
                user_question = msg.get("content", "")
                break

        # Build context from recent messages (last 5 for context)
        recent_messages = state.messages[-6:] if len(state.messages) > 6 else state.messages
        conversation_context = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in recent_messages
        ])

        # Format tool result for synthesis
        tool_result_str = json.dumps(state.tool_result, indent=2, ensure_ascii=False)

        # Create synthesis prompt
        synthesis_prompt = FINAL_SYNTHESIS_PROMPT.format(
            tool_result=tool_result_str,
            conversation_context=conversation_context,
            user_question=user_question
        )

        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": synthesis_prompt}],
            max_tokens=1024,
            temperature=0.7
        )

        final_answer = response.choices[0].message.content.strip()
        
        # Update state with final answer
        state.messages.append({"role": "assistant", "content": final_answer})
        state.last_activity = datetime.now()
        
        logger.info("Final node: answer synthesized")
        return state

    except Exception as e:
        logger.error(f"Error in final_node: {str(e)}")
        # Add error message to state
        error_msg = "I apologize, but I encountered an error while generating a response. Please try again."
        state.messages.append({"role": "assistant", "content": error_msg})
        state.last_activity = datetime.now()
        return state

