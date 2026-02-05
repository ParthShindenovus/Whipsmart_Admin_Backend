"""
RAG-based suggestion generator for the LangGraph agent.
Generates related questions based on knowledge base documents used in RAG responses.

This module provides intelligent suggestion generation that:
1. Analyzes RAG documents used to answer user questions
2. Extracts related topics and concepts from the knowledge base
3. Generates contextually relevant follow-up questions
4. Combines RAG-based suggestions with conversational context
5. Prioritizes conversion-focused suggestions (Connect with team, Get quote, etc.)

Key Features:
- RAG-aware: Uses actual knowledge base content to suggest related questions
- Context-aware: Considers conversation history and question types
- Conversion-focused: Guides users toward connecting with WhipSmart's team
- Fallback support: Provides contextual suggestions when RAG data isn't available

Usage:
- Called automatically by the LangGraph agent when generating responses
- Prioritizes RAG-based suggestions for domain questions with knowledge results
- Falls back to contextual suggestions for general conversation flow
"""
import logging
import json
from typing import List, Dict, Any, Optional
from openai import AzureOpenAI
from django.conf import settings

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


RAG_RELATED_QUESTIONS_PROMPT = """You are generating related follow-up questions based on a user's question and the knowledge base documents that were used to answer it.

User's Original Question:
{user_question}

Bot's Answer:
{bot_answer}

Knowledge Base Documents Used:
{rag_documents}

INSTRUCTIONS:
1. Generate 3-4 related questions that users might naturally want to ask next
2. Base questions on the CONTENT and TOPICS found in the knowledge base documents
3. Questions should be:
   - Directly related to the topics covered in the documents
   - Natural follow-ups to the user's original question
   - Short and clear (max 12 words each)
   - Specific to WhipSmart's services and the document content
4. Focus on related aspects mentioned in the documents but not fully covered in the bot's answer
5. Include one conversion-focused suggestion like "Connect with our team" or "Get a quote" if appropriate
6. Avoid repeating the exact same question the user just asked
7. Look for specific details in the documents like:
   - Tax benefits, FBT exemption amounts
   - Vehicle eligibility criteria, price caps
   - Application processes, requirements
   - Savings calculations, salary sacrifice details
   - Maintenance, insurance coverage
   - Lease terms, end-of-lease options

EXAMPLES:
- If user asked about "novated lease benefits" and docs mention tax savings, FBT exemption, salary sacrifice:
  ["How much can I save on tax?", "What is FBT exemption?", "How does salary sacrifice work?", "Connect with our team"]
- If user asked about "EV eligibility" and docs mention specific models, price caps, luxury car tax:
  ["What EVs are under the price cap?", "How does luxury car tax work?", "What about Tesla models?", "Get a personalized quote"]
- If user asked about "application process" and docs mention credit checks, documents needed, approval time:
  ["What documents do I need?", "How long does approval take?", "What's the credit requirement?", "Apply for lease"]

RESPOND WITH JSON ONLY:
{{
    "related_questions": ["question 1", "question 2", "question 3", "question 4"]
}}

If no related questions can be generated, return: {{"related_questions": []}}
"""


