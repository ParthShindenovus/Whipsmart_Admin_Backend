"""
Unified Main Agent - Handles all conversation types with intelligent routing.
Uses LLM function calling to route to appropriate handlers and tools.
"""
import logging
import json
import re
from typing import Dict, Optional
from django.utils import timezone
from chats.models import Session
from agents.graph import get_graph
from agents.session_manager import session_manager
from agents.state import AgentState
from agents.tools.rag_tool import rag_tool_node
from agents.tools.car_tool import car_tool_node
from agents.agent_prompts import KNOWLEDGE_AGENT_PROMPT
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


class UnifiedAgent:
    """
    Unified Main Agent that handles all conversation types.
    Routes intelligently to sales/support/knowledge based on user intent.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.conversation_data = session.conversation_data or {}
    
    def handle_message(self, user_message: str) -> Dict:
        """Process user message using LLM with function calling tools."""
        client, model = _get_openai_client()
        if not client or not model:
            return {
                'message': "I apologize, but the AI service is currently unavailable. Please try again later.",
                'suggestions': [],
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
        
        # Check if session is complete
        if self.conversation_data.get('step') == 'complete':
            return {
                'message': "Thank you! Our team will contact you shortly. Have a wonderful day!",
                'suggestions': [],
                'complete': True,
                'needs_info': None,
                'escalate_to': None
            }
        
        # Get current state
        current_name = self.conversation_data.get('name', '')
        current_email = self.conversation_data.get('email', '')
        current_phone = self.conversation_data.get('phone', '')
        step = self.conversation_data.get('step', 'chatting')
        
        # Build system prompt
        system_prompt = self._build_system_prompt(current_name, current_email, current_phone, step)
        
        # Define all available tools
        tools = self._get_tools()
        
        # Get conversation history from database
        conversation_history = self._get_conversation_history()
        
        # Build messages with full conversation history
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
        try:
            # Call LLM with function calling
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=512  # Keep responses concise
            )
            
            message = response.choices[0].message
            
            # Check if LLM wants to call a tool
            if message.tool_calls:
                # Handle ALL tool calls - execute each one and collect results
                tool_results = []
                function_names = []
                
                # Add assistant message with tool calls
                messages.append(message)
                
                # Execute all tool calls
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse tool arguments: {tool_call.function.arguments}")
                        function_args = {}
                    
                    # Execute the tool
                    tool_result = self._execute_tool(function_name, function_args)
                    function_names.append(function_name)
                    tool_results.append({
                        "tool_call_id": tool_call.id,
                        "result": tool_result
                    })
                    
                    # Add tool response message for each tool call
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result)
                    })
                
                # Get final response from LLM (without tools parameter to prevent infinite loops)
                try:
                    final_response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=256  # Keep concise
                        # Note: Not passing tools parameter to prevent tool calls in final response
                    )
                    
                    final_message = final_response.choices[0].message
                    
                    # Extract assistant message content
                    if final_message.content:
                        assistant_message = final_message.content.strip()
                    elif final_message.tool_calls:
                        # If somehow tool calls are returned, log warning and use fallback
                        logger.warning("Final response has tool calls but no content, using fallback")
                        assistant_message = self._generate_response_from_tool_results(function_names, tool_results)
                    else:
                        # No content and no tool calls - use fallback
                        assistant_message = self._generate_response_from_tool_results(function_names, tool_results)
                        
                except Exception as e:
                    logger.error(f"Error getting final response: {str(e)}", exc_info=True)
                    # Fallback: generate a response based on tool results
                    assistant_message = self._generate_response_from_tool_results(function_names, tool_results)
                
                # Check if lead was submitted
                if "submit_lead" in function_names:
                    for result in tool_results:
                        if result["result"].get("success"):
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
                
                # Check if conversation was ended
                if "end_conversation" in function_names:
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
                needs_info = self._get_needs_info()
                
                # Generate suggestions based on context
                primary_function = function_names[0] if function_names else None
                suggestions = self._generate_suggestions(assistant_message, user_message, primary_function)
                
                return {
                    'message': assistant_message,
                    'suggestions': suggestions,
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None
                }
            else:
                # LLM responded directly without calling tools
                assistant_message = message.content.strip()
                needs_info = self._get_needs_info()
                
                # Generate suggestions based on context
                suggestions = self._generate_suggestions(assistant_message, user_message, None)
                
                return {
                    'message': assistant_message,
                    'suggestions': suggestions,
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None
                }
                
        except Exception as e:
            logger.error(f"Error in unified agent: {str(e)}", exc_info=True)
            return {
                'message': "I apologize, but I encountered an error. Please try again.",
                'suggestions': [],
                'complete': False,
                'needs_info': None,
                'escalate_to': None
            }
    
    def _get_conversation_history(self, limit: int = 20) -> list:
        """Get conversation history from database."""
        from chats.models import ChatMessage
        
        try:
            messages = ChatMessage.objects.filter(
                session=self.session,
                is_deleted=False,
                role__in=['user', 'assistant']
            ).order_by('timestamp')[:limit]
            
            history = []
            for msg in messages:
                history.append({
                    "role": msg.role,
                    "content": msg.message
                })
            
            return history
        except Exception as e:
            logger.error(f"Error getting conversation history: {str(e)}")
            return []
    
    def _build_system_prompt(self, name: str, email: str, phone: str, step: str) -> str:
        """Build system prompt based on current state."""
        prompt = """You are WhipSmart's Unified Assistant. Your PRIMARY GOAL is to help users understand WhipSmart's services AND convert them to connect with our team.

