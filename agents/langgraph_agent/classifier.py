"""
Question classifier for determining if RAG context is needed.
"""
import logging
import re
from typing import Tuple
from agents.langgraph_agent.config import (
    DOMAIN_KEYWORDS, USER_ACTION_KEYWORDS, CONNECTION_INTENT_PATTERNS,
    QuestionType
)

logger = logging.getLogger(__name__)


class QuestionClassifier:
    """Classifies user questions to determine if RAG context is needed."""
    
    @staticmethod
    def classify(user_message: str, conversation_history: list) -> Tuple[str, str]:
        """
        Classify question and determine if RAG is needed.
        
        Args:
            user_message: The user's message
            conversation_history: Previous messages in conversation
            
        Returns:
            Tuple of (question_type, rag_query)
            - question_type: 'domain', 'user_action', or 'unclear'
            - rag_query: Query string if RAG needed, empty string otherwise
        """
        message_lower = user_message.lower()
        message_stripped = user_message.strip()
        
        # Check for contact information (email/phone) - NO RAG
        if QuestionClassifier._has_contact_info(message_stripped):
            logger.info("[CLASSIFY] Contact information detected - bypassing RAG")
            return QuestionType.USER_ACTION, ""
        
        # Check for user action keywords - NO RAG
        if QuestionClassifier._has_user_action_keywords(message_lower):
            logger.info("[CLASSIFY] User action detected - bypassing RAG")
            return QuestionType.USER_ACTION, ""
        
        # Check for connection intent patterns - NO RAG
        if QuestionClassifier._has_connection_intent(message_lower):
            logger.info("[CLASSIFY] Connection intent detected - bypassing RAG")
            return QuestionType.USER_ACTION, ""
        
        # Check for domain keywords - NEEDS RAG
        if QuestionClassifier._has_domain_keywords(message_lower):
            logger.info(f"[CLASSIFY] Domain question detected - using RAG")
            return QuestionType.DOMAIN, message_stripped
        
        # Check conversation history for domain context
        if QuestionClassifier._has_domain_context_in_history(message_lower, conversation_history):
            logger.info("[CLASSIFY] Domain context in history - using RAG")
            return QuestionType.DOMAIN, message_stripped
        
        # Check if last assistant message asked for info
        if QuestionClassifier._is_info_submission(conversation_history):
            logger.info("[CLASSIFY] Info submission detected - bypassing RAG")
            return QuestionType.USER_ACTION, ""
        
        # Default: unclear, no RAG
        logger.info("[CLASSIFY] Unclear question - no RAG")
        return QuestionType.UNCLEAR, ""
    
    @staticmethod
    def _has_contact_info(message: str) -> bool:
        """Check if message contains email or phone."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        has_email = bool(re.search(email_pattern, message))
        
        digit_count = len(re.findall(r'\d', message))
        has_phone = digit_count >= 8
        
        if has_email or has_phone:
            # Check if it's part of a question
            question_words = ['what', 'where', 'when', 'why', 'how', 'who', 'which', '?']
            is_question = any(word in message.lower() for word in question_words)
            return not is_question
        
        return False
    
    @staticmethod
    def _has_user_action_keywords(message_lower: str) -> bool:
        """Check for user action keywords with word boundaries."""
        import re
        
        # Simple responses that should be exact matches
        simple_responses = ['yes', 'no', 'sure', 'okay', 'ok', 'thanks', 'thank you',
                          'goodbye', 'bye', 'done', 'finished', 'that\'s all', 'no more questions',
                          'sounds good', 'that works', 'perfect', 'great']
        
        # Check simple responses with word boundaries
        for keyword in simple_responses:
            if re.search(r'\b' + re.escape(keyword) + r'\b', message_lower):
                return True
        
        # Check other user action keywords (phrases that are safe to match as substrings)
        other_keywords = [kw for kw in USER_ACTION_KEYWORDS if kw not in simple_responses]
        for keyword in other_keywords:
            if keyword in message_lower:
                return True
        
        return False
    
    @staticmethod
    def _has_connection_intent(message_lower: str) -> bool:
        """Check for connection intent patterns."""
        for pattern in CONNECTION_INTENT_PATTERNS:
            if re.search(pattern, message_lower):
                return True
        return False
    
    @staticmethod
    def _has_domain_keywords(message_lower: str) -> bool:
        """Check for domain keywords."""
        for keyword in DOMAIN_KEYWORDS:
            if keyword in message_lower:
                return True
        return False
    
    @staticmethod
    def _has_domain_context_in_history(message_lower: str, conversation_history: list) -> bool:
        """Check if previous messages had domain context."""
        if len(message_lower.split()) <= 5:  # Short message
            for msg in reversed(conversation_history[-3:]):
                if msg.get('role') == 'user':
                    prev_msg = msg.get('content', '').lower()
                    if any(kw in prev_msg for kw in DOMAIN_KEYWORDS):
                        return True
        return False
    
    @staticmethod
    def _is_info_submission(conversation_history: list) -> bool:
        """Check if last assistant message asked for info."""
        if not conversation_history:
            return False
        
        from agents.langgraph_agent.config import INFO_REQUEST_KEYWORDS
        
        last_assistant_msg = None
        for msg in reversed(conversation_history[-3:]):
            if msg.get('role') == 'assistant':
                last_assistant_msg = msg.get('content', '').lower()
                break
        
        if last_assistant_msg:
            return any(kw in last_assistant_msg for kw in INFO_REQUEST_KEYWORDS)
        
        return False