CONTEXTUAL_SUGGESTIONS_PROMPT = """You are generating contextual suggestion questions for a chat interface. These are quick-reply buttons that users can click to continue the conversation.

PRIMARY GOAL: Generate suggestions that guide users toward connecting with WhipSmart's team or taking action.

Conversation Context:
{conversation_context}

Last Bot Message:
{last_bot_message}

User's Last Question:
{user_question}

Question Type: {question_type}

INSTRUCTIONS:
1. Generate 3-4 short, relevant suggestion questions based on the conversation context
2. PRIORITIZE conversion-focused suggestions:
   - "Connect with our team" or "Get started" should be included when user shows interest
   - After answering questions, include suggestions like "I'd like to learn more" or "Connect with your team"
3. Suggestions should be:
   - Short (max 10-12 words each)
   - Contextually relevant to the last bot message and conversation
   - Natural follow-up questions or related topics
   - Specific to WhipSmart's EV leasing services, novated leases, or related topics
   - Conversion-focused when appropriate (guide users to connect with team)
4. If the conversation is just starting (greeting), suggest common topics users might ask about
5. If the bot just answered a question, suggest related follow-up questions AND include conversion suggestions
6. If user shows interest (asks about pricing, benefits, getting started), prioritize "Connect with our team" suggestions

EXAMPLES:
- If bot says "Hello! I can help with EV leasing...", suggest: ["What is a novated lease?", "How does FBT exemption work?", "Connect with our team"]
- If bot explains novated leases, suggest: ["What are the tax benefits?", "Connect with our team to explore options", "How do I apply?"]
- If bot explains FBT, suggest: ["Which vehicles qualify?", "Connect with our team", "How much can I save?"]
- If user asks about pricing/benefits, suggest: ["Connect with our team to get started", "I'd like to learn more", "Get a personalized quote"]

RESPOND WITH JSON ONLY:
{{
    "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"]
}}

If no relevant suggestions can be generated, return: {{"suggestions": []}}
"""


def generate_rag_related_questions(
    user_question: str,
    bot_answer: str,
    rag_documents: List[Dict[str, Any]]
) -> List[str]:
    """
    Generate related questions based on RAG documents used to answer a user's question.
    
    Args:
        user_question: The user's original question
        bot_answer: The bot's response to the question
        rag_documents: List of RAG documents that were used to generate the answer
        
    Returns:
        List of related question strings
    """
    client, model = _get_openai_client()
    if not client or not model:
        logger.error("OpenAI client not available for RAG suggestions")
        return []
    
    if not rag_documents:
        logger.info("No RAG documents provided - cannot generate related questions")
        return []
    
    try:
        # Format RAG documents for the prompt
        formatted_docs = []
        for i, doc in enumerate(rag_documents[:4], 1):  # Use top 4 documents
            text = doc.get('text', '')[:800]  # Limit text length
            source = doc.get('source', '') or doc.get('reference_url', '') or doc.get('url', '')
            score = doc.get('score', 0.0)
            
            doc_text = f"Document {i} (Score: {score:.3f}):\n{text}"
            if source:
                doc_text += f"\nSource: {source}"
            formatted_docs.append(doc_text)
        
        documents_text = "\n\n".join(formatted_docs)
        
        # Build prompt
        prompt = RAG_RELATED_QUESTIONS_PROMPT.format(
            user_question=user_question[:300],
            bot_answer=bot_answer[:600],
            rag_documents=documents_text
        )
        
        logger.info(f"Generating RAG-based related questions for: '{user_question[:50]}...'")
        
        # Generate related questions using LLM
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0.7
        )
        
        result_text = response.choices[0].message.content.strip()
        result_data = json.loads(result_text)
        
        related_questions = result_data.get("related_questions", [])
        
        # Validate and filter questions
        if not isinstance(related_questions, list):
            logger.warning("Invalid related questions format from LLM")
            return []
        
        # Filter out empty questions and limit length
        valid_questions = [
            q.strip() for q in related_questions 
            if q and isinstance(q, str) and len(q.strip()) > 0 and len(q.strip()) <= 100
        ]
        
        # Limit to max 4 questions
        valid_questions = valid_questions[:4]
        
        logger.info(f"Generated {len(valid_questions)} RAG-based related questions")
        
        # Add metadata for database storage
        return [
            {
                'text': question,
                'type': 'rag_related',
                'metadata': {
                    'generation_method': 'rag_based',
                    'rag_documents_count': len(rag_documents),
                    'user_question': user_question[:100]
                }
            }
            for question in valid_questions
        ]
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse related questions JSON: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error generating RAG-based related questions: {str(e)}", exc_info=True)
        return []


