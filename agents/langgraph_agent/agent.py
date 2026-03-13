"""
Main LangGraph agent orchestrator.
"""
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime
from django.conf import settings
from openai import AzureOpenAI
from chats.models import Session, ChatMessage, MessageSuggestion
from agents.langgraph_agent.state import AgentState
from agents.langgraph_agent.classifier import QuestionClassifier
from agents.langgraph_agent.prompts import (
    SYSTEM_PROMPT_TEMPLATE, DOMAIN_QUESTION_PROMPT_TEMPLATE, TONE_VALIDATION_PROMPT
)
from agents.langgraph_agent.config import (
    CONVERSATION_HISTORY_LIMIT, EXTENDED_HISTORY_LIMIT,
    LLM_TEMPERATURE_RESPONSE, LLM_MAX_TOKENS_RESPONSE,
    NAME_COLLECTION_THRESHOLD, TEAM_CONNECTION_THRESHOLD
)

logger = logging.getLogger(__name__)


class LangGraphAgent:
    """Main agent orchestrator using LangGraph and LangChain."""
    
    def __init__(self, session: Session):
        self.session = session
        self.client = self._get_openai_client()
        self.model = self._get_model_name()
    
    def _get_openai_client(self) -> Optional[AzureOpenAI]:
        """Get Azure OpenAI client."""
        try:
            api_key = getattr(settings, 'AZURE_OPENAI_API_KEY', None)
            endpoint = getattr(settings, 'AZURE_OPENAI_ENDPOINT', None)
            api_version = getattr(settings, 'AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
            
            if not api_key or not endpoint:
                logger.error("Azure OpenAI credentials not configured")
                return None
            
            return AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=endpoint
            )
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI: {str(e)}")
            return None
    
    def _get_model_name(self) -> str:
        """Get model deployment name."""
        return getattr(settings, 'AZURE_OPENAI_DEPLOYMENT_NAME', 'gpt-4o')
    
    def handle_message(self, user_message: str) -> Dict[str, Any]:
        """
        Main entry point for handling user messages.
        
        Args:
            user_message: The user's message
            
        Returns:
            Response dictionary with message, suggestions, etc.
        """
        if not self.client or not self.model:
            return self._error_response("AI service is currently unavailable")
        
        try:
            # Check if session is complete
            conversation_data = self.session.conversation_data or {}
            if conversation_data.get('step') == 'complete':
                return {
                    'message': "Thank you! Our team will contact you shortly. Have a wonderful day!",
                    'suggestions': [],
                    'complete': True,
                    'needs_info': None,
                    'escalate_to': None
                }
            
            # NEW: Check session's question count and enforce 3-question rule
            from chats.models import Visitor
            from service.hubspot_service import format_phone_number
            import re
            
            try:
                visitor = self.session.visitor
                
                # Check if visitor already has all required info
                visitor_has_info = visitor.name and visitor.email and visitor.phone
                
                # Check if we're currently collecting info
                collecting_info = conversation_data.get('collecting_user_info', False)
                
                # If we're collecting info, try to extract it from the message
                if collecting_info:
                    # Try to extract name, email, and phone from the message
                    extracted_info = self._extract_user_info(user_message)
                    
                    # Validate extracted info
                    validation_result = self._validate_and_store_visitor_info(
                        visitor, 
                        extracted_info.get('name'),
                        extracted_info.get('email'),
                        extracted_info.get('phone')
                    )
                    
                    if validation_result['all_collected']:
                        # All info collected successfully - end the session
                        conversation_data['collecting_user_info'] = False
                        conversation_data['step'] = 'complete'
                        self.session.conversation_data = conversation_data
                        self.session.is_active = False
                        self.session.save(update_fields=['conversation_data', 'is_active'])
                        
                        first_name = visitor.name.split()[0] if visitor.name else ''
                        return {
                            'message': f"Thank you so much{', ' + first_name if first_name else ''}! I've got your details. Our team will be in touch with you shortly. Have a wonderful day!",
                            'suggestions': [],  # No suggestions when ending session
                            'complete': True,
                            'needs_info': None,
                            'escalate_to': None
                        }
                    elif validation_result['errors']:
                        # Some validation errors
                        error_msg = " ".join(validation_result['errors'])
                        return {
                            'message': f"I appreciate you sharing that information! However, {error_msg.lower()} Could you please provide the correct details?",
                            'suggestions': [],
                            'complete': False,
                            'needs_info': 'name_email_phone',
                            'escalate_to': None
                        }
                    else:
                        # Partial info collected, ask for missing fields
                        missing = validation_result['missing']
                        if len(missing) == 1:
                            missing_str = missing[0]
                            return {
                                'message': f"Thank you! I just need your {missing_str} to complete the connection. Could you please share that?",
                                'suggestions': [],
                                'complete': False,
                                'needs_info': 'name_email_phone',
                                'escalate_to': None
                            }
                        else:
                            missing_str = " and ".join(missing)
                            return {
                                'message': f"Thank you! I still need your {missing_str} to connect you with our team. Could you please provide those?",
                                'suggestions': [],
                                'complete': False,
                                'needs_info': 'name_email_phone',
                                'escalate_to': None
                            }
                
                # Increment question count for THIS SESSION
                self.session.questions_asked += 1
                self.session.save(update_fields=['questions_asked'])
                total_questions = self.session.questions_asked
                
                logger.info(f"[QUESTION_COUNT] Session {self.session.id} has asked {total_questions} questions (just incremented)")
                
                # If 3 questions have been asked
                if total_questions >= 3:
                    logger.info(f"[QUESTION_COUNT] Threshold reached for session {self.session.id}")
                    
                    # Check if visitor already has info
                    if visitor_has_info:
                        # Visitor already has info - just ask if they want to connect
                        logger.info(f"[QUESTION_COUNT] Visitor already has info - asking if they want to connect")
                        
                        # Provide answer to their question
                        brief_answer = self._get_better_brief_answer(user_message)
                        
                        # Ask if they want to connect
                        first_name = visitor.name.split()[0] if visitor.name else ''
                        connect_message = f"I have your contact details on file{', ' + first_name if first_name else ''}. Would you like me to connect you with our team for more personalized assistance?"
                        
                        return {
                            'message': brief_answer,
                            'suggestions': [],
                            'complete': False,
                            'needs_info': None,
                            'escalate_to': None,
                            'followup_type': 'ask_to_connect',
                            'followup_message': connect_message
                        }
                    else:
                        # Visitor doesn't have info - start collecting
                        logger.info(f"[QUESTION_COUNT] Starting info collection for session {self.session.id}")
                        conversation_data['collecting_user_info'] = True
                        self.session.conversation_data = conversation_data
                        self.session.save(update_fields=['conversation_data'])
                        
                        # Provide answer to their question
                        brief_answer = self._get_better_brief_answer(user_message)
                        
                        # Ask for their details politely
                        request_message = "I'd love to connect you with our team so they can provide you with more detailed information and personalized assistance! Could you please share your name, email, and phone number?"
                        
                        return {
                            'message': brief_answer,
                            'suggestions': [],
                            'complete': False,
                            'needs_info': None,
                            'escalate_to': None,
                            'followup_type': 'request_info',
                            'followup_message': request_message
                        }
            except Exception as e:
                logger.error(f"Error checking session question count: {str(e)}", exc_info=True)
                # Continue with normal flow if there's an error
            
            # Track suggestion click if this message matches a recent suggestion
            self.handle_suggestion_click(user_message)
            
            # Handle specific suggestion clicks with predefined responses
            suggestion_response = self._handle_suggestion_click(user_message)
            if suggestion_response:
                # Save to database
                self._save_message(user_message, 'user')
                self._save_message(suggestion_response['message'], 'assistant', suggestion_response.get('suggestions', []))
                return suggestion_response
            
            # Initialize agent state
            state = self._initialize_state(user_message)
            
            # Classify question
            state.question_type, state.rag_query = QuestionClassifier.classify(
                user_message, state.messages
            )
            
            # Fetch RAG context if needed
            if state.question_type == 'domain' and state.rag_query:
                state.rag_context = self._fetch_rag_context(state.rag_query)
                state.knowledge_results = state.rag_context
            
            # Generate response
            response = self._generate_response(state, user_message)
            
            # Save to database
            self._save_message(user_message, 'user')
            self._save_message(response['message'], 'assistant', response.get('suggestions', []))
            
            return response
            
        except Exception as e:
            logger.error(f"Error in agent: {str(e)}", exc_info=True)
            return self._error_response("An error occurred. Please try again.")
    
    def _handle_suggestion_click(self, user_message: str) -> Optional[Dict[str, Any]]:
        """Handle specific suggestion clicks with predefined responses."""
        message_lower = user_message.lower().strip()
        
        # Handle specific suggestion responses
        if message_lower == "connect with team":
            return {
                'message': "I'd be happy to connect you with our team! To get started, I'll need a few details from you. What's your name?",
                'suggestions': [],  # No suggestions for team connection flow
                'complete': False,
                'needs_info': 'name',
                'escalate_to': None
            }
        
        elif message_lower == "get a quote":
            return {
                'message': "Great! Click on the link below to search for a car and generate your personalized quote:\n\n[Search Cars & Get Quote](https://whipsmart.com.au/search)\n\nYou can browse our available vehicles, compare options, and get an instant quote based on your preferences.",
                'suggestions': ["Tell me about the process", "What vehicles are available?", "Connect with team"],
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
        
        elif message_lower == "apply for lease":
            return {
                'message': "Ready to apply? Get your credit pre-approved and start your lease application here:\n\n[Apply for Lease](https://whipsmart.com.au/lease-application)\n\nOur application process is quick and easy, and you'll get a decision fast so you can start driving your new EV sooner.",
                'suggestions': ["What documents do I need?", "How long does approval take?", "Connect with team"],
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
        
        return None
    
    def _initialize_state(self, user_message: str) -> AgentState:
        """Initialize agent state from session."""
        conversation_data = self.session.conversation_data or {}
        
        # Get conversation history
        messages = self._get_conversation_history(CONVERSATION_HISTORY_LIMIT)
        
        # Check if should ask for name
        should_ask_for_name = self._should_ask_for_name(conversation_data)
        
        # Check if should offer team connection
        should_offer_team_connection = self._should_offer_team_connection()
        
        state = AgentState(
            session_id=str(self.session.id),
            messages=messages,
            user_name=conversation_data.get('name'),
            user_email=conversation_data.get('email'),
            user_phone=conversation_data.get('phone'),
            step=conversation_data.get('step', 'chatting'),
            should_ask_for_name=should_ask_for_name,
            should_offer_team_connection=should_offer_team_connection,
        )
        
        return state
    
    def _get_conversation_history(self, limit: int = 4) -> list:
        """Get conversation history from database."""
        try:
            messages = ChatMessage.objects.filter(
                session=self.session,
                is_deleted=False,
                role__in=['user', 'assistant']
            ).order_by('-timestamp')[:limit]
            
            history = []
            for msg in reversed(messages):
                history.append({
                    "role": msg.role,
                    "content": msg.message
                })
            
            return history
        except Exception as e:
            logger.error(f"Error getting conversation history: {str(e)}")
            return []
    
    def _should_ask_for_name(self, conversation_data: Dict) -> bool:
        """Check if should ask for name."""
        if conversation_data.get('name'):
            return False
        
        try:
            user_message_count = ChatMessage.objects.filter(
                session=self.session,
                is_deleted=False,
                role='user'
            ).count()
            
            return NAME_COLLECTION_THRESHOLD <= user_message_count <= NAME_COLLECTION_THRESHOLD + 1
        except Exception as e:
            logger.error(f"Error checking name collection: {str(e)}")
            return False
    
    def _should_offer_team_connection(self) -> bool:
        """Check if should offer team connection."""
        try:
            user_message_count = ChatMessage.objects.filter(
                session=self.session,
                is_deleted=False,
                role='user'
            ).count()
            
            return TEAM_CONNECTION_THRESHOLD <= user_message_count <= TEAM_CONNECTION_THRESHOLD + 1
        except Exception as e:
            logger.error(f"Error checking team connection: {str(e)}")
            return False
    
    def _fetch_rag_context(self, query: str) -> list:
        """Fetch RAG context for a query."""
        try:
            from agents.tools.rag_tool import rag_tool_node
            from agents.state import AgentState as OldAgentState
            
            agent_state = OldAgentState(session_id=str(self.session.id))
            agent_state.tool_result = {"action": "rag", "query": query}
            
            state_dict = rag_tool_node(agent_state.to_dict())
            rag_state = OldAgentState.from_dict(state_dict)
            
            results = rag_state.tool_result.get('results', [])
            
            formatted_results = []
            for r in results[:4]:
                if isinstance(r, dict):
                    formatted_results.append({
                        "text": r.get('text', '')[:500],
                        "score": r.get('score', 0.0),
                        "source": r.get('reference_url') or r.get('url') or ''
                    })
            
            return formatted_results
        except Exception as e:
            logger.error(f"Error fetching RAG context: {str(e)}")
            return []
    
    def _generate_response(self, state: AgentState, user_message: str) -> Dict[str, Any]:
        """Generate response using LLM."""
        try:
            # Build system prompt
            first_name = state.user_name.split()[0] if state.user_name else ''
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                name=state.user_name or "Not provided",
                email=state.user_email or "Not provided",
                phone=state.user_phone or "Not provided",
                step=state.step,
                first_name=first_name
            )
            
            # Build messages
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(state.messages)
            messages.append({"role": "user", "content": user_message})
            
            # For domain questions with RAG, use enhanced prompt
            if state.question_type == 'domain' and state.rag_context:
                context_text = self._format_rag_context(state.rag_context)
                history_text = self._format_history(state.messages)
                
                user_prompt = DOMAIN_QUESTION_PROMPT_TEMPLATE.format(
                    user_message=user_message,
                    context_text=context_text,
                    history_text=history_text,
                    user_name=first_name
                )
                
                messages[-1] = {"role": "user", "content": user_prompt}
            
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=LLM_TEMPERATURE_RESPONSE,
                max_tokens=LLM_MAX_TOKENS_RESPONSE
            )
            
            assistant_message = response.choices[0].message.content.strip()
            
            # Validate and potentially rewrite for consultative tone
            assistant_message = self._validate_and_improve_tone(assistant_message, user_message)
            
            # Determine needs_info
            needs_info = self._get_needs_info(state)
            
            # Check if we're collecting user info
            conversation_data = self.session.conversation_data or {}
            collecting_info = conversation_data.get('collecting_user_info', False)
            
            # Generate suggestions (but not for user_action questions or when actively collecting info)
            if state.question_type == 'user_action':
                suggestions = []
            elif collecting_info:
                # CRITICAL: No suggestions when collecting user info
                suggestions = []
            elif needs_info and state.step in ['name', 'email', 'phone']:
                # Only hide suggestions when actively in the info collection flow
                suggestions = []
            else:
                suggestions = self._generate_suggestions(assistant_message, user_message, state.question_type, state)
            
            return {
                'message': assistant_message,
                'suggestions': suggestions,
                'complete': state.is_complete,
                'needs_info': needs_info,
                'escalate_to': None,
                'knowledge_results': state.knowledge_results,
                'metadata': {
                    'knowledge_results': state.knowledge_results,
                }
            }
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}", exc_info=True)
            return self._error_response("Failed to generate response")
    
    def _format_rag_context(self, rag_context: list) -> str:
        """Format RAG context for prompt."""
        if not rag_context:
            return "No relevant context found."
        
        formatted = []
        for i, item in enumerate(rag_context, 1):
            text = item.get('text', '')
            source = item.get('source', '')
            formatted.append(f"{i}. {text}")
            if source:
                formatted.append(f"   Source: {source}")
        
        return "\n".join(formatted)
    
    def _format_history(self, messages: list) -> str:
        """Format conversation history for prompt."""
        if not messages:
            return "No previous messages."
        
        formatted = []
        for msg in messages[-3:]:  # Last 3 messages
            role = msg.get('role', '').upper()
            content = msg.get('content', '')
            formatted.append(f"{role}: {content}")
        
        return "\n".join(formatted)
    
    def _validate_and_improve_tone(self, generated_answer: str, user_question: str) -> str:
        """Validate tone and rewrite if needed for consultative approach."""
        try:
            # Skip validation for very short responses or greetings
            if len(generated_answer) < 50 or any(word in generated_answer.lower() 
                                                for word in ['hello', 'hi', 'thanks', 'thank you']):
                return generated_answer
            
            validation_prompt = TONE_VALIDATION_PROMPT.format(
                user_question=user_question,
                generated_answer=generated_answer
            )
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": validation_prompt}],
                temperature=0.1,  # Low temperature for consistent validation
                max_tokens=1000
            )
            
            validation_result = response.choices[0].message.content.strip()
            
            # Try to parse JSON response
            try:
                result_data = json.loads(validation_result)
                if result_data.get('needs_rewrite', False) and result_data.get('rewritten_answer'):
                    logger.info(f"Tone validation: Rewriting response. Issues: {result_data.get('issues_found', [])}")
                    return result_data['rewritten_answer']
            except json.JSONDecodeError:
                logger.warning("Failed to parse tone validation JSON response")
            
            return generated_answer
            
        except Exception as e:
            logger.error(f"Error in tone validation: {str(e)}")
            return generated_answer  # Return original if validation fails
    
    def _generate_suggestions(self, assistant_message: str, user_message: str, question_type: str = None, state: AgentState = None) -> list:
        """Generate contextual suggestions using RAG-based approach when available."""
        from agents.langgraph_agent.suggestions import generate_suggestions_with_rag
        
        # Don't show suggestions for user_action type questions (like team connection requests)
        if question_type == 'user_action':
            return []
        
        # Check if this is the first interaction (no previous messages)
        message_count = ChatMessage.objects.filter(
            session=self.session,
            is_deleted=False,
            role='user'
        ).count()
        
        
        # Get conversation history for context
        conversation_messages = self._get_conversation_history(6)
        
        # Use RAG-based suggestions if we have knowledge results
        rag_documents = None
        if state and hasattr(state, 'knowledge_results') and state.knowledge_results:
            rag_documents = state.knowledge_results
        
        try:
            # Generate suggestions using the new RAG-based approach
            suggestions = generate_suggestions_with_rag(
                user_question=user_message,
                bot_answer=assistant_message,
                conversation_messages=conversation_messages,
                question_type=question_type or "general",
                rag_documents=rag_documents
            )
            
            if suggestions:
                logger.info(f"Generated {len(suggestions)} RAG-enhanced suggestions")
                return suggestions[:4]  # Max 4 suggestions
        except Exception as e:
            logger.error(f"Error generating RAG-based suggestions: {str(e)}")
        
        # Fallback to simple contextual suggestions
        return self._generate_fallback_suggestions(assistant_message, user_message, question_type)
    
    def _generate_fallback_suggestions(self, assistant_message: str, user_message: str, question_type: str = None) -> list:
        """Generate fallback suggestions when RAG-based approach fails."""
        suggestions = []
        
        # Generate contextual suggestions based on conversation
        message_lower = user_message.lower()
        assistant_lower = assistant_message.lower()
        
        # Context-based suggestions for domain questions
        if question_type == 'domain':
            if any(word in message_lower for word in ['price', 'cost', 'fee', 'pricing']):
                suggestions.extend(["Get a quote", "Tell me more about pricing", "What's included?"])
            elif any(word in message_lower for word in ['vehicle', 'car', 'ev', 'tesla']):
                suggestions.extend(["Show me available vehicles", "Get a quote", "Tell me about EVs"])
            elif any(word in message_lower for word in ['process', 'how', 'steps', 'apply']):
                suggestions.extend(["Apply for lease", "What happens next?", "Connect with team"])
            elif any(word in message_lower for word in ['tax', 'benefit', 'saving']):
                suggestions.extend(["Tell me about tax benefits", "How much can I save?", "Get a quote"])
            elif any(word in message_lower for word in ['novated', 'lease', 'leasing']):
                suggestions.extend(["How does novated leasing work?", "Get a quote", "Apply for lease"])
            else:
                # Default suggestions for domain questions
                suggestions.extend(["Get a quote", "Connect with team", "Tell me more"])
        
        # Context-based suggestions for other question types
        elif any(word in assistant_lower for word in ['contact', 'team', 'speak', 'call']):
            suggestions.extend(["Connect with team", "Yes, connect me", "Not right now"])
        else:
            # Default suggestions
            suggestions.extend(["Get a quote", "Connect with team", "Tell me more"])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_suggestions = []
        for suggestion in suggestions:
            if suggestion not in seen:
                seen.add(suggestion)
                unique_suggestions.append(suggestion)
        
        return unique_suggestions[:3]  # Max 3 suggestions
    
    def _get_needs_info(self, state: AgentState) -> Optional[str]:
        """Determine what information is needed."""
        if not state.user_name:
            return 'name'
        elif not state.user_email:
            return 'email'
        elif not state.user_phone:
            return 'phone'
        
        return None
    
    def _save_message(self, content: str, role: str, suggestions: list = None) -> ChatMessage:
        """Save message to database and optionally save suggestions."""
        try:
            message = ChatMessage.objects.create(
                session=self.session,
                role=role,
                message=content,
                timestamp=datetime.now()
            )
            
            # Save suggestions if this is an assistant message and suggestions are provided
            if role == 'assistant' and suggestions:
                self._save_suggestions(message, suggestions)
            
            return message
        except Exception as e:
            logger.error(f"Error saving message: {str(e)}")
            return None
    
    def _save_suggestions(self, message: ChatMessage, suggestions: list) -> None:
        """Save suggestions for an assistant message."""
        try:
            suggestion_objects = []
            for i, suggestion in enumerate(suggestions):
                # Handle both string suggestions and dict suggestions with metadata
                if isinstance(suggestion, dict):
                    suggestion_text = suggestion.get('text', str(suggestion))
                    suggestion_type = suggestion.get('type', 'contextual')
                    metadata = suggestion.get('metadata', {})
                else:
                    suggestion_text = str(suggestion)
                    suggestion_type = self._classify_suggestion_type(suggestion_text)
                    metadata = {}
                
                # Add common metadata
                metadata.update({
                    'generated_at': datetime.now().isoformat(),
                    'session_id': str(self.session.id),
                    'message_id': str(message.id)
                })
                
                suggestion_objects.append(MessageSuggestion(
                    message=message,
                    suggestion_text=suggestion_text,
                    suggestion_type=suggestion_type,
                    order=i,
                    metadata=metadata
                ))
            
            # Bulk create suggestions
            MessageSuggestion.objects.bulk_create(suggestion_objects)
            logger.info(f"Saved {len(suggestion_objects)} suggestions for message {message.id}")
            
        except Exception as e:
            logger.error(f"Error saving suggestions: {str(e)}")
    
    def handle_suggestion_click(self, suggestion_text: str, message_id: str = None) -> bool:
        """
        Handle when a user clicks on a suggestion.
        
        Args:
            suggestion_text: The text of the clicked suggestion
            message_id: Optional message ID to help identify the specific suggestion
            
        Returns:
            bool: True if suggestion was found and marked as clicked
        """
        try:
            # Find the suggestion in the database
            query = MessageSuggestion.objects.filter(
                suggestion_text=suggestion_text,
                is_clicked=False,
                message__session=self.session
            )
            
            # If message_id is provided, filter by it
            if message_id:
                query = query.filter(message__id=message_id)
            
            # Get the most recent matching suggestion
            suggestion = query.order_by('-created_at').first()
            
            if suggestion:
                suggestion.mark_clicked()
                logger.info(f"Marked suggestion as clicked: {suggestion_text}")
                return True
            else:
                logger.warning(f"Suggestion not found for click tracking: {suggestion_text}")
                return False
                
        except Exception as e:
            logger.error(f"Error handling suggestion click: {str(e)}")
            return False
    
    def get_message_suggestions(self, message_id: str) -> list:
        """
        Get all suggestions for a specific message.
        
        Args:
            message_id: The ID of the message to get suggestions for
            
        Returns:
            List of suggestion dictionaries
        """
        try:
            suggestions = MessageSuggestion.objects.filter(
                message__id=message_id
            ).order_by('order')
            
            return [
                {
                    'id': str(suggestion.id),
                    'text': suggestion.suggestion_text,
                    'type': suggestion.suggestion_type,
                    'order': suggestion.order,
                    'is_clicked': suggestion.is_clicked,
                    'clicked_at': suggestion.clicked_at.isoformat() if suggestion.clicked_at else None,
                    'metadata': suggestion.metadata
                }
                for suggestion in suggestions
            ]
        except Exception as e:
            logger.error(f"Error getting message suggestions: {str(e)}")
            return []
    
    def get_session_suggestion_analytics(self) -> dict:
        """
        Get analytics about suggestions for this session.
        
        Returns:
            Dictionary with suggestion analytics
        """
        try:
            suggestions = MessageSuggestion.objects.filter(
                message__session=self.session
            )
            
            total_suggestions = suggestions.count()
            clicked_suggestions = suggestions.filter(is_clicked=True).count()
            
            # Group by type
            type_counts = {}
            for suggestion in suggestions:
                suggestion_type = suggestion.suggestion_type
                if suggestion_type not in type_counts:
                    type_counts[suggestion_type] = {'total': 0, 'clicked': 0}
                type_counts[suggestion_type]['total'] += 1
                if suggestion.is_clicked:
                    type_counts[suggestion_type]['clicked'] += 1
            
            return {
                'total_suggestions': total_suggestions,
                'clicked_suggestions': clicked_suggestions,
                'click_rate': (clicked_suggestions / total_suggestions * 100) if total_suggestions > 0 else 0,
                'type_breakdown': type_counts
            }
        except Exception as e:
            logger.error(f"Error getting suggestion analytics: {str(e)}")
            return {}
    
    def _classify_suggestion_type(self, suggestion_text: str) -> str:
        """Classify the type of suggestion based on its content."""
        suggestion_lower = suggestion_text.lower()
        
        # Conversion actions
        if any(phrase in suggestion_lower for phrase in [
            'connect with', 'get a quote', 'apply for', 'contact', 'speak with', 'call'
        ]):
            return 'conversion'
        
        # RAG-related questions (domain-specific)
        elif any(phrase in suggestion_lower for phrase in [
            'tax', 'fbt', 'benefit', 'saving', 'novated', 'lease', 'vehicle', 'ev', 'eligib'
        ]):
            return 'rag_related'
        
        # Contextual suggestions
        else:
            return 'contextual'
    
    def _error_response(self, message: str) -> Dict[str, Any]:
        """Generate error response."""
        return {
            'message': message,
            'suggestions': [],
            'complete': False,
            'needs_info': None,
            'escalate_to': None
        }
    
    def _get_brief_answer(self, user_message: str) -> str:
        """Generate a brief answer to the user's question before asking for their details."""
        # Simple brief responses for common questions
        message_lower = user_message.lower()
        
        if any(word in message_lower for word in ['price', 'cost', 'how much']):
            return "Pricing depends on your specific needs and vehicle choice."
        elif any(word in message_lower for word in ['benefit', 'advantage', 'why']):
            return "Novated leases offer tax savings and convenience."
        elif any(word in message_lower for word in ['how', 'process', 'work']):
            return "The process is straightforward and our team will guide you through it."
        elif any(word in message_lower for word in ['eligible', 'qualify', 'can i']):
            return "Most employees are eligible for novated leases."
        else:
            return ""
    
    def _get_better_brief_answer(self, user_message: str) -> str:
        """Generate a better contextual brief answer based on the question."""
        message_lower = user_message.lower()
        
        # End of lease questions
        if any(phrase in message_lower for phrase in ['end of', 'end of lease', 'lease term', 'lease ends', 'after lease', 'when lease ends']):
            return "At the end of your novated lease term, you have several flexible options: you can pay the residual value and keep the vehicle, trade it in for a new lease, refinance the residual, or return the vehicle. Our team can walk you through each option and help you choose what works best for your situation."
        
        # Tax benefits
        elif any(phrase in message_lower for phrase in ['tax benefit', 'tax saving', 'tax advantage', 'save on tax', 'reduce tax']):
            return "Novated leases offer significant tax benefits by reducing your taxable income. Lease payments and running costs are deducted from your pre-tax salary, which means you pay less income tax. The exact savings depend on your income level and the vehicle you choose."
        
        # Pricing/costs
        elif any(word in message_lower for word in ['price', 'cost', 'how much', 'expensive', 'afford']):
            return "The cost of a novated lease depends on the vehicle you choose, your salary, and the lease term. Our team can provide you with a personalized quote based on your specific circumstances and help you understand the potential tax savings."
        
        # Benefits
        elif any(word in message_lower for word in ['benefit', 'advantage', 'why', 'good', 'worth']):
            return "Novated leases offer several key benefits: tax savings through pre-tax deductions, simplified budgeting with one payment covering all vehicle costs, and flexibility at the end of the lease term. Plus, you get to choose the vehicle you want!"
        
        # Process/how it works
        elif any(word in message_lower for word in ['how', 'process', 'work', 'step', 'apply']):
            return "The process is straightforward: choose your vehicle, we arrange the lease with your employer, and payments are deducted from your pre-tax salary. Our team handles all the paperwork and ongoing management, making it hassle-free for you."
        
        # Eligibility
        elif any(word in message_lower for word in ['eligible', 'qualify', 'can i', 'who can', 'requirements']):
            return "Most employees are eligible for novated leases, regardless of whether you work for a private company, government, or not-for-profit organization. The main requirement is that your employer agrees to participate in the arrangement."
        
        # Vehicles/EVs
        elif any(word in message_lower for word in ['vehicle', 'car', 'ev', 'electric', 'tesla', 'available']):
            return "You can choose from a wide range of vehicles, including electric vehicles (EVs) which offer additional tax benefits. Our team can help you explore available options and find the perfect vehicle for your needs and budget."
        
        # Default
        else:
            return "That's a great question! Our team can provide you with detailed information tailored to your specific situation."

    
    def _extract_user_info(self, message: str) -> dict:
        """Extract name, email, and phone from user message."""
        import re
        
        extracted = {
            'name': None,
            'email': None,
            'phone': None
        }
        
        # Extract email (pattern: word@word.word)
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, message)
        if email_match:
            extracted['email'] = email_match.group(0)
        
        # Extract phone (pattern: 10+ digits, possibly with spaces/dashes/parentheses)
        phone_pattern = r'[\d\s\-\(\)]{10,}'
        phone_matches = re.findall(phone_pattern, message)
        for match in phone_matches:
            digits = ''.join(filter(str.isdigit, match))
            if len(digits) >= 10:
                extracted['phone'] = digits
                break
        
        # Extract name (remaining text after removing email and phone)
        temp_message = message
        if extracted['email']:
            temp_message = temp_message.replace(extracted['email'], '')
        if extracted['phone']:
            temp_message = re.sub(r'[\d\s\-\(\)]{10,}', '', temp_message)
        
        # Clean up and extract name
        temp_message = temp_message.strip()
        temp_message = re.sub(r'\b(my|name|is|email|phone|number|here|this|it|the|a|an)\b', '', temp_message, flags=re.IGNORECASE)
        temp_message = temp_message.strip()
        
        if temp_message and len(temp_message) > 1:
            temp_message = re.sub(r'\s+', ' ', temp_message)
            extracted['name'] = temp_message.strip()
        
        return extracted
    
    def _validate_and_store_visitor_info(self, visitor, name, email, phone):
        """Validate and store user information in Visitor model."""
        from service.hubspot_service import format_phone_number
        import re
        
        errors = []
        missing = []
        updated = []
        
        # Validate and store name
        if name:
            if self._validate_name(name):
                visitor.name = name.strip()
                updated.append('name')
            else:
                errors.append("The name you provided doesn't look valid.")
        elif not visitor.name:
            missing.append('name')
        
        # Validate and store email
        if email:
            if self._validate_email(email):
                visitor.email = email.strip().lower()
                updated.append('email')
            else:
                errors.append("The email address doesn't look valid.")
        elif not visitor.email:
            missing.append('email')
        
        # Validate and store phone
        if phone:
            if self._validate_phone(phone):
                formatted_phone = format_phone_number(phone)
                visitor.phone = formatted_phone
                updated.append('phone')
            else:
                errors.append("The phone number doesn't look valid.")
        elif not visitor.phone:
            missing.append('phone')
        
        # Save visitor if any fields were updated
        if updated:
            visitor.save(update_fields=updated)
        
        # Check if all info is collected
        all_collected = visitor.name and visitor.email and visitor.phone
        
        return {
            'all_collected': all_collected,
            'updated': updated,
            'missing': missing,
            'errors': errors
        }
    
    def _validate_name(self, name: str) -> bool:
        """Validate name."""
        import re
        if not name or len(name.strip()) < 2:
            return False
        if '@' in name or re.search(r'\d{10,}', name):
            return False
        return True
    
    def _validate_email(self, email: str) -> bool:
        """Validate email."""
        if not email:
            return False
        email = email.strip().lower()
        if '@' not in email:
            return False
        parts = email.split('@')
        if len(parts) != 2:
            return False
        if '.' not in parts[1]:
            return False
        return True
    
    def _validate_phone(self, phone: str) -> bool:
        """Validate phone number."""
        if not phone:
            return False
        digits = ''.join(filter(str.isdigit, phone))
        return len(digits) >= 10
