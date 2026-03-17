"""
Integration layer for LangGraph Agent V2.
Compatible with existing WebSocket and REST API.
"""
import logging
from typing import Dict, Any
from chats.models import Session
from agents.session_manager import session_manager
from .state import AgentState
from .graph import get_graph

logger = logging.getLogger(__name__)

def _increment_question_count(conversation_data: Dict[str, Any]) -> int:
    current = int(conversation_data.get("question_count") or 0)
    current += 1
    conversation_data["question_count"] = current
    return current


class ChatAPIIntegration:
    """
    Integration class for chat API (WebSocket and REST).
    """
    
    @staticmethod
    def process_message(session_id: str, user_message: str) -> Dict[str, Any]:
        """
        Process a user message and return response.
        
        Args:
            session_id: Session ID
            user_message: User's message
        
        Returns:
            Response dictionary compatible with existing API
        """
        try:
            # Get or create session
            session = Session.objects.get(id=session_id)
            conversation_data = session.conversation_data or {}
            visitor = session.visitor
            
            # Check if session is complete
            if conversation_data.get('step') == 'complete':
                return {
                    'message': "Thank you! Our team will contact you shortly. Have a wonderful day!",
                    'suggestions': [],
                    'complete': True,
                    'needs_info': None,
                    'followup_type': '',
                    'followup_message': '',
                    'metadata': {}
                }
            
            # Get or create agent state
            agent_state_dict = session_manager.get_or_create_agent_state(session_id)
            
            # Convert to AgentState
            state = AgentState.from_dict(agent_state_dict.to_dict() if hasattr(agent_state_dict, 'to_dict') else agent_state_dict)
            
            # Update user info from conversation_data, then visitor profile (persist across sessions)
            state.user_name = conversation_data.get('name') or state.user_name or visitor.name
            state.user_email = conversation_data.get('email') or state.user_email or visitor.email
            state.user_phone = conversation_data.get('phone') or state.user_phone or visitor.phone
            state.step = conversation_data.get('step', 'chatting')

            # Load counters / flow flags
            state.question_count = int(conversation_data.get('question_count') or 0)
            state.last_team_offer_count = int(conversation_data.get('last_team_offer_count') or 0)
            state.awaiting_team_connection_confirm = bool(conversation_data.get('awaiting_team_connection_confirm') or False)
            
            # Add user message
            state.messages.append({
                "role": "user",
                "content": user_message
            })

            # Increment question count for normal chat flow (not while collecting info)
            # This is the trigger for proactive team connection offers.
            if state.step in {"chatting", "awaiting_team_connection"} and not conversation_data.get("collecting_user_info", False):
                state.question_count = _increment_question_count(conversation_data)
            
            # Get graph and invoke
            graph = get_graph()
            logger.info("=" * 80)
            logger.info(f"[AGENT_V2] ===== USING LANGGRAPH AGENT V2 =====")
            logger.info(f"[AGENT_V2] Processing message for session: {session_id}")
            logger.info(f"[AGENT_V2] User message: {user_message[:100]}")
            logger.info("=" * 80)
            
            # Invoke graph
            final_state_dict = graph.invoke(state.to_dict())
            final_state = AgentState.from_dict(final_state_dict)
            
            # Extract response
            response_message = final_state.final_response or final_state.draft_response or ""
            
            # Update conversation data
            conversation_data['name'] = final_state.user_name or conversation_data.get('name')
            conversation_data['email'] = final_state.user_email or conversation_data.get('email')
            conversation_data['phone'] = final_state.user_phone or conversation_data.get('phone')
            conversation_data['step'] = final_state.step
            conversation_data['collecting_user_info'] = final_state.collecting_user_info
            conversation_data['question_count'] = final_state.question_count
            conversation_data['last_team_offer_count'] = final_state.last_team_offer_count
            conversation_data['awaiting_team_connection_confirm'] = final_state.awaiting_team_connection_confirm
            
            # Save conversation data
            session.conversation_data = conversation_data
            session.save(update_fields=['conversation_data'])

            # Persist contact info to visitor so next session doesn't ask again
            updated = False
            if final_state.user_name and final_state.user_name != visitor.name:
                visitor.name = final_state.user_name
                updated = True
            if final_state.user_email and final_state.user_email != visitor.email:
                visitor.email = final_state.user_email
                updated = True
            if final_state.user_phone and final_state.user_phone != visitor.phone:
                visitor.phone = final_state.user_phone
                updated = True
            if updated:
                visitor.save(update_fields=['name', 'email', 'phone'])
            
            # NOTE: Do not call `session_manager.save_agent_state` here.
            # That helper expects the v1 `agents.state.AgentState` object, and it also writes assistant messages.
            # WebSocket/REST layers already persist assistant messages via `session_manager.save_assistant_message`,
            # so calling it here would be redundant and error-prone.
            
            # Format response
            return {
                'message': response_message,
                'suggestions': final_state.suggestions,
                'complete': final_state.is_complete,
                'needs_info': final_state.needs_info,
                'followup_type': final_state.followup_type or '',
                'followup_message': final_state.followup_message or '',
                'metadata': {
                    'question_type': final_state.question_type,
                    'validation_passed': final_state.validation_result.get('overall_valid', True) if final_state.validation_result else True
                }
            }
            
        except Session.DoesNotExist:
            logger.error(f"[AGENT_V2] Session not found: {session_id}")
            return {
                'message': "I apologize, but there was an error processing your request. Please try again.",
                'suggestions': [],
                'complete': False,
                'needs_info': None,
                'followup_type': '',
                'followup_message': '',
                'metadata': {'error': 'session_not_found'}
            }
        except Exception as e:
            logger.error(f"[AGENT_V2] Error processing message: {str(e)}", exc_info=True)
            return {
                'message': "I apologize, but I encountered an error. Please try again.",
                'suggestions': [],
                'complete': False,
                'needs_info': None,
                'followup_type': '',
                'followup_message': '',
                'metadata': {'error': str(e)}
            }
