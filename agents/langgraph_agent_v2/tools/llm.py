"""
LLM utilities for LangGraph Agent V2.
"""
import logging
from typing import Optional, Dict, Any, List
from openai import AzureOpenAI
from django.conf import settings

logger = logging.getLogger(__name__)

# Singleton client
_client: Optional[AzureOpenAI] = None
_model: Optional[str] = None


def get_llm_client() -> tuple[Optional[AzureOpenAI], Optional[str]]:
    """Get or create Azure OpenAI client (singleton)."""
    global _client, _model
    
    if _client is not None:
        return _client, _model
    
    try:
        api_key = getattr(settings, 'AZURE_OPENAI_API_KEY', None)
        endpoint = getattr(settings, 'AZURE_OPENAI_ENDPOINT', None)
        api_version = getattr(settings, 'AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
        deployment_name = getattr(settings, 'AZURE_OPENAI_DEPLOYMENT_NAME', 'gpt-4o')
        
        if not api_key or not endpoint:
            logger.error("Azure OpenAI credentials not configured")
            return None, None
        
        _client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint
        )
        _model = deployment_name
        
        logger.info(f"Initialized Azure OpenAI client: {deployment_name}")
        return _client, _model
        
    except Exception as e:
        logger.error(f"Failed to initialize Azure OpenAI client: {str(e)}")
        return None, None


def llm_call(
    prompt: str,
    system_prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    response_format: Optional[Dict[str, str]] = None
) -> str:
    """
    Make LLM call with error handling.
    
    Args:
        prompt: User prompt
        system_prompt: Optional system prompt
        messages: Optional message history
        temperature: Temperature for generation
        max_tokens: Maximum tokens
        response_format: Optional response format (e.g., {"type": "json_object"})
    
    Returns:
        LLM response text
    """
    client, model = get_llm_client()
    
    if not client or not model:
        raise RuntimeError("LLM client not available")
    
    # Build messages
    message_list = []
    if system_prompt:
        message_list.append({"role": "system", "content": system_prompt})
    
    if messages:
        message_list.extend(messages)
    
    message_list.append({"role": "user", "content": prompt})
    
    try:
        kwargs = {
            "model": model,
            "messages": message_list,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if response_format:
            kwargs["response_format"] = response_format
        
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"LLM call failed: {str(e)}", exc_info=True)
        raise


def llm_call_json(
    prompt: str,
    system_prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> Dict[str, Any]:
    """
    Make LLM call and parse JSON response.
    
    Returns:
        Parsed JSON as dictionary
    """
    import json
    
    response = llm_call(
        prompt=prompt,
        system_prompt=system_prompt,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"}
    )
    
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {str(e)}")
        raise
