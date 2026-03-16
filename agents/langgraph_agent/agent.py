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
            
            # Check if user is responding to a connection request
            connection_response = self._handle_connection_request_response(user_message)
            if connection_response:
                return connection_response
            
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
                
                # If we're collecting info, classify the message first
                if collecting_info:
                    logger.info(f"[INFO_COLLECTION] Collecting info mode. User message: '{user_message[:50]}...'")
                    
                    # Step 1: Quick regex check for obvious email/phone patterns
                    has_obvious_info = self._quick_regex_check(user_message)
                    
                    if has_obvious_info:
                        # Obvious info detected - extract and validate directly
                        logger.info(f"[INFO_COLLECTION] Obvious info detected via regex - extracting and validating")
                        extracted_info = self._extract_user_info(user_message)
                    else:
                        # Step 2: Use LLM classifier for ambiguous cases
                        logger.info(f"[INFO_COLLECTION] No obvious info - using LLM classifier")
                        classification = self._classify_user_message(user_message)
                        
                        logger.info(f"[INFO_COLLECTION] Classification result: {classification}")
                        
                        if classification['category'] == 'contains_info':
                            # User provided info - extract and validate
                            logger.info(f"[INFO_COLLECTION] LLM detected info - extracting and validating")
                            extracted_info = self._extract_user_info(user_message)
                        elif classification['category'] == 'domain_question':
                            # Domain question - provide brief answer + follow-up
                            logger.info(f"[INFO_COLLECTION] Domain question detected - providing brief answer + follow-up")
                            brief_answer = self._get_better_brief_answer(user_message)
                            followup_message, followup_type = self._get_info_request_followup(visitor, user_message, 'domain_question')
                            
                            return {
                                'message': brief_answer,
                                'suggestions': [],
                                'complete': False,
                                'needs_info': None,
                                'escalate_to': None,
                                'followup_type': followup_type,
                                'followup_message': followup_message
                            }
                        elif classification['category'] == 'meta_question':
                            # Meta question - explain why we need info + follow-up
                            logger.info(f"[INFO_COLLECTION] Meta question detected - explaining why we need info")
                            explanation = self._get_meta_question_response(classification.get('meta_reason', 'why_need'))
                            followup_message, followup_type = self._get_info_request_followup(visitor, user_message, 'meta_question')
                            
                            return {
                                'message': explanation,
                                'suggestions': [],
                                'complete': False,
                                'needs_info': None,
                                'escalate_to': None,
                                'followup_type': followup_type,
                                'followup_message': followup_message
                            }
                        else:
                            # Other/unclear - brief response + follow-up
                            logger.info(f"[INFO_COLLECTION] Other/unclear message - providing brief response + follow-up")
                            brief_response = "I understand! I'd love to help you with that. To connect you with our team for personalized assistance, I'll need your contact details."
                            followup_message, followup_type = self._get_info_request_followup(visitor, user_message, 'other')
                            
                            return {
                                'message': brief_response,
                                'suggestions': [],
                                'complete': False,
                                'needs_info': None,
                                'escalate_to': None,
                                'followup_type': followup_type,
                                'followup_message': followup_message
                            }
                    
                    # If we reach here, we have extracted_info to validate
                    # Info was extracted - validate and store it
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
            
            # Get followup_type from state if available
            followup_type = getattr(state, 'followup_type', None) or ''
            
            # Use centralized function to determine if suggestions should be shown
            should_show = self._should_show_suggestions(
                state=state,
                conversation_data=conversation_data,
                followup_type=followup_type,
                needs_info=needs_info
            )
            
            # Generate suggestions only if allowed
            if should_show:
                suggestions = self._generate_suggestions(
                    assistant_message, 
                    user_message, 
                    state.question_type or 'general', 
                    state
                )
            else:
                suggestions = []
            
            return {
                'message': assistant_message,
                'suggestions': suggestions,
                'complete': state.is_complete,
                'needs_info': needs_info,
                'escalate_to': None,
                'followup_type': followup_type,
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
    
    def _should_show_suggestions(self, state: AgentState, conversation_data: dict, 
                                followup_type: Optional[str] = None, needs_info: Optional[str] = None) -> bool:
        """
        Centralized check to determine if suggestions should be shown.
        
        Returns False (no suggestions) when:
        1. Question type is 'user_action'
        2. Collecting user info (collecting_user_info flag)
        3. Needs info and step is name/email/phone
        4. Follow-up type indicates info collection or team connection
        5. Session is complete
        
        Returns True (show suggestions) otherwise.
        """
        # Don't show suggestions if session is complete
        if state.is_complete:
            return False
        
        # Don't show suggestions for user_action type questions
        if state.question_type == 'user_action':
            return False
        
        # Don't show suggestions when collecting user info
        if conversation_data.get('collecting_user_info', False):
            return False
        
        # Don't show suggestions when actively asking for name/email/phone
        if needs_info and state.step in ['name', 'email', 'phone']:
            return False
        
        # Don't show suggestions when follow-up type indicates info collection or team connection
        if followup_type and followup_type in ['request_info', 'ask_to_connect', 'name_request', 'team_connection']:
            return False
        
        return True
    
    def _generate_suggestions(self, assistant_message: str, user_message: str, question_type: str = None, state: AgentState = None) -> list:
        """Generate contextual suggestions using RAG-based approach when available."""
        from agents.langgraph_agent.suggestions import generate_suggestions_with_rag
        
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
        """Generate a structured brief answer (4-5 lines) using LLM for domain questions."""
        try:
            # Use LLM to generate a brief, structured answer
            brief_prompt = f"""The user asked: "{user_message}"

Please provide a brief, structured answer (4-5 lines maximum) about novated leases. Keep it concise, professional, and helpful. Focus on the key points without being too detailed.

Answer:"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": brief_prompt}],
                temperature=0.7,
                max_tokens=200  # Limit to keep it brief (4-5 lines)
            )
            
            brief_answer = response.choices[0].message.content.strip()
            
            # Ensure it's not too long (max 5 lines)
            lines = brief_answer.split('\n')
            if len(lines) > 5:
                brief_answer = '\n'.join(lines[:5])
            
            return brief_answer
            
        except Exception as e:
            logger.error(f"Error generating brief answer with LLM: {str(e)}")
            # Fallback to template-based answers
            message_lower = user_message.lower()
            
            # Benefits
            if any(word in message_lower for word in ['benefit', 'advantage', 'why', 'good', 'worth', 'provide']):
                return "Novated leases offer several key benefits:\n• Tax savings through pre-tax deductions\n• Simplified budgeting with one payment covering all vehicle costs\n• Flexibility at the end of the lease term\n• You get to choose the vehicle you want!"
            
            # Tax benefits
            elif any(phrase in message_lower for phrase in ['tax benefit', 'tax saving', 'tax advantage', 'save on tax', 'reduce tax']):
                return "Novated leases offer significant tax benefits:\n• Lease payments and running costs are deducted from your pre-tax salary\n• This reduces your taxable income, meaning you pay less income tax\n• The exact savings depend on your income level and the vehicle you choose"
            
            # Pricing/costs
            elif any(word in message_lower for word in ['price', 'cost', 'how much', 'expensive', 'afford']):
                return "The cost of a novated lease depends on:\n• The vehicle you choose\n• Your salary\n• The lease term\n\nOur team can provide you with a personalized quote based on your specific circumstances."
            
            # Process/how it works
            elif any(word in message_lower for word in ['how', 'process', 'work', 'step', 'apply']):
                return "The process is straightforward:\n• Choose your vehicle\n• We arrange the lease with your employer\n• Payments are deducted from your pre-tax salary\n• Our team handles all the paperwork and ongoing management"
            
            # Eligibility
            elif any(word in message_lower for word in ['eligible', 'qualify', 'can i', 'who can', 'requirements']):
                return "Most employees are eligible for novated leases:\n• Works for private companies, government, or not-for-profit organizations\n• Main requirement is that your employer agrees to participate\n• Our team can help you check your eligibility"
            
            # Vehicles/EVs
            elif any(word in message_lower for word in ['vehicle', 'car', 'ev', 'electric', 'tesla', 'available']):
                return "You can choose from a wide range of vehicles:\n• Including electric vehicles (EVs) which offer additional tax benefits\n• Our team can help you explore available options\n• Find the perfect vehicle for your needs and budget"
            
            # End of lease
            elif any(phrase in message_lower for phrase in ['end of', 'end of lease', 'lease term', 'lease ends', 'after lease', 'when lease ends']):
                return "At the end of your novated lease term, you have several options:\n• Pay the residual value and keep the vehicle\n• Trade it in for a new lease\n• Refinance the residual\n• Return the vehicle\n\nOur team can help you choose what works best for your situation."
            
            # Default
            else:
                return "That's a great question! Novated leases offer tax benefits, flexible vehicle options, and simplified budgeting. Our team can provide you with detailed information tailored to your specific situation."

    
    def _extract_user_info(self, message: str) -> dict:
        """
        Extract name, email, and phone from user message using LLM-based extraction agent.
        Falls back to regex if LLM fails.
        """
        try:
            # Use LLM-based extraction for better accuracy
            return self._extract_info_with_llm(message)
        except Exception as e:
            logger.error(f"[EXTRACTION] LLM extraction failed: {str(e)}, falling back to regex")
            # Fallback to regex-based extraction
            return self._extract_info_with_regex(message)
    
    def _extract_info_with_llm(self, message: str) -> dict:
        """
        Extract user information (name, email, phone) using LLM for intelligent parsing.
        This handles cases like "Ok pate, pate@yopmail.com" correctly by understanding context.
        """
        extraction_prompt = f"""You are an information extraction agent. Extract name, email, and phone number from the user's message.

User message: "{message}"

Instructions:
1. Extract ONLY actual personal information (name, email, phone)
2. Ignore acknowledgments like "Ok", "Okay", "Sure", "Yes", "Thanks", etc.
3. Ignore filler words and conversational phrases
4. For name: Extract only if it's clearly a person's name (first name, full name, or initials)
   - Do NOT extract single words like "Ok", "Sure", "Yes" as names
   - Do NOT extract domain-related words like "benefit", "lease", etc.
   - Names should typically be 2+ words or a single capitalized word that looks like a name
5. For email: Extract email addresses (format: text@domain.com)
6. For phone: Extract phone numbers (10+ digits, may include spaces, dashes, parentheses)

Examples:
- "Ok pate, pate@yopmail.com" → name: "pate" (not "Ok pate"), email: "pate@yopmail.com"
- "My name is John Smith, email is john@example.com, phone is 0412345678" → name: "John Smith", email: "john@example.com", phone: "0412345678"
- "John Smith" → name: "John Smith"
- "Ok, here it is: john@example.com" → email: "john@example.com" (no name, "Ok" is acknowledgment)
- "Sure, my phone is 0412345678" → phone: "0412345678" (no name, "Sure" is acknowledgment)

Return ONLY valid JSON (no markdown, no code blocks):
{{
    "name": "extracted name or null",
    "email": "extracted email or null",
    "phone": "extracted phone (digits only) or null"
}}"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": extraction_prompt}],
            temperature=0.1,  # Low temperature for consistent extraction
            max_tokens=150
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if result_text.startswith('```'):
            result_text = result_text.split('```')[1]
            if result_text.startswith('json'):
                result_text = result_text[4:]
            result_text = result_text.strip()
        
        # Parse JSON response
        extracted = json.loads(result_text)
        
        # Clean and validate extracted data
        if extracted.get('name'):
            # Clean name: remove extra spaces, capitalize properly
            name = extracted['name'].strip()
            # Capitalize first letter of each word
            name_parts = name.split()
            name = ' '.join(word.capitalize() if word else '' for word in name_parts)
            extracted['name'] = name if len(name) >= 2 else None
        
        if extracted.get('email'):
            # Clean email: lowercase, strip
            extracted['email'] = extracted['email'].strip().lower()
        
        if extracted.get('phone'):
            # Clean phone: extract only digits
            import re
            digits = ''.join(filter(str.isdigit, extracted['phone']))
            extracted['phone'] = digits if len(digits) >= 10 else None
        
        logger.info(f"[EXTRACTION] LLM extracted: name={extracted.get('name')}, email={extracted.get('email')}, phone={extracted.get('phone')}")
        
        return {
            'name': extracted.get('name'),
            'email': extracted.get('email'),
            'phone': extracted.get('phone')
        }
    
    def _extract_info_with_regex(self, message: str) -> dict:
        """
        Fallback regex-based extraction when LLM fails.
        """
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
            extracted['email'] = email_match.group(0).lower()
        
        # Extract phone (pattern: 10+ digits, possibly with spaces/dashes/parentheses)
        phone_pattern = r'[\d\s\-\(\)]{10,}'
        phone_matches = re.findall(phone_pattern, message)
        for match in phone_matches:
            digits = ''.join(filter(str.isdigit, match))
            if len(digits) >= 10:
                extracted['phone'] = digits
                break
        
        # Extract name (remaining text after removing email and phone)
        # Only extract if it looks like an actual name (2+ words, starts with capital, not a question)
        temp_message = message
        if extracted['email']:
            temp_message = temp_message.replace(extracted['email'], '')
        if extracted['phone']:
            temp_message = re.sub(r'[\d\s\-\(\)]{10,}', '', temp_message)
        
        # Clean up and extract name
        temp_message = temp_message.strip()
        
        # Remove acknowledgments FIRST (before other processing)
        acknowledgments = r'\b(ok|okay|sure|yes|yeah|yep|yup|alright|all right|fine|good|great|thanks|thank you|here|there)\b'
        temp_message = re.sub(acknowledgments, '', temp_message, flags=re.IGNORECASE)
        
        # Remove common question words and phrases that indicate this is a question, not a name
        question_indicators = [
            r'\b(can|could|would|will|should|may|might|tell|me|more|about|what|how|why|when|where|which|who)\b',
            r'\b(is|are|does|do|did|was|were|have|has|had)\b',
            r'\b(please|share|provide|give|send)\b',
            r'\?',  # Question marks
        ]
        for pattern in question_indicators:
            temp_message = re.sub(pattern, '', temp_message, flags=re.IGNORECASE)
        
        # Remove common words
        temp_message = re.sub(r'\b(my|name|is|email|phone|number|here|this|it|the|a|an|i|you|your|our|team)\b', '', temp_message, flags=re.IGNORECASE)
        temp_message = temp_message.strip()
        
        # Only extract as name if:
        # 1. Has at least 2 words (first and last name) OR single word that's clearly a name
        # 2. Starts with capital letter (proper name)
        # 3. Doesn't contain question words
        # 4. Is not too long (max 50 chars for a name)
        if temp_message:
            words = temp_message.split()
            # Filter out very short words that are likely not names
            valid_words = [w for w in words if len(w.strip()) >= 2]
            
            if valid_words:
                # If we have valid words, check if they form a name
                potential_name = ' '.join(valid_words)
                if (len(potential_name) >= 2 and 
                    len(potential_name) <= 50 and
                    potential_name[0].isupper() and
                    not any(word.lower() in ['benefit', 'benefits', 'lease', 'novated', 'vehicle', 'car', 'tax', 'price', 'cost'] for word in valid_words)):
                    temp_message = re.sub(r'\s+', ' ', potential_name)
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
    
    def _quick_regex_check(self, message: str) -> bool:
        """
        Quick regex check for obvious email or phone patterns.
        Returns True if obvious info is detected, False otherwise.
        """
        import re
        
        # Check for email pattern
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        if re.search(email_pattern, message):
            return True
        
        # Check for phone pattern (10+ digits)
        phone_pattern = r'\d{10,}'
        if re.search(phone_pattern, message):
            return True
        
        return False
    
    def _classify_user_message(self, user_message: str) -> Dict[str, Any]:
        """
        Classify user message when collecting info using LLM.
        
        Returns:
        {
            'category': 'contains_info' | 'domain_question' | 'meta_question' | 'other',
            'contains_info': bool,
            'info_types': ['name', 'email', 'phone'] or [],
            'is_domain_question': bool,
            'is_meta_question': bool,
            'meta_reason': 'why_need' | 'why_asking' | 'what_for' | 'privacy' | None,
            'confidence': float
        }
        """
        try:
            classification_prompt = f"""You are classifying a user message received while collecting contact information for a novated lease service.

User message: "{user_message}"

Context: We are asking the user for their name, email, and phone number to connect them with our team for personalized assistance with novated leases.

Classify this message into ONE of these categories:
1. "contains_info" - Message contains name, email, or phone number (e.g., "My name is John Smith", "john@example.com", "0412345678")
2. "domain_question" - Question about novated leases, benefits, pricing, process, vehicles, eligibility, etc. (e.g., "What are the benefits?", "How much does it cost?")
3. "meta_question" - Questions about why we need their info, what we'll do with it, privacy concerns (e.g., "Why do you need this?", "What do you need my details for?", "Why are you asking?")
4. "other" - Greetings, unclear messages, or unrelated topics

For meta_question, also identify the reason:
- "why_need" - Asking why we need the information
- "why_asking" - Asking why we're asking for it
- "what_for" - Asking what we'll use it for
- "privacy" - Privacy or security concerns

Return ONLY valid JSON (no markdown, no code blocks):
{{
    "category": "one of: contains_info, domain_question, meta_question, other",
    "contains_info": true or false,
    "info_types": ["name", "email", "phone"] or [],
    "is_domain_question": true or false,
    "is_meta_question": true or false,
    "meta_reason": "why_need" or "why_asking" or "what_for" or "privacy" or null,
    "confidence": 0.0 to 1.0
}}"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": classification_prompt}],
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=200
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if result_text.startswith('```'):
                result_text = result_text.split('```')[1]
                if result_text.startswith('json'):
                    result_text = result_text[4:]
                result_text = result_text.strip()
            
            # Parse JSON response
            classification = json.loads(result_text)
            
            logger.info(f"[CLASSIFIER] Classification result: {classification}")
            return classification
            
        except json.JSONDecodeError as e:
            logger.error(f"[CLASSIFIER] Failed to parse JSON response: {result_text[:200]}")
            # Fallback: simple keyword-based classification
            return self._fallback_classify(user_message)
        except Exception as e:
            logger.error(f"[CLASSIFIER] Error in LLM classification: {str(e)}")
            # Fallback: simple keyword-based classification
            return self._fallback_classify(user_message)
    
    def _fallback_classify(self, user_message: str) -> Dict[str, Any]:
        """Fallback classification using keyword matching when LLM fails."""
        message_lower = user_message.lower()
        
        # Check for meta questions
        meta_keywords = ['why do you need', 'why are you asking', 'what do you need', 'what for', 'why need', 
                        'privacy', 'secure', 'safe', 'what will you do', 'how will you use']
        if any(keyword in message_lower for keyword in meta_keywords):
            meta_reason = 'why_need'
            if 'privacy' in message_lower or 'secure' in message_lower or 'safe' in message_lower:
                meta_reason = 'privacy'
            elif 'what for' in message_lower or 'what will you' in message_lower:
                meta_reason = 'what_for'
            
            return {
                'category': 'meta_question',
                'contains_info': False,
                'info_types': [],
                'is_domain_question': False,
                'is_meta_question': True,
                'meta_reason': meta_reason,
                'confidence': 0.7
            }
        
        # Check for domain question keywords
        domain_keywords = ['benefit', 'price', 'cost', 'how much', 'process', 'how', 'work', 'eligible', 
                          'vehicle', 'car', 'ev', 'lease', 'tax', 'saving', 'advantage']
        if any(keyword in message_lower for keyword in domain_keywords):
            return {
                'category': 'domain_question',
                'contains_info': False,
                'info_types': [],
                'is_domain_question': True,
                'is_meta_question': False,
                'meta_reason': None,
                'confidence': 0.7
            }
        
        # Default to other
        return {
            'category': 'other',
            'contains_info': False,
            'info_types': [],
            'is_domain_question': False,
            'is_meta_question': False,
            'meta_reason': None,
            'confidence': 0.5
        }
    
    def _get_meta_question_response(self, meta_reason: str = 'why_need') -> str:
        """
        Get response explaining why we need user info based on meta question type.
        
        Args:
            meta_reason: 'why_need', 'why_asking', 'what_for', 'privacy', or 'how_got_info'
        """
        meta_responses = {
            'why_need': "I need your contact details so I can connect you with our team. They can provide personalized assistance, answer detailed questions, and help you get started with a novated lease that's tailored to your needs.",
            'why_asking': "I'm asking for your details because our team can give you more detailed information and help you find the perfect vehicle and lease terms for your situation. They'll be able to provide personalized quotes and guide you through the entire process.",
            'what_for': "Your contact information helps us connect you with our specialists who can provide personalized quotes, answer your specific questions, and guide you through the novated lease process. We'll only use it to help you get the best lease option for your needs.",
            'privacy': "I understand your privacy concerns! Your information is secure and will only be used to connect you with our team for personalized assistance. We take data privacy seriously and will only use your details to help you with your novated lease inquiry.",
            'how_got_info': "You provided your contact details earlier in our conversation when we were collecting information to connect you with our team. I have your name, email, and phone number on file from when you shared them with me."
        }
        
        return meta_responses.get(meta_reason, meta_responses['why_need'])
    
    def _handle_connection_request_response(self, user_message: str) -> Optional[Dict[str, Any]]:
        """
        Check if user is responding to a connection request and handle accordingly.
        
        Returns:
            Response dict if handling connection response, None otherwise
        """
        try:
            # Get last few messages to check for connection request
            recent_messages = self._get_conversation_history(4)
            
            # Find the last assistant message
            last_assistant_msg = None
            for msg in reversed(recent_messages):
                if msg.get('role') == 'assistant':
                    last_assistant_msg = msg.get('content', '').lower()
                    break
            
            if not last_assistant_msg:
                return None
            
            # Check if last assistant message was asking to connect
            connection_keywords = [
                'would you like me to connect',
                'connect you with our team',
                'connect you with our specialists',
                'put you in touch',
                'connect with our team'
            ]
            
            is_connection_request = any(keyword in last_assistant_msg for keyword in connection_keywords)
            
            if not is_connection_request:
                return None
            
            logger.info(f"[CONNECTION] Detected connection request response. User message: '{user_message}'")
            
            # Classify user response
            response_type = self._classify_connection_response(user_message)
            
            logger.info(f"[CONNECTION] Response type: {response_type}")
            
            if response_type == 'confirmation':
                # User confirmed - complete the session
                conversation_data = self.session.conversation_data or {}
                conversation_data['step'] = 'complete'
                self.session.conversation_data = conversation_data
                self.session.is_active = False
                self.session.save(update_fields=['conversation_data', 'is_active'])
                
                visitor = self.session.visitor
                first_name = visitor.name.split()[0] if visitor.name else ''
                
                return {
                    'message': f"Perfect{', ' + first_name if first_name else ''}! I've submitted your details to our team. They'll be in touch with you shortly. Have a wonderful day!",
                    'suggestions': [],
                    'complete': True,
                    'needs_info': None,
                    'escalate_to': None
                }
            elif response_type == 'decline':
                # User declined - acknowledge politely
                return {
                    'message': "No problem at all! Feel free to reach out anytime if you have questions or if you'd like to connect with our team later.",
                    'suggestions': ["Tell me more about novated leases", "What are the benefits?", "How does it work?"],
                    'complete': False,
                    'needs_info': None,
                    'escalate_to': None
                }
            elif response_type == 'meta_question':
                # User asked a meta question - use LLM to understand and answer it properly
                explanation = self._answer_meta_question_with_context(user_message, recent_messages)
                
                visitor = self.session.visitor
                first_name = visitor.name.split()[0] if visitor.name else ''
                followup_message = f"I'd be happy to connect you with our team{', ' + first_name if first_name else ''}! Would you like me to proceed?"
                
                return {
                    'message': explanation,
                    'suggestions': [],
                    'complete': False,
                    'needs_info': None,
                    'escalate_to': None,
                    'followup_type': 'ask_to_connect',
                    'followup_message': followup_message
                }
            else:
                # Unclear response - ask for clarification
                return {
                    'message': "I'd be happy to connect you with our team! Just to confirm, would you like me to proceed with connecting you?",
                    'suggestions': ["Yes, connect me", "Not right now", "Tell me more first"],
                    'complete': False,
                    'needs_info': None,
                    'escalate_to': None
                }
                
        except Exception as e:
            logger.error(f"[CONNECTION] Error handling connection request response: {str(e)}", exc_info=True)
            return None
    
    def _classify_connection_response(self, user_message: str) -> str:
        """
        Classify user response to connection request.
        
        Returns:
            'confirmation', 'decline', 'meta_question', or 'unclear'
        """
        message_lower = user_message.lower().strip()
        
        # Check for meta questions FIRST (privacy/data concerns)
        meta_keywords = [
            'how do you have', 'how did you get', 'where did you get', 'why do you have',
            'how do you know', 'where did you', 'how did you', 'why do you',
            'privacy', 'data', 'information', 'details', 'contact', 'my info', 'my details',
            'how come you', 'what information', 'what data', 'what details'
        ]
        
        if any(keyword in message_lower for keyword in meta_keywords):
            return 'meta_question'
        
        # Confirmation keywords
        confirmation_keywords = [
            'yes', 'yeah', 'yep', 'yup', 'sure', 'ok', 'okay', 'alright', 'all right',
            'sounds good', 'that works', 'go ahead', 'please do', 'connect me',
            'yes please', 'sure thing', 'absolutely', 'definitely', 'of course'
        ]
        
        # Decline keywords
        decline_keywords = [
            'no', 'nope', 'not now', 'not right now', 'maybe later', 'later',
            'not yet', 'not interested', 'no thanks', 'no thank you', 'pass',
            'skip', 'not at this time'
        ]
        
        # Check for confirmation
        if any(keyword in message_lower for keyword in confirmation_keywords):
            # Make sure it's not a decline (e.g., "no, ok" should be decline)
            if not any(decline in message_lower for decline in ['no', 'not', 'nope']):
                return 'confirmation'
        
        # Check for decline
        if any(keyword in message_lower for keyword in decline_keywords):
            return 'decline'
        
        # Use LLM for ambiguous cases
        try:
            classification_prompt = f"""Classify this user response to a connection request.