MAIN GOAL: Understand user's intent, answer their questions, and CONVERT users to connect with our team.

CONVERSION STRATEGY:
- After answering questions, PROACTIVELY offer to connect them with our team
- When user shows interest (asks about pricing, benefits, getting started, etc.), immediately offer team connection
- Use phrases like:
  * "Would you like to connect with our team to explore your options?"
  * "I can connect you with our team to get personalized assistance. Would you like me to do that?"
  * "Are you interested in learning more? We can connect you with our team."
- Don't wait for user to ask - be proactive in offering team connection
- Make it natural and helpful, not pushy

CRITICAL: UNDERSTAND USER INTENT AND ASK CLARIFYING QUESTIONS
- ALWAYS read the FULL conversation history to understand what the user is asking
- If user's question is unclear or ambiguous, ASK CLARIFYING QUESTIONS to better understand their needs
- Examples of clarifying questions:
  * "Are you looking for information about novated leases, or do you have a specific question about our services?"
  * "Would you like to know about pricing, vehicle options, or the leasing process?"
  * "Are you interested in electric vehicles specifically, or all vehicle types?"
- Don't guess what user wants - ask for clarification when needed
- When user says "yes", "sure", "okay", etc., they are agreeing to the LAST question you asked
- If you asked "Would you like to connect with our team?" and user says "yes", immediately start collecting their information
- If you asked "Would you like further details?" and user says "yes", search knowledge base for more information
- Understand the conversation flow - don't ask for clarification when the context is clear

SESSION MANAGEMENT:
- If user says they're done, have no more questions, say goodbye, or indicate they're finished → End the conversation gracefully
- If user hasn't responded for a while and seems satisfied → Offer to help with anything else or end conversation
- End conversation with: "Thank you for chatting with WhipSmart! If you have any more questions, feel free to reach out. Have a great day!"

CURRENT STATE:
- Name: {name}
- Email: {email}
- Phone: {phone}
- Step: {step}

YOUR CAPABILITIES:
1. Answer questions about WhipSmart services using knowledge base (RAG tool)
2. Search for available vehicles (car search tool)
3. Collect user information when they want to connect with our team
4. Ask clarifying questions when user intent is unclear
5. End conversation gracefully when user is done
6. PROACTIVELY offer team connection after answering questions

WHEN TO OFFER TEAM CONNECTION (BE PROACTIVE):
- After answering any question about pricing, benefits, or services
- When user asks about getting started, application process, or next steps
- When user shows interest (keywords: interested, want to, explore, learn more, etc.)
- After providing information - always offer: "Would you like to connect with our team to explore your options?"
- When user seems satisfied with an answer - offer: "Are you interested in learning more? We can connect you with our team."

WHEN TO COLLECT USER INFORMATION:
- User says "yes" to connecting with team
- User wants to schedule a call
- User shows interest in WhipSmart services
- User asks about pricing, plans, onboarding, consultation
- You cannot fully assist and need human help
- User explicitly asks to speak with someone

RESPONSE GUIDELINES:
- Keep responses CONCISE (2-4 sentences maximum)
- Be clear and direct
- Use knowledge base to answer questions accurately
- Ask clarifying questions when user intent is unclear
- PROACTIVELY offer team connection after answering questions
- Only collect information when user wants to connect with team
- If user provides multiple pieces of info at once, extract all of them
- Make conversation NATURAL and FLOWING - understand context from previous messages
- If user seems done or satisfied, offer to help with anything else or end conversation

