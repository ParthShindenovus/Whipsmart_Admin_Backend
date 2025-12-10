"""
Master Agent Router - Routes conversations to appropriate agents based on conversation_type.
"""
import logging
from chats.models import Session
from agents.conversation_handlers import (
    SalesConversationHandler,
    SupportConversationHandler,
    KnowledgeConversationHandler
)

logger = logging.getLogger(__name__)


def select_agent(conversation_type: str, session: Session):
    """
    Master Agent Router - Selects the correct agent based on conversation_type.
    
    Args:
        conversation_type: "sales", "support", or "knowledge"
        session: Session instance
    
    Returns:
        Appropriate handler instance
    """
    logger.info(f"[ROUTER] Selecting agent for conversation_type: {conversation_type}")
    
    if conversation_type == "sales":
        return SalesConversationHandler(session)
    elif conversation_type == "support":
        return SupportConversationHandler(session)
    elif conversation_type == "knowledge":
        return KnowledgeConversationHandler(session)
    else:
        # Default to Knowledge agent
        logger.warning(f"[ROUTER] Unknown conversation_type '{conversation_type}', defaulting to Knowledge")
        return KnowledgeConversationHandler(session)