User message: "{user_message}"

Context: The AI just asked "Would you like me to connect you with our team for more personalized assistance?"

Classify the response as:
1. "confirmation" - User wants to be connected (yes, ok, sure, go ahead, etc.)
2. "decline" - User doesn't want to be connected (no, not now, maybe later, etc.)
3. "meta_question" - User is asking about privacy/data/how we got their info (e.g., "How do you have my info?", "Where did you get my details?")
4. "unclear" - Ambiguous or unclear response

Return ONLY one word: confirmation, decline, meta_question, or unclear"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": classification_prompt}],
                temperature=0.1,
                max_tokens=15
            )
            
            result = response.choices[0].message.content.strip().lower()
            
            if result in ['confirmation', 'decline', 'meta_question', 'unclear']:
                return result
            
            return 'unclear'
            
        except Exception as e:
            logger.error(f"[CONNECTION] Error classifying response with LLM: {str(e)}")
            return 'unclear'
    
    def _answer_meta_question_with_context(self, user_message: str, conversation_history: list) -> str:
        """
        Use LLM to understand and answer meta questions with full conversation context.
        This intelligently answers questions like "How do you get my info?" by checking
        conversation history to see when/if user provided information.
        """
        try:
            # Get visitor info to see what we have
            visitor = self.session.visitor
            has_name = bool(visitor.name)
            has_email = bool(visitor.email)
            has_phone = bool(visitor.phone)
            
            # Format conversation history for context
            history_text = ""
            for msg in conversation_history[-6:]:  # Last 6 messages for context
                role = msg.get('role', '')
                content = msg.get('content', '')
                history_text += f"{role.upper()}: {content}\n"
            
            # Build context about what info we have
            info_summary = []
            if has_name:
                info_summary.append(f"name: {visitor.name}")
            if has_email:
                info_summary.append(f"email: {visitor.email}")
            if has_phone:
                info_summary.append(f"phone: {visitor.phone}")
            
            info_context = ", ".join(info_summary) if info_summary else "no contact information"
            
            answer_prompt = f"""You are a helpful AI assistant. A user asked you a question about their information or privacy.

User's question: "{user_message}"

Conversation history (recent messages):
{history_text}

Current information we have: {info_context}

Based on the conversation history, answer the user's question directly and accurately:
- If they're asking "How do you have/get my info?" - Check the conversation history to see if/when they provided it. If they did provide it earlier, explain that. If not, explain we're asking for it now.
- If they're asking "Why do you need my info?" - Explain why we need it (to connect with team).
- If they're asking about privacy/security - Address their concerns.
- Be direct, honest, and helpful.
- Keep it brief (2-3 sentences max).
- Don't use phrases like "I'd be happy to" or ask follow-up questions - just answer their question directly.

Answer:"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": answer_prompt}],
                temperature=0.3,  # Low temperature for accurate, consistent answers
                max_tokens=150
            )
            
            answer = response.choices[0].message.content.strip()
            
            # Remove any follow-up phrases or questions
            answer = self._clean_meta_answer(answer)
            
            logger.info(f"[META_QUESTION] Generated answer: {answer}")
            return answer
            
        except Exception as e:
            logger.error(f"[META_QUESTION] Error generating answer with LLM: {str(e)}")
            # Fallback to simple answer
            visitor = self.session.visitor
            if visitor.name or visitor.email or visitor.phone:
                return "You provided your contact details earlier in our conversation when we were collecting information. I have those details on file."
            else:
                return "I'm asking for your contact details so I can connect you with our team for personalized assistance."
    
    def _clean_meta_answer(self, answer: str) -> str:
        """Remove follow-up phrases and questions from meta question answers."""
        # Remove common follow-up phrases
        followup_phrases = [
            "would you like me to",
            "can i",
            "shall i",
            "let me know",
            "feel free to",
            "if you'd like",
            "if you want"
        ]
        
        sentences = answer.split('.')
        cleaned_sentences = []
        
        for sentence in sentences:
            sentence_lower = sentence.lower().strip()
            # Skip sentences that are follow-up questions
            if any(phrase in sentence_lower for phrase in followup_phrases):
                continue
            # Skip questions
            if '?' in sentence:
                continue
            cleaned_sentences.append(sentence.strip())
        
        result = '. '.join(cleaned_sentences)
        result = result.strip()
        
        # Remove trailing periods if multiple
        while result.endswith('..'):
            result = result[:-1]
        
        # Ensure it ends with a period
        if result and not result.endswith('.'):
            result += '.'
        
        return result if result else answer  # Return original if cleaning removed everything
    
    def _get_info_request_followup(self, visitor, user_message: str = None, context: str = None) -> tuple:
        """
        Generate dynamic follow-up message requesting missing info using LLM.
        
        Args:
            visitor: Visitor object
            user_message: The user's message for context
            context: Context type ('domain_question', 'meta_question', 'other')
        
        Returns:
            tuple: (followup_message, followup_type)
        """
        # Determine what info is still needed
        missing = []
        if not visitor.name:
            missing.append('name')
        if not visitor.email:
            missing.append('email')
        if not visitor.phone:
            missing.append('phone')
        
        # If all info collected, ask to connect
        if len(missing) == 0:
            first_name = visitor.name.split()[0] if visitor.name else ''
            followup_message = f"I have your contact details on file{', ' + first_name if first_name else ''}. Would you like me to connect you with our team for more personalized assistance?"
            followup_type = 'ask_to_connect'
            return followup_message, followup_type
        
        # Generate dynamic message using LLM
        try:
            missing_str = " and ".join(missing) if len(missing) > 1 else missing[0]
            context_info = ""
            if context == 'domain_question' and user_message:
                context_info = f" The user just asked: '{user_message[:100]}'"
            elif context == 'meta_question':
                context_info = " The user asked why we need their information."
            
            followup_prompt = f"""Generate a natural, friendly, and conversational follow-up message asking the user for their contact information.