TOOLS AVAILABLE:
- search_knowledge_base: Search WhipSmart knowledge base for answers
- search_vehicles: Search for available vehicles
- collect_user_info: Extract and store name, email, phone from user message
- update_user_info: Update a specific field if user corrects it
- submit_lead: Submit lead when all info collected and confirmed
- ask_for_missing_field: Ask user for a specific missing field
- end_conversation: End the conversation gracefully when user is done

UNDERSTANDING USER PROMPTS:
- Analyze the user's message carefully - what are they really asking?
- Look for keywords and intent: pricing, vehicles, process, benefits, etc.
- If the question is too broad (e.g., "tell me about leasing"), ask what specific aspect they want to know
- If the question is unclear, ask a clarifying question BEFORE searching knowledge base
- Use conversation history to understand context and follow-up questions

EXAMPLES:
- If you asked "Would you like to connect with our team?" and user says "yes" → Use collect_user_info tool or ask_for_missing_field
- If you asked "Would you like further details?" and user says "yes" → Use search_knowledge_base with the topic from previous conversation
- If user says "yes" without clear context → Look at last assistant message to understand what they're agreeing to
- If user says "I'm done", "no more questions", "thank you, goodbye", "that's all" → Use end_conversation tool
- If user's question is vague like "tell me about leasing" → Ask clarifying question: "Would you like to know about novated leases, the leasing process, or vehicle options?"
- If user asks "what are the benefits?" without context → Ask: "Are you asking about the benefits of novated leases, electric vehicles, or WhipSmart's services?"
- After answering a question → Always offer: "Would you like to connect with our team to explore your options?"
- If user seems satisfied after getting an answer → Offer: "Are you interested in learning more? We can connect you with our team." or use end_conversation if they indicate they're done

