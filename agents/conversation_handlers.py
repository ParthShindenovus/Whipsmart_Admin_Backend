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
    Sales Agent Handler using LLM with function calling.
    Collects: Name → Email → Phone → Confirmation → Submit Lead → Complete
    Uses LLM tools to extract, validate, and submit lead information.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.conversation_data = session.conversation_data or {}
        if 'step' not in self.conversation_data:
            self.conversation_data['step'] = 'collecting'
    
    def handle_message(self, user_message: str) -> Dict:
        """Process user message using LLM with function calling."""
        # Check if session is already complete
        if self.conversation_data.get('step') == 'complete':
            return {
                'message': "Thank you! Our sales team will contact you shortly. Have a wonderful day!",
                'suggestions': [],
                'complete': True,
                'needs_info': None,
                'escalate_to': None
            }
        
        # Use LLM with function calling to understand intent and call appropriate tools
        return self._process_with_llm_tools(user_message)
    
    def _collect_name(self, name: str) -> Dict:
        """Collect user's name."""
        name = name.strip()
        if not self._validate_name(name):
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
        if not self._validate_email(email):
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
        phone = phone.strip()
        if not self._validate_phone(phone):
            return {
                'message': "Please provide a valid phone number (at least 10 digits).",
                'suggestions': [],
                'complete': False,
                'needs_info': 'phone',
                'escalate_to': None
            }
        
        self.conversation_data['phone'] = phone
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
    
    def _extract_info_with_llm(self, user_message: str) -> Dict:
        """Use LLM to extract name, email, and phone from natural language message."""
        client, model = _get_openai_client()
        if not client or not model:
            # Fallback to regex extraction
            return {
                'name': self._extract_name(user_message),
                'email': self._extract_email(user_message),
                'phone': self._extract_phone(user_message)
            }
        
        try:
            prompt = f"""Extract personal information from the following user message. Return ONLY valid JSON with the extracted information.

User message: "{user_message}"

Extract:
- name: Full name if mentioned (e.g., "John Doe", "Jane Smith")
- email: Email address if mentioned (must contain @ and domain)
- phone: Phone number if mentioned (must have at least 10 digits)

Return JSON format:
{{
    "name": "extracted name or null",
    "email": "extracted email or null",
    "phone": "extracted phone or null"
}}

If information is not found, use null. Only extract if clearly present in the message."""
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=256,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            return {
                'name': result.get('name') if result.get('name') and result.get('name') != 'null' else None,
                'email': result.get('email') if result.get('email') and result.get('email') != 'null' else None,
                'phone': result.get('phone') if result.get('phone') and result.get('phone') != 'null' else None
            }
        except Exception as e:
            logger.error(f"Error extracting info with LLM: {str(e)}")
            # Fallback to regex extraction
            return {
                'name': self._extract_name(user_message),
                'email': self._extract_email(user_message),
                'phone': self._extract_phone(user_message)
            }
    
    def _extract_corrections_with_llm(self, user_message: str) -> Dict:
        """Use LLM to extract corrections from user message during confirmation."""
        client, model = _get_openai_client()
        if not client or not model:
            return {}
        
        try:
            current_name = self.conversation_data.get('name', '')
            current_email = self.conversation_data.get('email', '')
            current_phone = self.conversation_data.get('phone', '')
            
            prompt = f"""The user is correcting their information. Extract the corrected values from their message.

Current information:
- Name: {current_name}
- Email: {current_email}
- Phone: {current_phone}

User's correction message: "{user_message}"

Extract any corrected values. The user might say things like:
- "Name field my name is dhruv" -> name should be "dhruv"
- "Email is wrong, it's new@email.com" -> email should be "new@email.com"
- "Phone number is 1234567890" -> phone should be "1234567890"
- "name" or "the name" -> they're indicating which field, but not providing new value yet

Return JSON format:
{{
    "name": "corrected name or null",
    "email": "corrected email or null",
    "phone": "corrected phone or null"
}}

Only extract if a NEW value is provided. If user only mentions the field name without a new value, return null for that field."""
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=256,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            return {
                'name': result.get('name') if result.get('name') and result.get('name') != 'null' else None,
                'email': result.get('email') if result.get('email') and result.get('email') != 'null' else None,
                'phone': result.get('phone') if result.get('phone') and result.get('phone') != 'null' else None
            }
        except Exception as e:
            logger.error(f"Error extracting corrections with LLM: {str(e)}")
            return {}
    
    def _extract_name(self, text: str) -> Optional[str]:
        """Extract name from text using regex fallback."""
        text = text.strip()
        # Remove common prefixes
        text = re.sub(r'^(name|my name is|i am|i\'m|this is)\s*:?\s*', '', text, flags=re.IGNORECASE)
        text = text.strip()
        # Check if it looks like a name (2-4 words, no @, no long digit sequences)
        if len(text.split()) <= 4 and '@' not in text and not re.search(r'\d{10,}', text) and len(text) >= 2:
            return text
        return None
    
    def _extract_email(self, text: str) -> Optional[str]:
        """Extract email from text using regex."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, text)
        return match.group(0).lower() if match else None
    
    def _extract_phone(self, text: str) -> Optional[str]:
        """Extract phone number from text using regex."""
        # Remove common prefixes
        text = re.sub(r'^(phone|number|contact|mobile|cell)\s*:?\s*', '', text, flags=re.IGNORECASE)
        # Extract digits
        digits = re.sub(r'[\s\-\(\)\+\.]', '', text)
        if len(re.findall(r'\d', digits)) >= 10:
            return text.strip()
        return None
    
    def _validate_name(self, name: str) -> bool:
        """Validate name."""
        if not name or len(name.strip()) < 2:
            return False
        # Name should not contain email or phone patterns
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
    
    def _check_and_advance_step(self) -> Dict:
        """Check if all fields are collected and advance to next step or confirmation."""
        name = self.conversation_data.get('name')
        email = self.conversation_data.get('email')
        phone = self.conversation_data.get('phone')
        
        # Determine what's missing
        if not name:
            return self._get_next_field_prompt(None)
        elif not email:
            return {
                'message': f"Thank you, {name}! Could you please provide your email address?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'email',
                'escalate_to': None
            }
        elif not phone:
            return {
                'message': "Perfect! Now, could you please provide your phone number?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'phone',
                'escalate_to': None
            }
        else:
            # All fields collected, show confirmation
            self.conversation_data['step'] = 'confirmation'
            self._save_conversation_data()
            
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
    
    def _process_with_llm_tools(self, user_message: str) -> Dict:
        """Process message using LLM with function calling tools."""
        client, model = _get_openai_client()
        if not client or not model:
            return {
                'message': "I apologize, but the AI service is currently unavailable. Please try again later.",
                'suggestions': [],
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
        
        # Get current state
        current_name = self.conversation_data.get('name', '')
        current_email = self.conversation_data.get('email', '')
        current_phone = self.conversation_data.get('phone', '')
        step = self.conversation_data.get('step', 'collecting')
        
        # Build system prompt with current state
        system_prompt = SALES_AGENT_PROMPT.format(
            step=step,
            name=current_name,
            email=current_email,
            phone=current_phone
        )
        
        # Define tools (functions) for the LLM to call
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "extract_and_store_info",
                    "description": "Extract name, email, or phone number from user message and store it. Use this when user provides information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Full name if provided in the message, otherwise null"
                            },
                            "email": {
                                "type": "string",
                                "description": "Email address if provided in the message, otherwise null"
                            },
                            "phone": {
                                "type": "string",
                                "description": "Phone number if provided in the message, otherwise null"
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_field",
                    "description": "Update a specific field when user corrects information during confirmation. Use this when user says a field is incorrect and provides new value.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "field": {
                                "type": "string",
                                "enum": ["name", "email", "phone"],
                                "description": "The field to update"
                            },
                            "value": {
                                "type": "string",
                                "description": "The new value for the field"
                            }
                        },
                        "required": ["field", "value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_lead",
                    "description": "Submit the lead when all information is collected and confirmed. Only call this when user confirms with 'yes' and all fields (name, email, phone) are present.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_for_field",
                    "description": "Ask user for a specific missing field. Use this when a field is missing and user hasn't provided it.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "field": {
                                "type": "string",
                                "enum": ["name", "email", "phone"],
                                "description": "The field to ask for"
                            }
                        },
                        "required": ["field"]
                    }
                }
            }
        ]
        
        # Build conversation history
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        try:
            # Call LLM with function calling
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",  # Let LLM decide which tool to call
                temperature=0.3
            )
            
            message = response.choices[0].message
            
            # Check if LLM wants to call a tool
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                # Execute the tool
                tool_result = self._execute_tool(function_name, function_args)
                
                # Get LLM response after tool execution
                messages.append(message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result)
                })
                
                # Get final response from LLM
                final_response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=256
                )
                
                assistant_message = final_response.choices[0].message.content.strip()
                
                # Check if lead was submitted
                if function_name == "submit_lead" and tool_result.get("success"):
                    self.conversation_data['step'] = 'complete'
                    self.session.is_active = False
                    self._save_conversation_data()
                    self.session.save(update_fields=['is_active', 'conversation_data'])
                    
                    return {
                        'message': assistant_message,
                        'suggestions': [],
                        'complete': True,
                        'needs_info': None,
                        'escalate_to': None
                    }
                
                # Determine what info is still needed
                needs_info = None
                if not self.conversation_data.get('name'):
                    needs_info = 'name'
                elif not self.conversation_data.get('email'):
                    needs_info = 'email'
                elif not self.conversation_data.get('phone'):
                    needs_info = 'phone'
                elif step != 'complete':
                    needs_info = 'confirmation'
                
                return {
                    'message': assistant_message,
                    'suggestions': [],
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None
                }
            else:
                # LLM responded directly without calling tools
                assistant_message = message.content.strip()
                
                # Determine what info is still needed
                needs_info = None
                if not self.conversation_data.get('name'):
                    needs_info = 'name'
                elif not self.conversation_data.get('email'):
                    needs_info = 'email'
                elif not self.conversation_data.get('phone'):
                    needs_info = 'phone'
                elif step != 'complete':
                    needs_info = 'confirmation'
                
                return {
                    'message': assistant_message,
                    'suggestions': [],
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None
                }
                
        except Exception as e:
            logger.error(f"Error in LLM tool processing: {str(e)}", exc_info=True)
            return {
                'message': "I apologize, but I encountered an error. Please try again.",
                'suggestions': [],
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
    
    def _execute_tool(self, function_name: str, args: Dict) -> Dict:
        """Execute a tool function and return result."""
        try:
            if function_name == "extract_and_store_info":
                return self._tool_extract_and_store_info(args)
            elif function_name == "update_field":
                return self._tool_update_field(args)
            elif function_name == "submit_lead":
                return self._tool_submit_lead()
            elif function_name == "ask_for_field":
                return self._tool_ask_for_field(args)
            else:
                return {"error": f"Unknown tool: {function_name}"}
        except Exception as e:
            logger.error(f"Error executing tool {function_name}: {str(e)}", exc_info=True)
            return {"error": str(e)}
    
    def _tool_extract_and_store_info(self, args: Dict) -> Dict:
        """Extract and store information from user message."""
        updated_fields = []
        
        # Extract and validate name
        if args.get('name') and not self.conversation_data.get('name'):
            name = args['name'].strip()
            if self._validate_name(name):
                self.conversation_data['name'] = name
                updated_fields.append('name')
                logger.info(f"[SALES TOOL] Stored name: {name}")
        
        # Extract and validate email
        if args.get('email') and not self.conversation_data.get('email'):
            email = args['email'].strip().lower()
            if self._validate_email(email):
                self.conversation_data['email'] = email
                updated_fields.append('email')
                logger.info(f"[SALES TOOL] Stored email: {email}")
        
        # Extract and validate phone
        if args.get('phone') and not self.conversation_data.get('phone'):
            phone = args['phone'].strip()
            if self._validate_phone(phone):
                self.conversation_data['phone'] = phone
                updated_fields.append('phone')
                logger.info(f"[SALES TOOL] Stored phone: {phone}")
        
        # Update step if needed
        if self.conversation_data.get('name') and self.conversation_data.get('email') and self.conversation_data.get('phone'):
            if self.conversation_data.get('step') != 'confirmation':
                self.conversation_data['step'] = 'confirmation'
        
        self._save_conversation_data()
        
        return {
            "success": True,
            "updated_fields": updated_fields,
            "current_data": {
                "name": self.conversation_data.get('name', ''),
                "email": self.conversation_data.get('email', ''),
                "phone": self.conversation_data.get('phone', '')
            },
            "missing_fields": self._get_missing_fields()
        }
    
    def _tool_update_field(self, args: Dict) -> Dict:
        """Update a specific field during confirmation."""
        field = args.get('field')
        value = args.get('value', '').strip()
        
        if not field or not value:
            return {"error": "Field and value are required"}
        
        # Validate based on field type
        if field == 'name':
            if not self._validate_name(value):
                return {"error": "Invalid name format"}
            self.conversation_data['name'] = value
        elif field == 'email':
            if not self._validate_email(value):
                return {"error": "Invalid email format"}
            self.conversation_data['email'] = value.lower()
        elif field == 'phone':
            if not self._validate_phone(value):
                return {"error": "Invalid phone format"}
            self.conversation_data['phone'] = value
        else:
            return {"error": f"Unknown field: {field}"}
        
        self._save_conversation_data()
        logger.info(f"[SALES TOOL] Updated {field} to: {value}")
        
        return {
            "success": True,
            "updated_field": field,
            "current_data": {
                "name": self.conversation_data.get('name', ''),
                "email": self.conversation_data.get('email', ''),
                "phone": self.conversation_data.get('phone', '')
            }
        }
    
    def _tool_submit_lead(self) -> Dict:
        """Submit the lead - logs and completes session."""
        name = self.conversation_data.get('name', '')
        email = self.conversation_data.get('email', '')
        phone = self.conversation_data.get('phone', '')
        
        # Validate all fields are present
        if not name or not email or not phone:
            return {
                "error": "Cannot submit lead: missing required fields",
                "missing_fields": self._get_missing_fields()
            }
        
        # Log the lead submission
        logger.info("=" * 80)
        logger.info("[SALES TOOL] SUBMITTING LEAD:")
        logger.info(f"  Name: {name}")
        logger.info(f"  Email: {email}")
        logger.info(f"  Phone: {phone}")
        logger.info(f"  Session ID: {self.session.id}")
        logger.info("=" * 80)
        
        # Mark as complete
        self.conversation_data['step'] = 'complete'
        self.conversation_data['submitted_at'] = timezone.now().isoformat()
        self._save_conversation_data()
        
        # Lock session
        self.session.is_active = False
        self.session.save(update_fields=['is_active', 'conversation_data'])
        
        return {
            "success": True,
            "message": "Lead submitted successfully",
            "lead_data": {
                "name": name,
                "email": email,
                "phone": phone
            }
        }
    
    def _tool_ask_for_field(self, args: Dict) -> Dict:
        """Ask user for a specific field."""
        field = args.get('field')
        
        if field == 'name':
            return {
                "message": "To connect you with our sales team, could you please provide your full name?",
                "field": "name"
            }
        elif field == 'email':
            name = self.conversation_data.get('name', '')
            greeting = f"Thank you, {name}! " if name else ""
            return {
                "message": f"{greeting}Could you please provide your email address?",
                "field": "email"
            }
        elif field == 'phone':
            return {
                "message": "Perfect! Now, could you please provide your phone number?",
                "field": "phone"
            }
        else:
            return {"error": f"Unknown field: {field}"}
    
    def _get_missing_fields(self) -> list:
        """Get list of missing required fields."""
        missing = []
        if not self.conversation_data.get('name'):
            missing.append('name')
        if not self.conversation_data.get('email'):
            missing.append('email')
        if not self.conversation_data.get('phone'):
            missing.append('phone')
        return missing
        """Get prompt for the next field that needs to be collected."""
        name = self.conversation_data.get('name')
        email = self.conversation_data.get('email')
        phone = self.conversation_data.get('phone')
        
        prefix = f"{answer}\n\n" if answer else ""
        
        if not name:
            self.conversation_data['step'] = 'name'
            self._save_conversation_data()
            return {
                'message': f"{prefix}To connect you with our sales team, could you please provide your full name?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'name',
                'escalate_to': None
            }
        elif not email:
            self.conversation_data['step'] = 'email'
            self._save_conversation_data()
            return {
                'message': f"{prefix}Could you please provide your email address?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'email',
                'escalate_to': None
            }
        elif not phone:
            self.conversation_data['step'] = 'phone'
            self._save_conversation_data()
            return {
                'message': f"{prefix}Finally, could you please provide your phone number?",
                'suggestions': [],
                'complete': False,
                'needs_info': 'phone',
                'escalate_to': None
            }
        else:
            # All collected, show confirmation
            self.conversation_data['step'] = 'confirmation'
            self._save_conversation_data()
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
            
            # Get user's name for personalization
            user_name = self.conversation_data.get('name', '')
            
            # Inject Support Agent system prompt
            system_prompt = SUPPORT_AGENT_PROMPT.format(
                step=self.conversation_data.get('step', 'issue'),
                issue=self.conversation_data.get('issue', ''),
                name=user_name,
                email=self.conversation_data.get('email', '')
            )
            
            # Add personalization instruction if name is known
            if user_name:
                system_prompt += f"""

USER PERSONALIZATION:
- The user's name is: {user_name}
- ALWAYS address them by name naturally in your responses (e.g., "Great question, {user_name}!", "{user_name}, let me help with that:")
- Use their name once per response to make the conversation more formal and personalized
"""
            
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
            
            # Get user's name from conversation data for personalization
            user_name = self.conversation_data.get('name', '')
            
            # Inject Knowledge Agent system prompt with personalization
            system_prompt = KNOWLEDGE_AGENT_PROMPT
            if user_name:
                # Add personalization instruction with user's name
                system_prompt += f"""

USER PERSONALIZATION:
- The user's name is: {user_name}
- ALWAYS address them by name naturally in your responses (e.g., "Great question, {user_name}!", "Here's what I found, {user_name}:")
- Use their name once per response to make the conversation more formal and personalized
"""
            
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