Context: We're collecting contact details to connect the user with our team for personalized novated lease assistance.{context_info}

Missing information: {missing_str}
Number of missing fields: {len(missing)}

Requirements:
- Be natural and conversational (not robotic or template-like)
- Be friendly and helpful
- Keep it brief (1-2 sentences, max 30 words)
- Don't use phrases like "I'd love to" or "I still need" (too repetitive)
- Vary the wording naturally
- Make it feel personal and contextual

Examples of good follow-up messages:
- "To get you connected with our team, could you share your {missing_str}?"
- "I'll need your {missing_str} to connect you with our specialists who can help with that."
- "Could you provide your {missing_str} so our team can reach out with more details?"

Generate ONLY the follow-up message (no explanations, no quotes):"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": followup_prompt}],
                temperature=0.8,  # Higher temperature for more natural variation
                max_tokens=100
            )
            
            followup_message = response.choices[0].message.content.strip()
            
            # Remove quotes if present
            if followup_message.startswith('"') and followup_message.endswith('"'):
                followup_message = followup_message[1:-1]
            elif followup_message.startswith("'") and followup_message.endswith("'"):
                followup_message = followup_message[1:-1]
            
            logger.info(f"[FOLLOWUP] Generated dynamic follow-up: {followup_message}")
            followup_type = 'request_info'
            return followup_message, followup_type
            
        except Exception as e:
            logger.error(f"[FOLLOWUP] Error generating dynamic follow-up: {str(e)}")
            # Fallback to template-based message
            if len(missing) == 1:
                missing_str = missing[0]
                followup_message = f"Could you please share your {missing_str} so I can connect you with our team?"
            else:
                missing_str = " and ".join(missing)
                followup_message = f"Could you please provide your {missing_str} so I can connect you with our team?"
            
            followup_type = 'request_info'
            return followup_message, followup_type