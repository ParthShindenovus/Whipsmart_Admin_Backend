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
            
            # Generate suggestions (but not for user_action questions or when actively collecting info)
            if state.question_type == 'user_action':
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
