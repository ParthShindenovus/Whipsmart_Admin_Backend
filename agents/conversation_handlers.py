"""
Conversation handlers for different conversation types: Sales, Support, and Knowledge.
Implements the multi-agent system according to requirements.
"""
import logging
import re
import json
from typing import Dict, Optional
from django.utils import timezone
from chats.models import Session
from agents.graph import get_graph
from agents.session_manager import session_manager
from agents.state import AgentState
from agents.suggestions import generate_suggestions
from agents.agent_prompts import (
    SALES_AGENT_PROMPT,
    SUPPORT_AGENT_PROMPT,
    KNOWLEDGE_AGENT_PROMPT
)
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


class SalesConversationHandler:
    """
    Sales Agent Handler.
    Collects: Name → Email → Phone → Confirmation → Complete
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.conversation_data = session.conversation_data or {}
        if 'step' not in self.conversation_data:
            self.conversation_data['step'] = 'name'
    
    def handle_message(self, user_message: str) -> Dict:
        """Process user message in sales flow."""
        # Check if session is already complete
        if self.conversation_data.get('step') == 'complete':
            return {
                'message': "Thank you! Our sales team will contact you shortly. Have a wonderful day!",
                'suggestions': [],
                'complete': True,
                'needs_info': None,
                'escalate_to': None
            }
        
        step = self.conversation_data.get('step', 'name')
        user_message_lower = user_message.lower().strip()
        
        # Handle confirmation step
        if step == 'confirmation':
            return self._handle_confirmation(user_message_lower)
        
        # Extract information from message
        name = self._extract_name(user_message) if not self.conversation_data.get('name') else None
        email = self._extract_email(user_message) if not self.conversation_data.get('email') else None
        phone = self._extract_phone(user_message) if not self.conversation_data.get('phone') else None
        
        # Handle data collection based on step
        if step == 'name':
            if name:
                return self._collect_name(name)
            elif self._is_question(user_message):
                # Answer question first, then ask for name
                answer = self._answer_question(user_message)
                return {
                    'message': f"{answer}\n\nTo connect you with our sales team, could you please provide your full name?",
                    'suggestions': [],
                    'complete': False,
                    'needs_info': 'name',
                    'escalate_to': None
                }
            else:
                return self._collect_name(user_message.strip())
        
        elif step == 'email':
            if email:
                return self._collect_email(email)
            elif self._is_question(user_message):
                answer = self._answer_question(user_message)
                return {
                    'message': f"{answer}\n\nNow, could you please provide your email address?",
                    'suggestions': [],
                    'complete': False,
                    'needs_info': 'email',
                    'escalate_to': None
                }
            else:
                return self._collect_email(user_message.strip())
        
        elif step == 'phone':
            if phone:
                return self._collect_phone(phone)
            elif self._is_question(user_message):
                answer = self._answer_question(user_message)
                return {
                    'message': f"{answer}\n\nFinally, could you please provide your phone number?",
                    'suggestions': [],
                    'complete': False,
                    'needs_info': 'phone',
                    'escalate_to': None
                }
            else:
                return self._collect_phone(user_message.strip())
        
        else:
            # Fallback: start from name
            return self._collect_name(user_message.strip() if not name else name)
    
    def _collect_name(self, name: str) -> Dict:
        """Collect user's name."""
        name = name.strip()
        if len(name) < 2:
            return {
                'message': "Could you please provide your full name?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'name',
                'escalate_to': None
            }
        
        self.conversation_data['name'] = name
        self.conversation_data['step'] = 'email'
        self._save_conversation_data()
        
        return {
            'message': f"Thank you, {name}! Could you please provide your email address?",
            'suggestions': [],
            'complete': False,
            'needs_info': 'email',
            'escalate_to': None
        }
    
    def _collect_email(self, email: str) -> Dict:
        """Collect user's email."""
        email = email.strip().lower()
        if '@' not in email or '.' not in email.split('@')[-1]:
            return {
                'message': "Please provide a valid email address (e.g., name@example.com).",
                'suggestions': [],
                'complete': False,
                'needs_info': 'email',
                'escalate_to': None
            }
        
        self.conversation_data['email'] = email
        self.conversation_data['step'] = 'phone'
        self._save_conversation_data()
        
        return {
            'message': "Perfect! Now, could you please provide your phone number?",
            'suggestions': [],
            'complete': False,
            'needs_info': 'phone',
            'escalate_to': None
        }
    
    def _collect_phone(self, phone: str) -> Dict:
        """Collect user's phone number."""
        digits_only = ''.join(filter(str.isdigit, phone))
        if len(digits_only) < 10:
            return {
                'message': "Please provide a valid phone number (at least 10 digits).",
                'suggestions': [],
                'complete': False,
                'needs_info': 'phone',
                'escalate_to': None
            }
        
        self.conversation_data['phone'] = phone.strip()
        self.conversation_data['step'] = 'confirmation'
        self._save_conversation_data()
        
        # Show confirmation message
        name = self.conversation_data.get('name', '')
        email = self.conversation_data.get('email', '')
        phone = self.conversation_data.get('phone', '')
        
        return {
            'message': f"""Here is what I have collected:
Name: {name}
Email: {email}
Phone: {phone}
Is this correct? (Yes/No)""",
            'suggestions': [],
            'complete': False,
            'needs_info': 'confirmation',
            'escalate_to': None
        }
    
    def _handle_confirmation(self, user_input: str) -> Dict:
        """Handle confirmation Yes/No."""
        if 'yes' in user_input or 'correct' in user_input or 'yep' in user_input or 'yeah' in user_input:
            self.conversation_data['step'] = 'complete'
            self._save_conversation_data()
            # Lock session
            self.session.is_active = False
            self.session.save(update_fields=['is_active', 'conversation_data'])
            
            return {
                'message': "Thank you! Our sales team will contact you shortly. Have a wonderful day!",
                'suggestions': [],
                'complete': True,
                'needs_info': None,
                'escalate_to': None
            }
        elif 'no' in user_input or 'incorrect' in user_input or 'wrong' in user_input or 'nope' in user_input:
            # Ask which field is incorrect
            return {
                'message': "Thank you for letting me know. Which field is incorrect? Please provide the correct information.",
                'suggestions': [],
                'complete': False,
                'needs_info': 'confirmation',
                'escalate_to': None
            }
        else:
            return {
                'message': "Please confirm with 'Yes' or 'No'. Is the information correct?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'confirmation',
                'escalate_to': None
            }
    
    def _answer_question(self, question: str) -> str:
        """Answer question using knowledge base."""
        try:
            agent_state = session_manager.get_or_create_agent_state(str(self.session.id))
            agent_state.messages.append({"role": "user", "content": question})
            
            graph = get_graph()
            final_state_dict = graph.invoke(agent_state.to_dict())
            final_state = AgentState.from_dict(final_state_dict)
            
            assistant_message = ""
            for msg in reversed(final_state.messages):
                if msg.get("role") == "assistant":
                    assistant_message = msg.get("content", "")
                    break
            
            session_manager.save_state(str(self.session.id), final_state)
            return assistant_message
        except Exception as e:
            logger.error(f"Error answering question: {str(e)}")
            return "I'd be happy to help with that. Let me connect you with our sales team for more details."
    
    def _is_question(self, text: str) -> bool:
        """Check if text is a question."""
        question_words = ['what', 'how', 'why', 'when', 'where', 'who', 'which', 'can', 'could', 'would', 'should']
        text_lower = text.lower().strip()
        return text_lower.endswith('?') or any(text_lower.startswith(word) for word in question_words)
    
    def _extract_name(self, text: str) -> Optional[str]:
        """Extract name from text."""
        text = text.strip()
        if len(text.split()) <= 3 and '@' not in text and not re.search(r'\d{10,}', text):
            return text
        return None
    
    def _extract_email(self, text: str) -> Optional[str]:
        """Extract email from text."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, text)
        return match.group(0).lower() if match else None
    
    def _extract_phone(self, text: str) -> Optional[str]:
        """Extract phone number from text."""
        digits = re.sub(r'[\s\-\(\)\+]', '', text)
        if len(re.findall(r'\d', digits)) >= 10:
            return text.strip()
        return None
    
    def _save_conversation_data(self):
        """Save conversation data to session."""
        self.session.conversation_data = self.conversation_data
        self.session.save(update_fields=['conversation_data'])


class SupportConversationHandler:
    """
    Support Agent Handler.
    Collects: Name → Issue → Email → Confirmation → Complete
    Starts with Name collection (initial message asks for name).
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.conversation_data = session.conversation_data or {}
        if 'step' not in self.conversation_data:
            self.conversation_data['step'] = 'name'
    
    def handle_message(self, user_message: str) -> Dict:
        """Process user message in support flow."""
        # Check if session is already complete
        if self.conversation_data.get('step') == 'complete':
            return {
                'message': "Thank you! Our support team will contact you shortly.",
                'suggestions': [],
                'complete': True,
                'needs_info': None,
                'escalate_to': None
            }
        
        step = self.conversation_data.get('step', 'name')
        user_message_lower = user_message.lower().strip()
        
        # Handle confirmation step
        if step == 'confirmation':
            return self._handle_confirmation(user_message_lower)
        
        # Extract information
        issue = self.conversation_data.get('issue')
        name = self._extract_name(user_message) if not self.conversation_data.get('name') else None
        email = self._extract_email(user_message) if not self.conversation_data.get('email') else None
        
        # Handle data collection
        if step == 'name':
            if name:
                return self._collect_name(name)
            elif self._is_question(user_message):
                answer = self._answer_question(user_message)
                return {
                    'message': f"{answer}\n\nTo help our support team assist you better, could you please provide your name?",
                    'suggestions': [],
                    'complete': False,
                    'needs_info': 'name',
                    'escalate_to': None
                }
            else:
                return self._collect_name(user_message.strip())
        
        elif step == 'issue':
            if not issue:
                issue_text = user_message.strip()
                if len(issue_text) < 10:
                    return {
                        'message': "I'm here to help. Could you please describe the issue you're experiencing in more detail?",
                        'suggestions': [],
                        'complete': False,
                        'needs_info': 'issue',
                        'escalate_to': None
                    }
                return self._collect_issue(issue_text)
            elif self._is_question(user_message):
                answer = self._answer_question(user_message)
                return {
                    'message': f"{answer}\n\nCould you please describe the issue you're experiencing?",
                    'suggestions': [],
                    'complete': False,
                    'needs_info': 'issue',
                    'escalate_to': None
                }
            else:
                return self._collect_issue(user_message.strip())
        
        elif step == 'email':
            if email:
                return self._collect_email(email)
            elif self._is_question(user_message):
                answer = self._answer_question(user_message)
                return {
                    'message': f"{answer}\n\nNow, could you please provide your email address?",
                    'suggestions': [],
                    'complete': False,
                    'needs_info': 'email',
                    'escalate_to': None
                }
            else:
                return self._collect_email(user_message.strip())
        
        else:
            return self._collect_issue(user_message.strip())
    
    def _collect_issue(self, issue: str) -> Dict:
        """Collect issue description."""
        issue = issue.strip()
        if len(issue) < 10:
            return {
                'message': "Could you please describe the issue in more detail?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'issue',
                'escalate_to': None
            }
        
        self.conversation_data['issue'] = issue
        self.conversation_data['step'] = 'email'
        self._save_conversation_data()
        
        return {
            'message': "Thank you for describing the issue. Now, could you please provide your email address so our support team can contact you?",
            'suggestions': [],
            'complete': False,
            'needs_info': 'email',
            'escalate_to': None
        }
    
    def _collect_name(self, name: str) -> Dict:
        """Collect user's name."""
        name = name.strip()
        if len(name) < 2:
            return {
                'message': "Could you please provide your name?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'name',
                'escalate_to': None
            }
        
        self.conversation_data['name'] = name
        self.conversation_data['step'] = 'issue'
        self._save_conversation_data()
        
        return {
            'message': f"Thank you, {name}! Could you please describe the issue you're experiencing?",
            'suggestions': [],
            'complete': False,
            'needs_info': 'issue',
            'escalate_to': None
        }
    
    def _collect_email(self, email: str) -> Dict:
        """Collect user's email."""
        email = email.strip().lower()
        if '@' not in email or '.' not in email.split('@')[-1]:
            return {
                'message': "Please provide a valid email address (e.g., name@example.com).",
                'suggestions': [],
                'complete': False,
                'needs_info': 'email',
                'escalate_to': None
            }
        
        self.conversation_data['email'] = email
        self.conversation_data['step'] = 'confirmation'
        self._save_conversation_data()
        
        issue = self.conversation_data.get('issue', '')
        name = self.conversation_data.get('name', '')
        email = self.conversation_data.get('email', '')
        
        return {
            'message': f"""Here is what I have collected:
Issue: {issue}
Name: {name}
Email: {email}
Is this correct? (Yes/No)""",
            'suggestions': [],
            'complete': False,
            'needs_info': 'confirmation',
            'escalate_to': None
        }
    
    def _handle_confirmation(self, user_input: str) -> Dict:
        """Handle confirmation Yes/No."""
        if 'yes' in user_input or 'correct' in user_input or 'yep' in user_input or 'yeah' in user_input:
            self.conversation_data['step'] = 'complete'
            self._save_conversation_data()
            # Lock session
            self.session.is_active = False
            self.session.save(update_fields=['is_active', 'conversation_data'])
            
            return {
                'message': "Thank you! Our support team will contact you shortly.",
                'suggestions': [],
                'complete': True,
                'needs_info': None,
                'escalate_to': None
            }
        elif 'no' in user_input or 'incorrect' in user_input or 'wrong' in user_input or 'nope' in user_input:
            return {
                'message': "Thank you. Please provide the correct information for the field that is incorrect.",
                'suggestions': [],
                'complete': False,
                'needs_info': 'confirmation',
                'escalate_to': None
            }
        else:
            return {
                'message': "Please confirm with 'Yes' or 'No'. Is the information correct?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'confirmation',
                'escalate_to': None
            }
    
    def _answer_question(self, question: str) -> str:
        """Answer question using knowledge base with Support Agent prompt."""
        try:
            agent_state = session_manager.get_or_create_agent_state(str(self.session.id))
            
            # Inject Support Agent system prompt
            system_prompt = SUPPORT_AGENT_PROMPT.format(
                step=self.conversation_data.get('step', 'issue'),
                issue=self.conversation_data.get('issue', ''),
                name=self.conversation_data.get('name', ''),
                email=self.conversation_data.get('email', '')
            )
            
            # Replace system message with agent-specific prompt
            messages = [{"role": "system", "content": system_prompt}]
            for msg in agent_state.messages:
                if msg.get("role") != "system":
                    messages.append(msg)
            messages.append({"role": "user", "content": question})
            
            # Use knowledge base agent but with Support prompt
            graph = get_graph()
            original_messages = agent_state.messages
            agent_state.messages = messages
            final_state_dict = graph.invoke(agent_state.to_dict())
            final_state = AgentState.from_dict(final_state_dict)
            agent_state.messages = original_messages
            
            assistant_message = ""
            for msg in reversed(final_state.messages):
                if msg.get("role") == "assistant":
                    assistant_message = msg.get("content", "")
                    break
            
            agent_state.messages.append({"role": "user", "content": question})
            agent_state.messages.append({"role": "assistant", "content": assistant_message})
            session_manager.save_state(str(self.session.id), agent_state)
            
            return assistant_message
        except Exception as e:
            logger.error(f"Error answering question: {str(e)}")
            return "I understand your concern. Let me help you with that."
    
    def _is_question(self, text: str) -> bool:
        """Check if text is a question."""
        question_words = ['what', 'how', 'why', 'when', 'where', 'who', 'which', 'can', 'could', 'would', 'should']
        text_lower = text.lower().strip()
        return text_lower.endswith('?') or any(text_lower.startswith(word) for word in question_words)
    
    def _extract_name(self, text: str) -> Optional[str]:
        """Extract name from text."""
        text = text.strip()
        if len(text.split()) <= 3 and '@' not in text:
            return text
        return None
    
    def _extract_email(self, text: str) -> Optional[str]:
        """Extract email from text."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, text)
        return match.group(0).lower() if match else None
    
    def _save_conversation_data(self):
        """Save conversation data to session."""
        self.session.conversation_data = self.conversation_data
        self.session.save(update_fields=['conversation_data'])


class KnowledgeConversationHandler:
    """
    Knowledge Agent Handler.
    Answers questions and can escalate to Sales.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.conversation_data = session.conversation_data or {}
        if 'step' not in self.conversation_data:
            self.conversation_data['step'] = 'chatting'
    
    def handle_message(self, user_message: str) -> Dict:
        """Process user message in knowledge flow."""
        user_message_lower = user_message.lower().strip()
        
        # Check for sales escalation intent
        escalation_keywords = [
            'pricing', 'price', 'cost', 'plan', 'plans', 'onboarding', 'setup', 
            'consultation', 'implementation', 'enterprise', 'sign up', 'get started',
            'speak with', 'talk to', 'contact sales', 'sales team', 'sales person',
            'want to buy', 'interested in', 'purchase', 'buy'
        ]
        
        # Check if user wants to escalate to sales
        if any(keyword in user_message_lower for keyword in escalation_keywords):
            # Check if we're already in escalation mode
            if self.conversation_data.get('escalation_pending'):
                # User agreed to escalation
                if any(word in user_message_lower for word in ['yes', 'sure', 'okay', 'please', 'go ahead', 'connect', 'yes please']):
                    return self._escalate_to_sales()
                else:
                    # User declined, continue answering
                    self.conversation_data['escalation_pending'] = False
                    self._save_conversation_data()
            else:
                # Suggest sales escalation
                self.conversation_data['escalation_pending'] = True
                self._save_conversation_data()
                return {
                    'message': "I can connect you directly with our sales team to guide you personally. Would you like me to do that?",
                    'suggestions': [],
                    'complete': False,
                    'needs_info': None,
                    'escalate_to': None
                }
        
        # Handle normal Q&A
        try:
            agent_state = session_manager.get_or_create_agent_state(str(self.session.id))
            
            # Inject Knowledge Agent system prompt
            system_prompt = KNOWLEDGE_AGENT_PROMPT
            
            # Replace system message with agent-specific prompt
            messages = [{"role": "system", "content": system_prompt}]
            for msg in agent_state.messages:
                if msg.get("role") != "system":
                    messages.append(msg)
            messages.append({"role": "user", "content": user_message})
            
            # Use knowledge base agent with Knowledge prompt
            graph = get_graph()
            original_messages = agent_state.messages
            agent_state.messages = messages
            final_state_dict = graph.invoke(agent_state.to_dict())
            final_state = AgentState.from_dict(final_state_dict)
            agent_state.messages = original_messages
            
            assistant_message = ""
            for msg in reversed(final_state.messages):
                if msg.get("role") == "assistant":
                    assistant_message = msg.get("content", "")
                    break
            
            # Save state (without system prompt in history)
            agent_state.messages.append({"role": "user", "content": user_message})
            agent_state.messages.append({"role": "assistant", "content": assistant_message})
            session_manager.save_state(str(self.session.id), agent_state)
            
            # Generate suggestions
            suggestions = generate_suggestions(
                conversation_messages=final_state.messages,
                last_bot_message=assistant_message,
                max_suggestions=5
            )
            
            return {
                'message': assistant_message,
                'suggestions': suggestions,
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
        except Exception as e:
            logger.error(f"Error in knowledge conversation: {str(e)}", exc_info=True)
            return {
                'message': "I apologize, but I encountered an error. Please try again.",
                'suggestions': [],
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
    
    def _escalate_to_sales(self) -> Dict:
        """Escalate conversation to Sales agent."""
        # Reset conversation data for sales flow
        self.session.conversation_type = 'sales'
        self.session.conversation_data = {
            'step': 'name',
            'name': None,
            'email': None,
            'phone': None
        }
        self.session.save(update_fields=['conversation_type', 'conversation_data'])
        
        return {
            'message': "Great! I am now connecting you with our Sales Team.\n\nTo get started, could you please provide your full name?",
            'suggestions': [],
            'complete': False,
            'needs_info': 'name',
            'escalate_to': 'sales'
        }
    
    def _save_conversation_data(self):
        """Save conversation data to session."""
        self.session.conversation_data = self.conversation_data
        self.session.save(update_fields=['conversation_data'])