Remember: Your MAIN GOAL is conversion - understand user intent, answer questions, and proactively guide them to connect with our team.""".format(
            name=name or "Not provided",
            email=email or "Not provided",
            phone=phone or "Not provided",
            step=step
        )
        return prompt
    
    def _get_tools(self) -> list:
        """Get all available tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge_base",
                    "description": "Search WhipSmart knowledge base for answers to questions about services, novated leases, EVs, tax benefits, etc. Use this for ANY question about WhipSmart.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query to find relevant information"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_vehicles",
                    "description": "Search for available vehicles/cars. Use when user asks about vehicle options, availability, or wants to find specific vehicles.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filters": {
                                "type": "object",
                                "description": "Search filters",
                                "properties": {
                                    "max_price": {"type": "number"},
                                    "min_price": {"type": "number"},
                                    "min_range": {"type": "number"},
                                    "max_range": {"type": "number"},
                                    "make": {"type": "string"},
                                    "model": {"type": "string"}
                                }
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "collect_user_info",
                    "description": "Extract name, email, or phone from user message and store it. Use when user provides their information OR when user says 'yes' to connecting with team. IMPORTANT: If user said 'yes' to connecting with team, use this tool to extract any info they provided, or use ask_for_missing_field if they didn't provide info yet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Full name if provided, otherwise null"
                            },
                            "email": {
                                "type": "string",
                                "description": "Email address if provided, otherwise null"
                            },
                            "phone": {
                                "type": "string",
                                "description": "Phone number if provided, otherwise null"
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_user_info",
                    "description": "Update a specific field when user corrects information. Use when user says a field is incorrect.",
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
                    "description": "Submit the lead when all information (name, email, phone) is collected and user confirms. Only call when user says 'yes' to confirmation.",
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
                    "name": "end_conversation",
                    "description": "End the conversation gracefully when user indicates they're done, have no more questions, say goodbye, or seem satisfied. Use this when user says things like 'I'm done', 'no more questions', 'thank you, goodbye', 'that's all', etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Final message to send to user (e.g., 'Thank you for chatting with WhipSmart! If you have any more questions, feel free to reach out. Have a great day!')"
                            }
                        },
                        "required": ["message"]
                    }
                }
            }
        ]
    
    def _execute_tool(self, function_name: str, args: Dict) -> Dict:
        """Execute a tool function and return result."""
        try:
            if function_name == "search_knowledge_base":
                return self._tool_search_knowledge_base(args)
            elif function_name == "search_vehicles":
                return self._tool_search_vehicles(args)
            elif function_name == "collect_user_info":
                return self._tool_collect_user_info(args)
            elif function_name == "update_user_info":
                return self._tool_update_user_info(args)
            elif function_name == "submit_lead":
                return self._tool_submit_lead()
            elif function_name == "ask_for_missing_field":
                return self._tool_ask_for_missing_field(args)
            elif function_name == "end_conversation":
                return self._tool_end_conversation(args)
            else:
                return {"error": f"Unknown tool: {function_name}"}
        except Exception as e:
            logger.error(f"Error executing tool {function_name}: {str(e)}", exc_info=True)
            return {"error": str(e)}
    
    def _tool_search_knowledge_base(self, args: Dict) -> Dict:
        """Search knowledge base using RAG."""
        query = args.get('query', '')
        if not query:
            return {"error": "Query is required"}
        
        try:
            # Use RAG tool from agents
            agent_state = session_manager.get_or_create_agent_state(str(self.session.id))
            agent_state.tool_result = {
                "action": "rag",
                "query": query
            }
            
            # Call RAG tool
            state_dict = rag_tool_node(agent_state.to_dict())
            rag_state = AgentState.from_dict(state_dict)
            
            results = rag_state.tool_result.get('results', [])
            
            # Format results for LLM
            if results:
                formatted_results = []
                for r in results[:4]:  # Top 4 results
                    if isinstance(r, dict):
                        text = r.get('text', '')[:500]  # Limit length
                        score = r.get('score', 0.0)
                        source = r.get('metadata', {}).get('source', '')
                        formatted_results.append({
                            "text": text,
                            "score": score,
                            "source": source
                        })
                
                return {
                    "success": True,
                    "results": formatted_results,
                    "count": len(formatted_results)
                }
            else:
                return {
                    "success": False,
                    "message": "No relevant information found in knowledge base",
                    "results": []
                }
        except Exception as e:
            logger.error(f"Error in RAG search: {str(e)}", exc_info=True)
            return {"error": str(e)}
    
    def _tool_search_vehicles(self, args: Dict) -> Dict:
        """Search for vehicles."""
        filters = args.get('filters', {})
        
        try:
            agent_state = session_manager.get_or_create_agent_state(str(self.session.id))
            agent_state.tool_result = {
                "action": "car",
                "filters": filters
            }
            
            # Call car tool
            state_dict = car_tool_node(agent_state.to_dict())
            car_state = AgentState.from_dict(state_dict)
            
            results = car_state.tool_result.get('results', [])
            
            return {
                "success": True,
                "results": results,
                "count": len(results)
            }
        except Exception as e:
            logger.error(f"Error in vehicle search: {str(e)}", exc_info=True)
            return {"error": str(e)}
    
    def _tool_collect_user_info(self, args: Dict) -> Dict:
        """Collect and store user information."""
        updated_fields = []
        
        # Extract and validate name
        if args.get('name') and not self.conversation_data.get('name'):
            name = args['name'].strip()
            if self._validate_name(name):
                self.conversation_data['name'] = name
                updated_fields.append('name')
        
        # Extract and validate email
        if args.get('email') and not self.conversation_data.get('email'):
            email = args['email'].strip().lower()
            if self._validate_email(email):
                self.conversation_data['email'] = email
                updated_fields.append('email')
        
        # Extract and validate phone
        if args.get('phone') and not self.conversation_data.get('phone'):
            phone = args['phone'].strip()
            if self._validate_phone(phone):
                self.conversation_data['phone'] = phone
                updated_fields.append('phone')
        
        # Update step if all fields collected
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
    
    def _tool_update_user_info(self, args: Dict) -> Dict:
        """Update a specific field."""
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
        """Submit the lead."""
        name = self.conversation_data.get('name', '')
        email = self.conversation_data.get('email', '')
        phone = self.conversation_data.get('phone', '')
        
        if not name or not email or not phone:
            return {
                "error": "Cannot submit lead: missing required fields",
                "missing_fields": self._get_missing_fields()
            }
        
        # Log the lead submission
        logger.info("=" * 80)
        logger.info("[UNIFIED AGENT] SUBMITTING LEAD:")
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
    
    def _tool_end_conversation(self, args: Dict) -> Dict:
        """End the conversation gracefully."""
        message = args.get('message', 'Thank you for chatting with WhipSmart! If you have any more questions, feel free to reach out. Have a great day!')
        
        logger.info("=" * 80)
        logger.info("[UNIFIED AGENT] ENDING CONVERSATION")
        logger.info(f"  Session ID: {self.session.id}")
        logger.info("=" * 80)
        
        # Mark as complete
        self.conversation_data['step'] = 'complete'
        self.conversation_data['ended_at'] = timezone.now().isoformat()
        self._save_conversation_data()
        
        # Lock session
        self.session.is_active = False
        self.session.save(update_fields=['is_active', 'conversation_data'])
        
        return {
            "success": True,
            "message": message,
            "conversation_ended": True
        }
    
    def _tool_ask_for_missing_field(self, args: Dict) -> Dict:
        """Ask for a missing field."""
        field = args.get('field')
        
        if field == 'name':
            return {"message": "To connect you with our team, could you please provide your full name?"}
        elif field == 'email':
            name = self.conversation_data.get('name', '')
            greeting = f"Thank you, {name}! " if name else ""
            return {"message": f"{greeting}Could you please provide your email address?"}
        elif field == 'phone':
            return {"message": "Perfect! Now, could you please provide your phone number?"}
        else:
            return {"error": f"Unknown field: {field}"}
    
    def _validate_name(self, name: str) -> bool:
        """Validate name."""
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
    
    def _generate_suggestions(self, assistant_message: str, user_message: str, tool_used: Optional[str]) -> list:
        """Generate contextual suggestions to guide users toward connecting with team."""
        from agents.suggestions import generate_suggestions
        
        # Get conversation history for context
        conversation_history = self._get_conversation_history(limit=10)
        
        # If user is already in lead collection flow, don't show suggestions
        if self.conversation_data.get('step') in ['confirmation', 'complete']:
            return []
        
        # If user already has all info collected, don't show suggestions
        if self.conversation_data.get('name') and self.conversation_data.get('email') and self.conversation_data.get('phone'):
            return []
        
        # Use the existing generate_suggestions function
        suggestions = generate_suggestions(
            conversation_messages=conversation_history + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message}
            ],
            last_bot_message=assistant_message,
            max_suggestions=3
        )
        
        # Enhance suggestions to prioritize "connect with team"
        enhanced_suggestions = []
        
        # Analyze context
        user_lower = user_message.lower()
        assistant_lower = assistant_message.lower()
        
        # Priority: If user shows interest or asks about pricing/getting started, prioritize team connection
        interest_keywords = ['price', 'cost', 'benefit', 'get started', 'how to', 'interested', 'want to', 'explore', 'learn more', 'apply', 'sign up']
        if any(keyword in user_lower for keyword in interest_keywords):
            # Add "Connect with our team" as first suggestion if not already present
            if not any('connect' in s.lower() or 'team' in s.lower() for s in suggestions):
                enhanced_suggestions.append("Connect with our team to get started")
        
        # If assistant mentioned connecting with team, prioritize it
        if 'connect' in assistant_lower or 'team' in assistant_lower:
            if not any('connect' in s.lower() or 'team' in s.lower() for s in suggestions):
                enhanced_suggestions.append("Yes, connect me with your team")
        
        # Add other suggestions
        for suggestion in suggestions:
            if suggestion not in enhanced_suggestions:
                enhanced_suggestions.append(suggestion)
        
        # If no suggestions yet, add default conversion-focused ones
        if not enhanced_suggestions:
            enhanced_suggestions = [
                "Connect with our team to explore your options",
                "I'd like to learn more",
                "Get started with WhipSmart"
            ]
        
        # Limit to 3 suggestions
        return enhanced_suggestions[:3]
    
    def _generate_response_from_tool_results(self, function_names: list, tool_results: list) -> str:
        """Generate a response message based on tool results."""
        # Generate a helpful response based on what tools were executed
        if "collect_user_info" in function_names:
            for result in tool_results:
                if result["result"].get("success"):
                    updated_fields = result["result"].get("updated_fields", [])
                    if updated_fields:
                        missing = result["result"].get("missing_fields", [])
                        if 'email' in missing:
                            return "Thank you! Could you please provide your email address?"
                        elif 'phone' in missing:
                            return "Perfect! Now, could you please provide your phone number?"
                        elif not missing:
                            name = self.conversation_data.get('name', '')
                            email = self.conversation_data.get('email', '')
                            phone = self.conversation_data.get('phone', '')
                            return f"""Here is what I have collected:
Name: {name}
Email: {email}
Phone: {phone}
Is this correct? (Yes/No)"""
        elif "search_knowledge_base" in function_names:
            return "I found some information that might help. Let me share that with you."
        elif "update_user_info" in function_names:
            return "I've updated your information. Is there anything else you'd like to change?"
        
        return "I've processed your request. How can I help you further?"
    
    def _get_needs_info(self) -> Optional[str]:
        """Determine what information is still needed."""
        if self.conversation_data.get('step') == 'confirmation':
            return 'confirmation'
        if not self.conversation_data.get('name'):
            return 'name'
        if not self.conversation_data.get('email'):
            return 'email'
        if not self.conversation_data.get('phone'):
            return 'phone'
        return None
    
    def _save_conversation_data(self):
        """Save conversation data to session."""
        self.session.conversation_data = self.conversation_data
        self.session.save(update_fields=['conversation_data'])

