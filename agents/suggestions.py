"""
Utility functions for generating contextual suggestion questions.
"""
from openai import AzureOpenAI
from django.conf import settings
import json
import logging

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


SUGGESTIONS_PROMPT = """You are generating contextual suggestion questions for a chat interface. These are quick-reply buttons that users can click to continue the conversation.

Conversation Context:
{conversation_context}

Last Bot Message:
{last_bot_message}

INSTRUCTIONS:
1. Generate 3-5 short, relevant suggestion questions based on the conversation context
2. Suggestions should be:
   - Short (max 10-12 words each)
   - Contextually relevant to the last bot message and conversation
   - Natural follow-up questions or related topics
   - Specific to WhipSmart's EV leasing services, novated leases, or related topics
3. If the conversation is just starting (greeting), suggest common topics users might ask about
4. If the bot just answered a question, suggest related follow-up questions
5. If the conversation has no context or is unclear, return empty array

EXAMPLES:
- If bot says "Hello! I can help with EV leasing...", suggest: ["What is a novated lease?", "How does FBT exemption work?", "What EVs are available?"]
- If bot explains novated leases, suggest: ["What are the tax benefits?", "How do I apply?", "What vehicles can I lease?"]
- If bot explains FBT, suggest: ["Which vehicles qualify?", "How much can I save?", "What are the requirements?"]

RESPOND WITH JSON ONLY:
{{
    "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"]
}}

If no relevant suggestions can be generated, return: {{"suggestions": []}}
"""


def generate_suggestions(conversation_messages, last_bot_message=None, max_suggestions=5):
    """
    Generate contextual suggestion questions based on conversation history.
    
    Args:
        conversation_messages: List of message dicts with 'role' and 'content' keys
        last_bot_message: Optional last bot message string (if not provided, extracted from messages)
        max_suggestions: Maximum number of suggestions to generate (default: 5)
    
    Returns:
        List of suggestion strings, or empty list if no suggestions can be generated
    """
    client, model = _get_openai_client()
    if not client or not model:
        logger.error("OpenAI client not available for suggestions")
        return []
    
    try:
        # Extract last bot message if not provided
        if not last_bot_message:
            for msg in reversed(conversation_messages):
                if msg.get("role") == "assistant":
                    last_bot_message = msg.get("content", "")
                    break
        
        # Build conversation context (last 6 messages for context)
        recent_messages = conversation_messages[-6:] if len(conversation_messages) > 6 else conversation_messages
        conversation_context = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')[:200]}"
            for msg in recent_messages
        ])
        
        # If no conversation context or last bot message, return empty array
        if not conversation_context.strip() and not last_bot_message:
            logger.info("No conversation context - returning empty suggestions")
            return []
        
        # If last bot message is a greeting and no other context, generate initial suggestions
        if last_bot_message and len(recent_messages) <= 2:
            # Check if it's a greeting
            greeting_keywords = ["hello", "hi", "hey", "welcome", "help", "assist"]
            if any(keyword in last_bot_message.lower() for keyword in greeting_keywords):
                # Generate initial topic suggestions
                initial_suggestions = [
                    "What is a novated lease?",
                    "How does FBT exemption work?",
                    "What EVs are available?",
                    "What are the tax benefits?",
                    "How do I apply for a lease?"
                ]
                logger.info(f"Generated {len(initial_suggestions)} initial suggestions for greeting")
                return initial_suggestions[:max_suggestions]
        
        # Build prompt
        prompt = SUGGESTIONS_PROMPT.format(
            conversation_context=conversation_context[:1500],  # Limit context length
            last_bot_message=last_bot_message[:500] if last_bot_message else "No previous bot message"
        )
        
        logger.info(f"Generating suggestions based on {len(recent_messages)} recent messages")
        
        # Generate suggestions using LLM
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=256,
            temperature=0.7
        )
        
        result_text = response.choices[0].message.content.strip()
        result_data = json.loads(result_text)
        
        suggestions = result_data.get("suggestions", [])
        
        # Validate and limit suggestions
        if not isinstance(suggestions, list):
            logger.warning("Invalid suggestions format from LLM")
            return []
        
        # Filter out empty suggestions and limit length
        valid_suggestions = [
            s.strip() for s in suggestions 
            if s and isinstance(s, str) and len(s.strip()) > 0 and len(s.strip()) <= 100
        ]
        
        # Limit to max_suggestions
        valid_suggestions = valid_suggestions[:max_suggestions]
        
        logger.info(f"Generated {len(valid_suggestions)} valid suggestions")
        return valid_suggestions
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse suggestions JSON: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error generating suggestions: {str(e)}", exc_info=True)
        return []