def generate_contextual_suggestions(
    conversation_messages: List[Dict[str, str]],
    last_bot_message: str,
    user_question: str,
    question_type: str = "general",
    max_suggestions: int = 4
) -> List[str]:
    """
    Generate contextual suggestion questions based on conversation history.
    
    Args:
        conversation_messages: List of message dicts with 'role' and 'content' keys
        last_bot_message: The bot's last message
        user_question: The user's last question
        question_type: Type of question (domain, general, user_action)
        max_suggestions: Maximum number of suggestions to generate
        
    Returns:
        List of suggestion strings
    """
    client, model = _get_openai_client()
    if not client or not model:
        logger.error("OpenAI client not available for contextual suggestions")
        return []
    
    try:
        # Build conversation context (last 6 messages for context)
        recent_messages = conversation_messages[-6:] if len(conversation_messages) > 6 else conversation_messages
        conversation_context = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')[:200]}"
            for msg in recent_messages
        ])
        
        # If no conversation context, return default suggestions
        if not conversation_context.strip() and not last_bot_message:
            logger.info("No conversation context - returning default suggestions")
            return [
                "What is a novated lease?",
                "How does FBT exemption work?",
                "Connect with our team"
            ]
        
        # Build prompt
        prompt = CONTEXTUAL_SUGGESTIONS_PROMPT.format(
            conversation_context=conversation_context[:1200],
            last_bot_message=last_bot_message[:400] if last_bot_message else "No previous bot message",
            user_question=user_question[:200],
            question_type=question_type
        )
        
        logger.info(f"Generating contextual suggestions for question type: {question_type}")
        
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
        
        # Validate and filter suggestions
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
        
        logger.info(f"Generated {len(valid_suggestions)} contextual suggestions")
        
        # Add metadata for database storage
        return [
            {
                'text': suggestion,
                'type': 'contextual',
                'metadata': {
                    'generation_method': 'contextual',
                    'question_type': question_type,
                    'conversation_length': len(conversation_messages)
                }
            }
            for suggestion in valid_suggestions
        ]
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse contextual suggestions JSON: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error generating contextual suggestions: {str(e)}", exc_info=True)
        return []


def generate_suggestions_with_rag(
    user_question: str,
    bot_answer: str,
    conversation_messages: List[Dict[str, str]],
    question_type: str = "general",
    rag_documents: Optional[List[Dict[str, Any]]] = None
) -> List[str]:
    """
    Generate suggestions combining RAG-based related questions and contextual suggestions.
    
    Args:
        user_question: The user's question
        bot_answer: The bot's response
        conversation_messages: Conversation history
        question_type: Type of question (domain, general, user_action)
        rag_documents: RAG documents used to generate the answer (if any)
        
    Returns:
        List of suggestion strings
    """
    suggestions = []
    
    # If we have RAG documents and this is a domain question, prioritize RAG-based suggestions
    if rag_documents and question_type == "domain":
        rag_suggestions = generate_rag_related_questions(
            user_question, bot_answer, rag_documents
        )
        
        # Extract text from suggestion objects
        suggestions.extend([s['text'] if isinstance(s, dict) else s for s in rag_suggestions])
        
        # If we got good RAG suggestions, use them primarily
        if len(suggestions) >= 3:
            logger.info(f"Using {len(suggestions)} RAG-based suggestions")
            return suggestions[:4]
    
    # Generate contextual suggestions as fallback or supplement
    contextual_suggestions = generate_contextual_suggestions(
        conversation_messages, bot_answer, user_question, question_type
    )
    
    # Extract text from suggestion objects
    contextual_texts = [s['text'] if isinstance(s, dict) else s for s in contextual_suggestions]
    
    # Combine suggestions, avoiding duplicates
    seen = set()
    combined_suggestions = []
    
    # Add RAG suggestions first
    for suggestion in suggestions:
        if suggestion.lower() not in seen:
            seen.add(suggestion.lower())
            combined_suggestions.append(suggestion)
    
    # Add contextual suggestions
    for suggestion in contextual_texts:
        if suggestion.lower() not in seen and len(combined_suggestions) < 4:
            seen.add(suggestion.lower())
            combined_suggestions.append(suggestion)
    
    logger.info(f"Generated {len(combined_suggestions)} combined suggestions")
    return combined_suggestions[:4]