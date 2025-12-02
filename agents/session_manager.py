"""
Session manager that works with Django Session and ChatMessage models.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from chats.models import Session, ChatMessage
from agents.state import AgentState
import logging

logger = logging.getLogger(__name__)


class DjangoSessionManager:
    """
    Manages agent sessions using Django models.
    Converts between Django models and AgentState.
    """
    
    def get_or_create_agent_state(self, session_id: str) -> AgentState:
        """
        Get existing session or create AgentState from Django Session.
        Loads messages from ChatMessage model.
        session_id is the UUID id (primary key) of the Session.
        """
        try:
            # session_id is now the id (UUID primary key)
            session = Session.objects.get(id=session_id, is_active=True)
            
            # Load messages from database
            messages = []
            chat_messages = ChatMessage.objects.filter(
                session=session,
                is_deleted=False
            ).order_by('timestamp')
            
            for msg in chat_messages:
                messages.append({
                    "role": msg.role,
                    "content": msg.message
                })
            
            # Create AgentState (use session.id as session_id for consistency)
            state = AgentState(
                session_id=str(session.id),
                messages=messages,
                tool_result=None,
                next_action=None,
                tool_calls=[],
                last_activity=session.expires_at or datetime.now()
            )
            
            logger.info(f"Loaded agent state for session: {session_id} ({len(messages)} messages)")
            return state
            
        except Session.DoesNotExist:
            logger.error(f"Session not found: {session_id}")
            raise
    
    def save_agent_state(self, session_id: str, state: AgentState):
        """
        Save agent state to Django models.
        Updates messages in ChatMessage model.
        session_id is the UUID id (primary key) of the Session.
        """
        try:
            # session_id is now the id (UUID primary key)
            session = Session.objects.get(id=session_id)
            
            # Find the last assistant message in state.messages
            last_assistant_message = None
            for msg in reversed(state.messages):
                if msg.get("role") == "assistant":
                    last_assistant_message = msg.get("content", "")
                    break
            
            # Only save if there's a new assistant message
            if last_assistant_message:
                # Check if this message already exists in DB
                existing_messages = ChatMessage.objects.filter(
                    session=session,
                    role='assistant',
                    is_deleted=False
                ).order_by('-timestamp')
                
                if existing_messages.exists():
                    latest = existing_messages.first()
                    if latest.message != last_assistant_message:
                        # New assistant message, save it
                        ChatMessage.objects.create(
                            session=session,
                            message=last_assistant_message,
                            role='assistant',
                            metadata=state.tool_result or {}
                        )
                        logger.info(f"Saved new assistant message for session: {session_id}")
                else:
                    # No existing messages, save it
                    ChatMessage.objects.create(
                        session=session,
                        message=last_assistant_message,
                        role='assistant',
                        metadata=state.tool_result or {}
                    )
                    logger.info(f"Saved first assistant message for session: {session_id}")
            
            logger.debug(f"State saved for session: {session_id}")
            
        except Session.DoesNotExist:
            logger.error(f"Session not found when saving state: {session_id}")
            raise
    
    def save_user_message(self, session_id: str, message: str):
        """
        Save user message to database.
        session_id is the UUID id (primary key) of the Session.
        """
        try:
            # session_id is now the id (UUID primary key)
            session = Session.objects.get(id=session_id)
            ChatMessage.objects.create(
                session=session,
                message=message,
                role='user',
                metadata={}
            )
            logger.info(f"Saved user message for session: {session_id}")
        except Session.DoesNotExist:
            logger.error(f"Session not found when saving user message: {session_id}")
            raise


# Global session manager instance
session_manager = DjangoSessionManager()

