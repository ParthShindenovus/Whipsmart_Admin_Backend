"""
Unified Main Agent - Handles all conversation types with intelligent routing.
Uses LLM function calling to route to appropriate handlers and tools.
Enhanced with intelligent RAG fetching and two-step answer generation.
"""
import logging
import json
import re
from typing import Dict, Optional, Tuple
from django.utils import timezone
from chats.models import Session
from agents.graph import get_graph
from agents.session_manager import session_manager
from agents.state import AgentState
from agents.tools.rag_tool import rag_tool_node
from agents.tools.car_tool import car_tool_node
from agents.agent_prompts import KNOWLEDGE_AGENT_PROMPT
from agents.multi_agent_reasoning import MultiAgentReasoning
from openai import AzureOpenAI
from django.conf import settings
from service.hubspot_service import create_contact, update_contact, format_phone_number

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
    
    def _classify_question(self, user_message: str, conversation_history: list) -> Tuple[bool, str]:
        """
        Fast classification to determine if question needs RAG context.
        Returns: (needs_rag: bool, query: str)
        
        Domain questions (need RAG): Whipsmart, leasing, novated lease, tax, benefits, 
        costs, eligibility, process, vehicles, EVs, etc.
        
        User-related questions (no RAG): connect with team, contact, speak with someone,
        schedule, personal info collection, etc.
        """
        message_lower = user_message.lower()
        message_stripped = user_message.strip()
        
        # CRITICAL: Check if user is providing contact information (email/phone) - NO RAG needed
        # Pattern: email address (contains @) or phone number (contains digits)
        import re
        # Check for email pattern
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        # Check for phone pattern (at least 8 digits, possibly with spaces/dashes/parentheses)
        phone_pattern = r'[\d\s\-\(\)]{8,}'
        
        has_email = bool(re.search(email_pattern, message_stripped))
        # Count digits to detect phone numbers
        digit_count = len(re.findall(r'\d', message_stripped))
        has_phone = digit_count >= 8  # At least 8 digits suggests a phone number
        
        # If message contains email or phone, it's likely user providing contact info - NO RAG
        if has_email or has_phone:
            # But check if it's part of a question (e.g., "what is info@whipsmart.com?")
            question_words = ['what', 'where', 'when', 'why', 'how', 'who', 'which', '?']
            is_question = any(word in message_lower for word in question_words)
            if not is_question:
                return False, ""
        
        # User-related keywords that DON'T need RAG (team connection, info collection, etc.)
        # CRITICAL: These should ALWAYS bypass RAG - just collect info and acknowledge
        user_action_keywords = [
            # Team connection keywords
            'connect with team', 'connect me', 'connect with', 'connect to team',
            'speak with', 'speak to', 'talk with', 'talk to', 'talk to someone',
            'contact', 'contact team', 'contact someone', 'contact us',
            'schedule', 'schedule a call', 'schedule call', 'book a call',
            'call me', 'call me back', 'have someone call', 'have someone contact',
            'reach out', 'reach out to', 'get in touch', 'get in touch with',
            'team contact', 'team member', 'human', 'person', 'representative',
            'help me connect', 'want to connect', 'would like to connect',
            'need to speak', 'need to talk', 'want to speak', 'want to talk',
            'set up a call', 'arrange a call', 'organize a call',
            # Information collection keywords
            'my name is', 'my email', 'my phone', 'my number', 'i am',
            'email is', 'phone is', 'number is', 'name is',
            'here is my', 'here\'s my', 'this is my',
            # Simple responses
            'yes', 'no', 'sure', 'okay', 'ok', 'thanks', 'thank you',
            'goodbye', 'bye', 'done', 'finished', 'that\'s all', 'no more questions',
            'sounds good', 'that works', 'perfect', 'great'
        ]
        
        # Check for user action keywords first (fast path) - CRITICAL: bypass RAG
        for keyword in user_action_keywords:
            if keyword in message_lower:
                logger.info(f"[CLASSIFY] User action detected ('{keyword}') - bypassing RAG")
                return False, ""
        
        # Also check if message is primarily about connecting/contacting (even if keyword not exact match)
        # This catches variations like "I'd like to connect", "can I speak with", etc.
        connection_intent_patterns = [
            r'\b(?:i\s+)?(?:would|want|need|like|wish)\s+(?:to\s+)?(?:connect|speak|talk|contact|reach)',
            r'\b(?:can|could|may)\s+(?:i|we)\s+(?:connect|speak|talk|contact|reach)',
            r'\b(?:let|help)\s+(?:me\s+)?(?:connect|speak|talk|contact|reach)',
            r'\b(?:i\s+)?(?:am|would\s+be)\s+(?:interested\s+in\s+)?(?:connecting|speaking|talking|contacting)',
            r'\b(?:arrange|set\s+up|book|schedule)\s+(?:a\s+)?(?:call|meeting|conversation)'
        ]
        
        for pattern in connection_intent_patterns:
            if re.search(pattern, message_lower):
                logger.info(f"[CLASSIFY] Connection intent detected - bypassing RAG")
                return False, ""
        
        # Domain keywords that ALWAYS need RAG
        domain_keywords = [
            'whipsmart', 'novated lease', 'novated leasing', 'salary sacrifice',
            'tax', 'tax benefit', 'tax savings', 'gst', 'fbt', 'fringe benefit',
            'lease', 'leasing', 'car lease', 'vehicle lease',
            'benefit', 'benefits', 'advantage', 'advantages', 'pros', 'cons',
            'cost', 'costs', 'price', 'pricing', 'fee', 'fees', 'charge', 'charges',
            'eligibility', 'eligible', 'qualify', 'qualification', 'requirement', 'requirements',
            'process', 'how to', 'how does', 'how do', 'what is', 'what are',
            'vehicle', 'vehicles', 'car', 'cars', 'ev', 'electric vehicle', 'tesla',
            'inclusion', 'inclusions', 'what\'s included', 'what is included',
            'explain', 'tell me about', 'information about', 'details about',
            'difference', 'compare', 'comparison', 'vs', 'versus',
            'risk', 'risks', 'downside', 'disadvantage', 'problem', 'issues'
        ]
        
        # Check for domain keywords
        for keyword in domain_keywords:
            if keyword in message_lower:
                # Use the full user message as query, or extract relevant part
                query = message_stripped
                return True, query
        
        # If message is a follow-up question (short, likely related to previous context)
        # Check conversation history for domain context
        if len(user_message.split()) <= 5:  # Short message
            # Check if previous messages had domain content
            for msg in reversed(conversation_history[-3:]):  # Check last 3 messages
                if msg.get('role') == 'user':
                    prev_msg = msg.get('content', '').lower()
                    if any(kw in prev_msg for kw in domain_keywords):
                        return True, message_stripped
        
        # Check conversation history: if last assistant message asked for contact info, this is likely info submission
        if conversation_history:
            last_assistant_msg = None
            for msg in reversed(conversation_history[-3:]):
                if msg.get('role') == 'assistant':
                    last_assistant_msg = msg.get('content', '').lower()
                    break
            
            if last_assistant_msg:
                info_request_keywords = ['email', 'phone', 'contact', 'details', 'information', 'share']
                if any(kw in last_assistant_msg for kw in info_request_keywords):
                    # Last message asked for info, current message likely provides it - NO RAG
                    return False, ""
        
        # Default: if unclear, do NOT use RAG - let LLM decide based on conversation context
        # The LLM will have full conversation history and can use search_knowledge_base tool if needed
        return False, ""
    
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
        full_name = self.conversation_data.get('name', '')
        # Extract first name only for more natural conversation
        current_name = full_name.strip().split()[0] if full_name.strip() else ''
        current_email = self.conversation_data.get('email', '')
        current_phone = self.conversation_data.get('phone', '')
        step = self.conversation_data.get('step', 'chatting')
        
        # Get conversation history from database (last 3-4 messages for LLM context)
        conversation_history = self._get_conversation_history(limit=4)
        
        # STEP 1: Classify question and fetch RAG context if needed (OPTIMIZED: do this first)
        needs_rag, rag_query = self._classify_question(user_message, conversation_history)
        rag_context = []
        knowledge_results = []
        
        if needs_rag and rag_query:
            # Always fetch RAG context for domain questions
            logger.info(f"[RAG] Fetching context for domain question: {rag_query}")
            try:
                rag_result = self._tool_search_knowledge_base({"query": rag_query})
                if rag_result.get("success") and rag_result.get("results"):
                    rag_context = rag_result.get("results", [])
                    knowledge_results = rag_context
                    logger.info(f"[RAG] Retrieved {len(rag_context)} context chunks")
            except Exception as e:
                logger.error(f"[RAG] Error fetching context: {str(e)}", exc_info=True)
        
        # Check if we should subtly ask for name (after 3-4 questions without name)
        # This will be handled separately after answer generation
        # Use full_name for checking if name exists, but current_name (first name) for prompts
        should_ask_for_name = self._should_ask_for_name(conversation_history, full_name)
        
        # Build system prompt (rag_context will be used in two-step process if needed)
        # Note: Team connection decision will be made AFTER answer generation
        system_prompt = self._build_system_prompt(
            current_name, current_email, current_phone, step, 
            should_ask_for_name=False  # Don't include in prompt, will be sent separately
        )
        
        # Define all available tools
        tools = self._get_tools()
        
        # Build messages with full conversation history
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
        try:
            # For domain questions with RAG context, use two-step answer generation
            if needs_rag and rag_context:
                return self._handle_domain_question_with_rag(
                    client, model, messages, tools, user_message, 
                    rag_context, knowledge_results, conversation_history
                )
            
            # For user-related questions (no RAG), use standard flow
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
                
                # Before executing tools, check if end_conversation is being called and we need to ask for name/phone
                # This prevents the tool from executing if we need to ask first
                name = self.conversation_data.get('name', '')
                phone = self.conversation_data.get('phone', '')
                should_ask_before_end = False
                
                # Check if end_conversation is in the tool calls and we need to ask for info first
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "end_conversation":
                        if not name or not phone:
                            # Don't execute end_conversation yet - we need to ask for name/phone first
                            should_ask_before_end = True
                            logger.info("[END_CONVERSATION] Skipping end_conversation tool - need to ask for name/phone first")
                            break
                
                # Execute all tool calls (except end_conversation if we need to ask first)
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    
                    # Skip end_conversation if we need to ask for name/phone first
                    if function_name == "end_conversation" and should_ask_before_end:
                        continue
                    
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
                        # Normalize newlines: replace multiple newlines with single newline (frontend converts \n to <br>)
                        assistant_message = self._normalize_newlines(assistant_message)
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
                
                # Extract knowledge base results (including URLs) from search_knowledge_base tool, if used
                knowledge_results = []
                if "search_knowledge_base" in function_names:
                    for fn, tr in zip(function_names, tool_results):
                        if fn == "search_knowledge_base":
                            tool_res = tr.get("result") or {}
                            if tool_res.get("success"):
                                knowledge_results = tool_res.get("results", []) or []
                            break
                
                # Check if user is responding to our request for name/phone (after declining team connection or before ending)
                # This MUST be checked BEFORE end_conversation check
                if self.conversation_data.get('asking_for_info_after_decline') or self.conversation_data.get('asking_before_end'):
                    user_lower = user_message.lower().strip()
                    
                    # Check if user is asking why we need this information
                    why_phrases = ['why do you need', 'why do you want', 'why do you ask', 'why need', 'why want', 'why ask', 'what for', 'why']
                    if any(phrase in user_lower for phrase in why_phrases):
                        # Explain why we need it and ask again
                        asking_before_end = self.conversation_data.get('asking_before_end')
                        if asking_before_end:
                            return {
                                'message': "We'd like to stay in touch so we can send you helpful updates about WhipSmart's EV leasing services and novated lease options. Could I get your name and phone number?",
                                'suggestions': [],
                                'complete': False,
                                'needs_info': 'name_phone',
                                'escalate_to': None,
                                'knowledge_results': knowledge_results,
                                'metadata': {'knowledge_results': knowledge_results}
                            }
                        else:
                            return {
                                'message': "We'd like to stay in touch so we can send you helpful updates about WhipSmart's EV leasing services. Could I get your name and phone number?",
                                'suggestions': [],
                                'complete': False,
                                'needs_info': 'name_phone',
                                'escalate_to': None,
                                'knowledge_results': knowledge_results,
                                'metadata': {'knowledge_results': knowledge_results}
                            }
                    
                    # Check if user is declining to share information
                    # Only match if it's a clear decline (short response, not part of a longer message)
                    # Use regex to match whole words/phrases, not parts of words
                    import re
                    is_decline = False
                    
                    # Single word declines (exact match)
                    if user_lower in ['no', 'nope', 'nah']:
                        is_decline = True
                    # Short phrases that are clear declines (3 words or less)
                    elif len(user_lower.split()) <= 3:
                        decline_patterns = [
                            r'^no\s+thanks',
                            r'^no\s+thank\s+you',
                            r"^don'?t\s+want",
                            r"^don'?t\s+need",
                            r'^won\'?t\s+share',
                            r'^can\'?t\s+share',
                            r'^prefer\s+not',
                            r'^i\s+don\'?t\s+want',
                            r'^i\s+don\'?t\s+need',
                            r'^not\s+interested'
                        ]
                        for pattern in decline_patterns:
                            if re.match(pattern, user_lower):
                                is_decline = True
                                break
                    
                    if is_decline:
                        # User declined to share - acknowledge and end
                        self.conversation_data.pop('asking_for_info_after_decline', None)
                        asking_before_end = self.conversation_data.pop('asking_before_end', None)
                        self._save_conversation_data()
                        
                        if asking_before_end:
                            # Was asking before ending - end the conversation
                            self.conversation_data['step'] = 'complete'
                            self.session.is_active = False
                            self._save_conversation_data()
                            self.session.save(update_fields=['is_active', 'conversation_data'])
                            
                            return {
                                'message': "No worries at all! Thanks for chatting with WhipSmart. If you have any more questions, feel free to reach out. Have a great day!",
                                'suggestions': [],
                                'complete': True,
                                'needs_info': None,
                                'escalate_to': None
                            }
                        else:
                            # After declining team connection - continue conversation
                            assistant_message = "No worries! Is there anything else you'd like to know about WhipSmart?"
                    
                    # Try to extract name and phone from user message
                    collect_result = self._tool_collect_user_info({"name": user_message, "phone": user_message})
                    name = self.conversation_data.get('name', '')
                    phone = self.conversation_data.get('phone', '')
                    
                    asking_before_end = self.conversation_data.get('asking_before_end')
                    asking_after_decline = self.conversation_data.get('asking_for_info_after_decline')
                    
                    if name and phone:
                        # Got both name and phone - acknowledge and end if before ending, otherwise continue
                        self.conversation_data.pop('asking_for_info_after_decline', None)
                        self.conversation_data.pop('asking_before_end', None)
                        self._save_conversation_data()
                        first_name = name.split()[0] if name else ''
                        
                        if asking_before_end:
                            # Was asking before ending - end the conversation
                            self.conversation_data['step'] = 'complete'
                            self.session.is_active = False
                            self._save_conversation_data()
                            self.session.save(update_fields=['is_active', 'conversation_data'])
                            
                            return {
                                'message': f"Thanks {first_name}! I've got your details. Our team will be in touch. Have a great day!",
                                'suggestions': [],
                                'complete': True,
                                'needs_info': None,
                                'escalate_to': None
                            }
                        else:
                            # After declining team connection - continue conversation
                            assistant_message = f"Thanks {first_name}! I've got your details. {assistant_message if assistant_message else 'Is there anything else you\'d like to know about WhipSmart?'}"
                    elif name or phone:
                        # Got partial info (only name or only phone) - store what we have, thank them, and end if before ending
                        self.conversation_data.pop('asking_for_info_after_decline', None)
                        self.conversation_data.pop('asking_before_end', None)
                        self._save_conversation_data()
                        
                        if asking_before_end:
                            # Was asking before ending - end the conversation with what we have
                            self.conversation_data['step'] = 'complete'
                            self.session.is_active = False
                            self._save_conversation_data()
                            self.session.save(update_fields=['is_active', 'conversation_data'])
                            
                            first_name = name.split()[0] if name else ''
                            thank_msg = f"Thanks {first_name}! " if first_name else "Thanks! "
                            return {
                                'message': f"{thank_msg}I've got your details. Our team will be in touch. Have a great day!",
                                'suggestions': [],
                                'complete': True,
                                'needs_info': None,
                                'escalate_to': None
                            }
                        else:
                            # After declining team connection - continue conversation
                            assistant_message = f"Thanks! I've got that. {assistant_message if assistant_message else 'Is there anything else you\'d like to know about WhipSmart?'}"
                    else:
                        # Didn't get any info - acknowledge and end if before ending, otherwise continue
                        self.conversation_data.pop('asking_for_info_after_decline', None)
                        asking_before_end = self.conversation_data.pop('asking_before_end', None)
                        self._save_conversation_data()
                        
                        if asking_before_end:
                            # Was asking before ending - end the conversation anyway
                            self.conversation_data['step'] = 'complete'
                            self.session.is_active = False
                            self._save_conversation_data()
                            self.session.save(update_fields=['is_active', 'conversation_data'])
                            
                            return {
                                'message': "Thanks for chatting with WhipSmart! If you have any more questions, feel free to reach out. Have a great day!",
                                'suggestions': [],
                                'complete': True,
                                'needs_info': None,
                                'escalate_to': None
                            }
                        else:
                            # After declining team connection - continue conversation
                            assistant_message = assistant_message or "No worries! Is there anything else you'd like to know about WhipSmart?"
                
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
                # Note: If we skipped end_conversation tool execution above (should_ask_before_end), 
                # it won't be in function_names, so we check the original tool calls
                end_conversation_called = "end_conversation" in function_names
                if not end_conversation_called:
                    # Check if end_conversation was requested but we skipped it
                    for tool_call in message.tool_calls:
                        if tool_call.function.name == "end_conversation":
                            end_conversation_called = True
                            break
                
                if end_conversation_called:
                    # If we skipped end_conversation because we need to ask for name/phone first
                    if should_ask_before_end:
                        # Ask for name and phone before ending
                        self.conversation_data['asking_before_end'] = True
                        self._save_conversation_data()
                        
                        return {
                            'message': "Before we wrap up, could I get your name and phone number so we can stay in touch?",
                            'suggestions': [],
                            'complete': False,
                            'needs_info': 'name_phone',
                            'escalate_to': None,
                            'knowledge_results': knowledge_results,
                            'metadata': {'knowledge_results': knowledge_results}
                        }
                    
                    # If end_conversation tool was executed, proceed with ending
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
                
                # Check if user said "no" to team connection - ask for name and phone
                # IMPORTANT: Skip this check if:
                # 1. We're already asking for info
                # 2. We're actively collecting information (step is name/email/phone)
                # 3. User is providing information (collect_user_info tool was called)
                # This prevents false positives when user provides their name (e.g., "nick norrr" being detected as "no")
                # Get needs_info early to check if we're collecting information
                current_needs_info = self._get_needs_info()
                if (not self.conversation_data.get('asking_for_info_after_decline') and 
                    not self.conversation_data.get('asking_before_end') and
                    step not in ['name', 'email', 'phone'] and
                    current_needs_info not in ['name', 'email', 'phone'] and
                    "collect_user_info" not in function_names):
                    user_lower = user_message.lower().strip()
                    
                    # More precise decline detection - only match whole words/phrases, not parts of words
                    # Check if message is a clear decline (short response with decline keywords as whole words)
                    import re
                    is_decline = False
                    
                    # Single word declines (exact match only - prevents matching "no" in "nick" or "norrr")
                    if user_lower == 'no' or user_lower == 'nope' or user_lower == 'nah':
                        is_decline = True
                    # Short phrases that start with decline words (3 words or less)
                    # Use word boundary to ensure "no" is a whole word, not part of another word
                    elif len(user_lower.split()) <= 3:
                        decline_patterns = [
                            r'^no\s+thanks',
                            r'^no\s+thank\s+you',
                            r'^not\s+interested',
                            r"^don'?t\s+want",
                            r"^don'?t\s+need",
                            r'^not\s+right\s+now',
                            r'^maybe\s+later'
                        ]
                        for pattern in decline_patterns:
                            if re.match(pattern, user_lower):
                                is_decline = True
                                break
                    
                    if is_decline:
                        conversation_history = self._get_conversation_history(limit=2)
                        if conversation_history:
                            # Check last assistant message
                            last_assistant_msg = None
                            for msg in reversed(conversation_history):
                                if msg.get('role') == 'assistant':
                                    last_assistant_msg = msg.get('content', '').lower()
                                    break
                            
                            if last_assistant_msg:
                                # Check if last message was asking to connect with team
                                team_connection_phrases = [
                                    'connect with our team',
                                    'connect with the team',
                                    'connect you with',
                                    'would you like to connect',
                                    'connect with team',
                                    'connect with our sales team'
                                ]
                                if any(phrase in last_assistant_msg for phrase in team_connection_phrases):
                                    # User declined team connection - ask for name and phone
                                    name = self.conversation_data.get('name', '')
                                    phone = self.conversation_data.get('phone', '')
                                    
                                    if not name or not phone:
                                        # Ask for name and phone
                                        self.conversation_data['asking_for_info_after_decline'] = True
                                        self._save_conversation_data()
                                        return {
                                            'message': "No worries! Before we continue, could I get your name and phone number so we can stay in touch?",
                                            'suggestions': [],
                                            'complete': False,
                                            'needs_info': 'name_phone',
                                            'escalate_to': None,
                                            'knowledge_results': knowledge_results,
                                            'metadata': {'knowledge_results': knowledge_results}
                                        }
                
                # Determine what info is still needed
                needs_info = self._get_needs_info()
                
                # CRITICAL: If all details are collected (name, email, phone) and step is 'confirmation',
                # force proper acknowledgment instead of generic response
                name = self.conversation_data.get('name', '')
                email = self.conversation_data.get('email', '')
                phone = self.conversation_data.get('phone', '')
                current_step = self.conversation_data.get('step', '')
                
                if name and email and phone and current_step == 'confirmation' and "collect_user_info" in function_names:
                    # Check if this was the final collection (all fields now present)
                    # Force proper acknowledgment
                    first_name = name.split()[0] if name else ""
                    proper_acknowledgment = f"Perfect{', ' + first_name if first_name else ''}! I've got all your details sorted. I'll submit them to our team and they'll contact you shortly. While you're here, is there anything else you'd like to know about WhipSmart's EV leasing services, novated leases, or how we can help you?"
                    
                    # Only override if LLM didn't provide proper acknowledgment
                    acknowledgment_phrases = [
                        "all your details", "submit them to our team", "they'll contact you", 
                        "team will contact", "submitted to our team", "contact you shortly"
                    ]
                    has_proper_acknowledgment = any(phrase in assistant_message.lower() for phrase in acknowledgment_phrases)
                    
                    if not has_proper_acknowledgment:
                        logger.info("[ACKNOWLEDGMENT] Forcing proper acknowledgment - LLM response didn't include team contact info")
                        assistant_message = proper_acknowledgment
                    else:
                        logger.info("[ACKNOWLEDGMENT] LLM response already includes proper acknowledgment")
                
                # Generate suggestions based on context
                primary_function = function_names[0] if function_names else None
                suggestions = self._generate_suggestions(assistant_message, user_message, primary_function)
                
                # Remove any follow-up phrases that LLM might have included
                assistant_message = self._remove_followup_phrases(assistant_message)
                
                # Check if we should skip post-processing (information collection flow)
                should_skip_post_processing = self._should_skip_post_processing(
                    user_message, function_names, step, needs_info, assistant_message
                )
                
                # Post-processing: Analyze answer and decide which ONE follow-up message to send (non-blocking)
                # SKIP if we're in information collection mode or user just agreed to connect
                if should_skip_post_processing:
                    followup_type, followup_message = "", ""
                    logger.info("[POST-PROCESS] Skipping post-processing - in information collection flow")
                else:
                    followup_type, followup_message = self._analyze_and_generate_followup_message(
                        assistant_message, user_message, conversation_history, should_ask_for_name, current_name
                    )
                
                return {
                    'message': assistant_message,
                    'suggestions': suggestions,
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None,
                    # Expose RAG/knowledge-base results (each item includes "source" URL if available)
                    'knowledge_results': knowledge_results,
                    # Also include in metadata for WebSocket "complete" messages
                    'metadata': {
                        'knowledge_results': knowledge_results,
                    },
                    'followup_type': followup_type,  # 'ask_name', 'ask_to_connect', 'follow_up', or ''
                    'followup_message': followup_message,
                }
            else:
                # LLM responded directly without calling tools
                assistant_message = message.content.strip() if message.content else "I'm here to help! How can I assist you today?"
                # Normalize newlines: replace multiple newlines with single newline (frontend converts \n to <br>)
                assistant_message = self._normalize_newlines(assistant_message)
                # Remove any follow-up phrases that LLM might have included
                assistant_message = self._remove_followup_phrases(assistant_message)
                needs_info = self._get_needs_info()
                
                # Generate suggestions based on context
                suggestions = self._generate_suggestions(assistant_message, user_message, None)
                
                # Check if we should skip post-processing (information collection flow)
                should_skip_post_processing = self._should_skip_post_processing(
                    user_message, [], step, needs_info, assistant_message
                )
                
                # Post-processing: Analyze answer and decide which ONE follow-up message to send (non-blocking)
                # SKIP if we're in information collection mode or user just agreed to connect
                if should_skip_post_processing:
                    followup_type, followup_message = "", ""
                    logger.info("[POST-PROCESS] Skipping post-processing - in information collection flow")
                else:
                    # Get extended conversation history (6-7 messages) for post-processing context
                    extended_history = self._get_conversation_history(limit=7)
                    followup_type, followup_message = self._analyze_and_generate_followup_message(
                        assistant_message, user_message, extended_history, should_ask_for_name, current_name
                    )
                
                return {
                    'message': assistant_message,
                    'suggestions': suggestions,
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None,
                    'knowledge_results': [],
                    'metadata': {
                        'knowledge_results': [],
                    },
                    'followup_type': followup_type,  # 'ask_name', 'ask_to_connect', 'follow_up', or ''
                    'followup_message': followup_message,
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
    
    def _get_conversation_history(self, limit: int = 4) -> list:
        """Get conversation history from database. Returns last 3-4 messages for LLM context."""
        from chats.models import ChatMessage
        
        try:
            # Get last N messages ordered by timestamp (most recent first, then reverse)
            messages = ChatMessage.objects.filter(
                session=self.session,
                is_deleted=False,
                role__in=['user', 'assistant']
            ).order_by('-timestamp')[:limit]  # Get most recent messages first
            
            # Reverse to get chronological order (oldest to newest)
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
    
    def _should_ask_for_name(self, conversation_history: list, current_name: str) -> bool:
        """
        Check if we should subtly ask for the user's name.
        Returns True if:
        - User has asked 2-3 questions (user messages)
        - Name is not yet collected
        
        Note: We count ALL user messages in the session, not just the limited history.
        The current message being processed is not yet saved, so we count existing messages.
        """
        if current_name:
            return False
        
        # Count ALL user messages in the session (not just limited history)
        from chats.models import ChatMessage
        try:
            total_user_messages = ChatMessage.objects.filter(
                session=self.session,
                is_deleted=False,
                role='user'
            ).count()
            
            # After 2-3 questions, we should ask for name
            # Current message will be the 3rd or 4th question
            should_ask = 2 <= total_user_messages <= 3
            
            if should_ask:
                logger.info(f"[NAME COLLECTION] Should ask for name: {total_user_messages} user messages found")
            
            return should_ask
        except Exception as e:
            logger.error(f"Error counting user messages: {str(e)}")
            # Fallback to history-based counting
            user_message_count = sum(1 for msg in conversation_history if msg.get('role') == 'user')
            return 2 <= user_message_count <= 3
    
    def _should_offer_team_connection_auto(self, conversation_history: list) -> bool:
        """
        Automatically determine if we should offer team connection.
        Returns True if user has asked 3-4 questions.
        This is handled automatically by the system, not by LLM tool calls.
        """
        # Count ALL user messages in the session (not just limited history)
        from chats.models import ChatMessage
        try:
            total_user_messages = ChatMessage.objects.filter(
                session=self.session,
                is_deleted=False,
                role='user'
            ).count()
            
            # After 3-4 questions, we can offer team connection
            # Current message will be the 4th or 5th question
            should_offer = 3 <= total_user_messages <= 4
            
            if should_offer:
                logger.info(f"[TEAM CONNECTION] Auto-offering team connection: {total_user_messages} user messages found")
            
            return should_offer
        except Exception as e:
            logger.error(f"Error counting user messages: {str(e)}")
            # Fallback to history-based counting
            user_message_count = sum(1 for msg in conversation_history if msg.get('role') == 'user')
            return 3 <= user_message_count <= 4
    
    def _handle_domain_question_with_rag(
        self, client, model, messages, tools, user_message, 
        rag_context, knowledge_results, conversation_history
    ) -> Dict:
        """
        Handle domain questions with RAG context using multi-agent reasoning flow:
        1. Orchestrator coordinates parallel agents:
           - Agent 1: Question Classifier
           - Agent 2: Context/RAG Retriever (already done)
           - Agent 3: Structure & Length Planner
           - Agent 4: Must-Have Coverage Definer
        2. Prompt Assembler combines outputs
        3. Structured Response Agent generates final answer
        Optimized for speed (5-6 seconds max).
        """
        try:
            # Get current state for name checks and step
            current_name = self.conversation_data.get('name', '')
            step = self.conversation_data.get('step', 'chatting')
            should_ask_for_name = self._should_ask_for_name(conversation_history, current_name)
            
            # Automatically determine if we should offer team connection (after 3-4 questions)
            should_offer_team_connection = self._should_offer_team_connection_auto(conversation_history)
            
            # Use Multi-Agent Reasoning System
            multi_agent = MultiAgentReasoning(client, model)
            
            logger.info("[MULTI-AGENT] Starting multi-agent orchestration...")
            assistant_message = multi_agent.orchestrate(
                user_question=user_message,
                rag_context=rag_context,
                conversation_history=conversation_history
            )
            
            # Normalize newlines
            assistant_message = self._normalize_newlines(assistant_message)
            
            # Note: Name asking will be handled separately after answer generation
            
            # Generate suggestions
            needs_info = self._get_needs_info()
            suggestions = self._generate_suggestions(assistant_message, user_message, "search_knowledge_base")
            
            logger.info("[MULTI-AGENT] Completed multi-agent answer generation")
            
            # Remove any follow-up phrases that LLM might have included
            assistant_message = self._remove_followup_phrases(assistant_message)
            
            # Check if we should skip post-processing (information collection flow)
            should_skip_post_processing = self._should_skip_post_processing(
                user_message, [], step, needs_info, assistant_message
            )
            
            # Post-processing: Analyze answer and decide which ONE follow-up message to send (non-blocking)
            # SKIP if we're in information collection mode or user just agreed to connect
            if should_skip_post_processing:
                followup_type, followup_message = "", ""
                logger.info("[POST-PROCESS] Skipping post-processing - in information collection flow")
            else:
                # Get extended conversation history (6-7 messages) for post-processing context
                extended_history = self._get_conversation_history(limit=7)
                followup_type, followup_message = self._analyze_and_generate_followup_message(
                    assistant_message, user_message, extended_history, should_ask_for_name, current_name
                )
            
            return {
                'message': assistant_message,
                'suggestions': suggestions,
                'complete': False,
                'needs_info': needs_info,
                'escalate_to': None,
                'knowledge_results': knowledge_results,
                'metadata': {
                    'knowledge_results': knowledge_results,
                },
                'followup_type': followup_type,  # 'ask_name', 'ask_to_connect', 'follow_up', or ''
                'followup_message': followup_message,
            }
            
        except Exception as e:
            logger.error(f"Error in multi-agent answer generation: {str(e)}", exc_info=True)
            # Fallback to original two-step process
            try:
                # Format RAG context for LLM
                context_text = self._format_rag_context(rag_context)
                
                # STEP 1: Understand question and generate draft answer
                understanding_prompt = f"""You are analyzing a user question about WhipSmart services.

USER QUESTION: {user_message}

RELEVANT CONTEXT FROM KNOWLEDGE BASE:
{context_text}

TASK: 
1. First, clearly understand what the user is asking (informational question)
2. Identify the key points from the context that answer the question
3. Generate a comprehensive draft answer that fully addresses the question

CRITICAL: This is an informational answer - apply Answer Quality Layer:
- Keep answers SHORT - aim for 2-4 key points for most questions
- Expand answers to cover *what we offer*, *how it works*, and *why it matters* - but keep it concise
- Address lifecycle coverage: before (setup/onboarding), during (usage/management), after (renewals/options) - only if relevant
- Include concrete details: operational, financial, digital, and support elements - only what's explicitly in context
- Cover key dimensions: financial, operational, customer experience, risks/edge cases, long-term implications - only if in context
- Use clear structure: headings, bullet points, logical grouping
- REALITY & SCOPE CONSTRAINT (MANDATORY):
  * Only include capabilities explicitly supported by provided context
  * Only include services that exist today
  * Only include benefits that can be delivered immediately
  * Do NOT invent future features, speculative innovations, roadmap items
  * Do NOT expand beyond the given context
  * If unsure, exclude it
- Ensure the answer fully stands on its own without requiring follow-up
- Ensure answer would be acceptable to an enterprise client
- CRITICAL: NEVER include follow-up phrases like "Let me know if you'd like..." or "Let me know if you'd like further guidance!" - just end with the information provided

Provide your analysis in this format:
UNDERSTANDING: [What is the user really asking? What type of question is this - exploratory, operational, or decision-making?]
KEY_POINTS: [List 2-4 main points from context that answer this - avoid duplication, only what's explicitly in context]
DRAFT_ANSWER: [Your SHORT draft answer (2-4 key points) with clear structure, covering what/how/why. CRITICAL: Apply density discipline - prefer concise high-value statements, avoid repetition, each paragraph/bullet must introduce distinct capability or outcome. Only include what exists today and is in the provided context.]

CRITICAL: USE POSITIVE, RESPECTFUL LANGUAGE
- NEVER use negative or rude language (e.g., "if you can't afford", "if you don't have", "if you're unable to")
- ALWAYS reframe negative statements into positive alternatives
- Instead of "If you can't afford the residual payment, you may:" use "You also have options to:" or "Additional options include:"
- Use supportive, helpful language that empowers users
- Focus on solutions and options, not limitations or problems
- Be respectful and professional at all times

IMPORTANT: 
- Use ONLY single \n for line breaks within content - frontend converts each \n to <br> tag
- EXCEPTION: When concluding/leaving a list (transitioning from list items to regular text), use \n\n (double newline) for proper visual separation
- If your draft answer includes nested lists, use exactly 4 spaces (not 3) for indentation per CommonMark specification
Example: 
1. **Main point**:
    - Detail 1 (4 spaces before dash)
    - Detail 2
\n\n
So, whether you're after a new car or a lease, we're here to help!"""

                understanding_messages = [
                {"role": "system", "content": "You are a helpful assistant that analyzes questions and generates answers."},
                    {"role": "user", "content": understanding_prompt}
                ]
                
                logger.info("[TWO-STEP] Step 1: Understanding question and generating draft...")
                understanding_response = client.chat.completions.create(
                    model=model,
                    messages=understanding_messages,
                    temperature=0.3,
                    max_tokens=800  # Increased to allow complete draft answers
                )
                
                draft_analysis = understanding_response.choices[0].message.content.strip()
                
                # STEP 2: Revalidate and improve the answer
                revalidation_prompt = f"""You are reviewing and improving an answer about WhipSmart services.

ORIGINAL QUESTION: {user_message}

DRAFT ANALYSIS:
{draft_analysis}

RELEVANT CONTEXT:
{context_text}

TASK:
1. Review the draft answer - does it fully answer the user's informational question without requiring follow-up?
2. Check if any important information from the context is missing
3. Verify the answer covers lifecycle phases (before/during/after) where relevant
4. Ensure concrete details are included (operational, financial, digital, support)
5. Verify key dimensions are covered: financial, operational, customer experience, risks/edge cases, long-term implications
6. Verify the answer explains what we offer, how it works, and why it matters
7. Check structure: clear headings, bullet points, logical grouping
8. Ensure ongoing obligations, commitments, and what happens if circumstances change are addressed
9. Improve the answer to be more thoughtful, clear, and comprehensive
10. Ensure the answer directly addresses what the user asked
11. CRITICAL: Check for and remove any negative, rude, or insensitive language - reframe into positive alternatives
12. Verify the answer would satisfy an enterprise client or RFP reviewer

CONTENT COMPLETENESS CHECK:
- [ ] Have all major service components been mentioned?
- [ ] Is the value to the customer clearly explained?
- [ ] Are management, tools, and ongoing support included?
- [ ] Is pricing, transparency, or compliance addressed where applicable?
- [ ] Does the answer cover before, during, and after phases where relevant?
- [ ] Are ongoing obligations or commitments mentioned?
- [ ] Are financial impacts clearly explained?
- [ ] Is what happens if circumstances change addressed?
- [ ] Would this satisfy someone making a business decision?
- [ ] Would this be acceptable to an enterprise client?

Provide your improved answer in this format:
IS_COMPLETE: [Yes/No - does the draft fully answer the question without requiring follow-up?]
MISSING_INFO: [Any important information that should be added - lifecycle phases, concrete details, operational elements - only if explicitly in context]
REDUNDANCY_CHECK: [Identify any repeated benefits, filler, duplicate information, or speculative content that should be removed]
REALITY_CHECK: [Verify answer only includes capabilities/services/benefits explicitly in context that exist today - remove any invented features]
IMPROVED_ANSWER: [Your final, SHORT answer (2-4 key points) that is thoughtful, complete, well-structured. CRITICAL: Apply density discipline - concise high-value statements, no repetition, each paragraph/bullet introduces distinct capability/outcome, compressed without losing coverage. REALITY CONSTRAINT: Only include what exists today and is explicitly in the provided context.]

CRITICAL: USE POSITIVE, RESPECTFUL LANGUAGE
- NEVER use negative or rude language (e.g., "if you can't afford", "if you don't have", "if you're unable to")
- ALWAYS reframe negative statements into positive alternatives
- Instead of "If you can't afford the residual payment, you may:" use "You also have options to:" or "Additional options include:"
- Use supportive, helpful language that empowers users
- Focus on solutions and options, not limitations or problems
- Be respectful and professional at all times

IMPORTANT: 
- Use ONLY single \n for line breaks within content - frontend converts each \n to <br> tag
- EXCEPTION: When concluding/leaving a list (transitioning from list items to regular text), use \n\n (double newline) for proper visual separation
- If your improved answer includes nested lists, use exactly 4 spaces (not 3) for indentation per CommonMark specification
Example:
1. **At the end of the lease**, you have options to:
    - Return the vehicle.  (4 spaces before dash)
    - Purchase the vehicle.
\n\n
So, whether you're after a new car or a lease, we're here to help!"""

                revalidation_messages = [
                    {"role": "system", "content": "You are a quality assurance assistant that reviews and improves answers."},
                    {"role": "user", "content": revalidation_prompt}
                ]
                
                logger.info("[TWO-STEP] Step 2: Revalidating and improving answer...")
                revalidation_response = client.chat.completions.create(
                    model=model,
                    messages=revalidation_messages,
                    temperature=0.4,
                    max_tokens=900  # Increased to allow complete improved answers
                )
                
                improved_analysis = revalidation_response.choices[0].message.content.strip()
                
                # STEP 3: Extract final answer and format it properly
                final_answer = self._extract_final_answer(improved_analysis, draft_analysis)
                
                # Build final messages with last 3-4 messages for context
                # Use the messages parameter which already contains last 3-4 conversation history from handle_message
                # Update the system message to include the final answer, but keep conversation history
                final_messages = []
                # Find and replace the system message, keep conversation history
                system_message_found = False
                for msg in messages:
                    if msg.get("role") == "system" and not system_message_found:
                        # Replace system message with updated one that includes final answer
                        final_messages.append({
                            "role": "system",
                            "content": f"""You are Alex AI, WhipSmart's Unified Assistant with a warm, friendly, professional Australian accent.

IMPORTANT: Use the following answer as the basis for your response. Format it naturally with Australian expressions, but keep it professional and helpful.

ANSWER TO USE:
{final_answer}

Remember:
- You are Alex, a subject-matter expert - deliver clear, structured, end-to-end answers
- Use professional Australian expressions naturally (e.g., "no worries", "how are you going", "fair enough")
- Keep the tone professional, confident, and informative (clarity and completeness come first)
- CRITICAL: USE POSITIVE, RESPECTFUL LANGUAGE - NEVER use negative or rude language
- Reframe negative statements into positive alternatives (e.g., "You also have options to:" instead of "If you can't afford, you may:")
- CRITICAL: ALWAYS consider the conversation history (last 3-4 messages) when responding - use it to provide contextually aware answers
- Format with markdown: **bold** for emphasis, headings for major sections, single line breaks (\n) for structure
- Use clear headings or bullet points to organize information logically
- CRITICAL: Use ONLY single \n for line breaks within content - frontend converts each \n to <br> tag
- EXCEPTION: When concluding/leaving a list (transitioning from list items to regular text), use \n\n (double newline) for proper visual separation
- CRITICAL: For nested lists, use exactly 4 spaces (not 3) for indentation per CommonMark specification
  Example: 
  1. **At the end of the lease**, you have options to:
      - Return the vehicle.  (4 spaces before the dash)
      - Purchase the vehicle.
  \n\n
  So, whether you're after a new car or a lease, we're here to help!
- ANSWER DENSITY & DISCIPLINE: Prefer concise high-value statements, avoid repetition, remove filler, each paragraph/bullet introduces distinct capability/outcome, compress without losing coverage
- Ensure the answer fully stands on its own - comprehensive but dense, thorough but concise
- Cover lifecycle phases (before/during/after) where relevant
- Include concrete details: operational, financial, digital, support elements
- If the answer feels long, compress it without losing coverage
- If the user asked a specific question, make sure your answer directly addresses it comprehensively"""
                        })
                        system_message_found = True
                    else:
                        # Keep conversation history (last 3-4 messages)
                        final_messages.append(msg)
                
                # If no system message was found, add it at the beginning
                if not system_message_found:
                    final_messages.insert(0, {
                        "role": "system",
                        "content": f"""You are Alex AI, WhipSmart's Unified Assistant with a warm, friendly, professional Australian accent.

IMPORTANT: Use the following answer as the basis for your response. Format it naturally with Australian expressions, but keep it professional and helpful.

ANSWER TO USE:
{final_answer}

Remember:
- You are Alex, a subject-matter expert - deliver clear, structured, end-to-end answers
- Use professional Australian expressions naturally (e.g., "no worries", "how are you going", "fair enough")
- Keep the tone professional, confident, and informative (clarity and completeness come first)
- CRITICAL: USE POSITIVE, RESPECTFUL LANGUAGE - NEVER use negative or rude language
- Reframe negative statements into positive alternatives (e.g., "You also have options to:" instead of "If you can't afford, you may:")
- CRITICAL: ALWAYS consider the conversation history (last 3-4 messages) when responding - use it to provide contextually aware answers
- Format with markdown: **bold** for emphasis, headings for major sections, single line breaks (\n) for structure
- Use clear headings or bullet points to organize information logically
- CRITICAL: Use ONLY single \n for line breaks within content - frontend converts each \n to <br> tag
- EXCEPTION: When concluding/leaving a list (transitioning from list items to regular text), use \n\n (double newline) for proper visual separation
- CRITICAL: For nested lists, use exactly 4 spaces (not 3) for indentation per CommonMark specification
  Example: 
  1. **At the end of the lease**, you have options to:
      - Return the vehicle.  (4 spaces before the dash)
      - Purchase the vehicle.
  \n\n
  So, whether you're after a new car or a lease, we're here to help!
- ANSWER DENSITY & DISCIPLINE: Prefer concise high-value statements, avoid repetition, remove filler, each paragraph/bullet introduces distinct capability/outcome, compress without losing coverage
- Ensure the answer fully stands on its own - comprehensive but dense, thorough but concise
- Cover lifecycle phases (before/during/after) where relevant
- Include concrete details: operational, financial, digital, support elements
- If the answer feels long, compress it without losing coverage
- If the user asked a specific question, make sure your answer directly addresses it comprehensively"""
                    })
                
                logger.info("[TWO-STEP] Step 3: Generating final formatted answer...")
                final_response = client.chat.completions.create(
                    model=model,
                    messages=final_messages,
                    temperature=0.7,
                    max_tokens=1200  # Increased to ensure complete answers (was 600, causing truncation)
                )
                
                assistant_message = final_response.choices[0].message.content.strip()
                
                # Normalize newlines: replace multiple newlines with single newline (frontend converts \n to <br>)
                assistant_message = self._normalize_newlines(assistant_message)
                
                # Validate answer completeness
                if not self._is_answer_complete(assistant_message):
                    logger.warning("[TWO-STEP] Answer appears incomplete, regenerating with higher token limit...")
                    # Regenerate with higher token limit
                    final_messages[-1]["content"] = final_messages[-1]["content"] + "\n\nIMPORTANT: Ensure your answer is complete and ends with a proper conclusion. Do not cut off mid-sentence."
                    final_response = client.chat.completions.create(
                        model=model,
                        messages=final_messages,
                        temperature=0.7,
                        max_tokens=1500  # Higher limit for regeneration
                    )
                    assistant_message = final_response.choices[0].message.content.strip()
                    assistant_message = self._normalize_newlines(assistant_message)
                
                # Remove any follow-up phrases that LLM might have included
                assistant_message = self._remove_followup_phrases(assistant_message)
                
                # Generate suggestions
                needs_info = self._get_needs_info()
                suggestions = self._generate_suggestions(assistant_message, user_message, "search_knowledge_base")
                
                # Get current state for name checks and step
                current_name = self.conversation_data.get('name', '')
                step = self.conversation_data.get('step', 'chatting')
                should_ask_for_name = self._should_ask_for_name(conversation_history, current_name)
                
                # Check if we should skip post-processing (information collection flow)
                should_skip_post_processing = self._should_skip_post_processing(
                    user_message, [], step, needs_info, assistant_message
                )
                
                # Post-processing: Analyze answer and decide which ONE follow-up message to send (non-blocking)
                # SKIP if we're in information collection mode or user just agreed to connect
                if should_skip_post_processing:
                    followup_type, followup_message = "", ""
                    logger.info("[POST-PROCESS] Skipping post-processing - in information collection flow")
                else:
                    # Get extended conversation history (6-7 messages) for post-processing context
                    extended_history = self._get_conversation_history(limit=7)
                    followup_type, followup_message = self._analyze_and_generate_followup_message(
                        assistant_message, user_message, extended_history, should_ask_for_name, current_name
                    )
                
                logger.info("[TWO-STEP] Completed two-step answer generation")
                
                return {
                    'message': assistant_message,
                    'suggestions': suggestions,
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None,
                    'knowledge_results': knowledge_results,
                    'metadata': {
                        'knowledge_results': knowledge_results,
                    },
                    'followup_type': followup_type,  # 'ask_name', 'ask_to_connect', 'follow_up', or ''
                    'followup_message': followup_message,
                }
            except Exception as e2:
                logger.error(f"Error in fallback two-step process: {str(e2)}", exc_info=True)
                # Final fallback to simple answer with last 3-4 messages for context
                context_text = self._format_rag_context(rag_context)
                fallback_prompt = f"""Based on the following context, answer the user's question: {user_message}

Context:
{context_text}

Provide a clear, CONCISE, structured answer with a professional Australian accent.

CRITICAL: This is an informational answer - apply Answer Quality Layer (non-disruptive):
- Keep answers SHORT - aim for 2-4 key points for most questions, 4-6 for complex ones
- Expand answers to cover *what we offer*, *how it works*, and *why it matters* - but keep it concise
- Address lifecycle coverage: before (setup/onboarding), during (usage/management), after (renewals/options) - only if relevant
- Include concrete details: operational, financial, digital, and support elements - only what's explicitly in context
- Cover key dimensions: financial, operational, customer experience, risks/edge cases, long-term implications - only if in context
- Include ongoing obligations, commitments, and what happens if circumstances change - only if explicitly stated
- Use clear structure: headings, bullet points, logical grouping
- ANSWER DENSITY & DISCIPLINE: Prefer concise high-value statements, avoid repetition, remove filler, each paragraph/bullet introduces distinct capability/outcome, compress without losing coverage
- REALITY & SCOPE CONSTRAINT (MANDATORY):
  * Only include capabilities explicitly supported by provided context
  * Only include services that exist today
  * Only include benefits that can be delivered immediately
  * Do NOT invent future features, speculative innovations, roadmap items
  * Do NOT expand beyond the given context
  * Do NOT add "nice-to-have" services unless explicitly stated
  * If unsure, exclude it
- Ensure the answer fully stands on its own without requiring follow-up
- Ensure answer would be acceptable to an enterprise client
- CRITICAL: NEVER include follow-up phrases like "Let me know if you'd like..." or "Let me know if you'd like further guidance!" - just end with the information provided

CRITICAL: USE POSITIVE, RESPECTFUL LANGUAGE
- NEVER use negative or rude language (e.g., "if you can't afford", "if you don't have", "if you're unable to")
- ALWAYS reframe negative statements into positive alternatives
- Instead of "If you can't afford the residual payment, you may:" use "You also have options to:" or "Additional options include:"
- Use supportive, helpful language that empowers users
- Focus on solutions and options, not limitations or problems
- Be respectful and professional at all times
- CRITICAL: ALWAYS consider the conversation history (last 3-4 messages) when responding - use it to provide contextually aware answers

IMPORTANT: 
- Use ONLY single \n for line breaks within content - frontend converts each \n to <br> tag
- EXCEPTION: When concluding/leaving a list (transitioning from list items to regular text), use \n\n (double newline) for proper visual separation
- If you use nested lists in markdown, use exactly 4 spaces (not 3) for indentation per CommonMark specification
Example:
1. **Main item**:
    - Nested item (4 spaces before dash)
    - Another nested item
\n\n
So, whether you're after a new car or a lease, we're here to help!"""
                
                # Use the messages parameter which already contains last 3-4 conversation history
                # Update system message but keep conversation history
                fallback_messages = []
                system_message_found = False
                for msg in messages:
                    if msg.get("role") == "system" and not system_message_found:
                        # Replace with updated system message
                        fallback_messages.append({
                            "role": "system",
                            "content": "You are Alex AI, WhipSmart's assistant with a professional Australian accent. CRITICAL: ALWAYS consider the conversation history (last 3-4 messages) when responding - use it to provide contextually aware answers."
                        })
                        system_message_found = True
                    else:
                        # Keep conversation history (last 3-4 messages)
                        fallback_messages.append(msg)
                
                # Add the fallback prompt as user message
                fallback_messages.append({"role": "user", "content": fallback_prompt})
                
                # If no system message was found, add it at the beginning
                if not system_message_found:
                    fallback_messages.insert(0, {
                        "role": "system",
                        "content": "You are Alex AI, WhipSmart's assistant with a professional Australian accent. CRITICAL: ALWAYS consider the conversation history (last 3-4 messages) when responding - use it to provide contextually aware answers."
                    })
                
                fallback_response = client.chat.completions.create(
                    model=model,
                    messages=fallback_messages,
                    temperature=0.7,
                    max_tokens=1200  # Increased to ensure complete answers (was 500, causing truncation)
                )
                
                assistant_message = fallback_response.choices[0].message.content.strip()
                # Normalize newlines: replace multiple newlines with single newline (frontend converts \n to <br>)
                assistant_message = self._normalize_newlines(assistant_message)
                
                # Validate answer completeness
                if not self._is_answer_complete(assistant_message):
                    logger.warning("[FALLBACK] Answer appears incomplete, regenerating with higher token limit...")
                    # Regenerate with higher token limit
                    fallback_messages[-1]["content"] = fallback_messages[-1]["content"] + "\n\nIMPORTANT: Ensure your answer is complete and ends with a proper conclusion. Do not cut off mid-sentence."
                    fallback_response = client.chat.completions.create(
                        model=model,
                        messages=fallback_messages,
                        temperature=0.7,
                        max_tokens=1500  # Higher limit for regeneration
                    )
                    assistant_message = fallback_response.choices[0].message.content.strip()
                    assistant_message = self._normalize_newlines(assistant_message)
                needs_info = self._get_needs_info()
                suggestions = self._generate_suggestions(assistant_message, user_message, "search_knowledge_base")
                
                return {
                    'message': assistant_message,
                    'suggestions': suggestions,
                    'complete': False,
                    'needs_info': needs_info,
                    'escalate_to': None,
                    'knowledge_results': knowledge_results,
                    'metadata': {
                        'knowledge_results': knowledge_results,
                    },
                }
    
    def _format_rag_context(self, rag_context: list) -> str:
        """Format RAG context chunks for LLM consumption."""
        if not rag_context:
            return "No relevant context found."
        
        formatted = []
        for i, chunk in enumerate(rag_context[:4], 1):  # Top 4 chunks
            text = chunk.get('text', '')
            source = chunk.get('reference_url') or chunk.get('url') or chunk.get('document_title', '')
            score = chunk.get('score', 0.0)
            
            chunk_text = f"[Context {i}] (Relevance: {score:.2f})\n{text}"
            if source:
                chunk_text += f"\nSource: {source}"
            formatted.append(chunk_text)
        
        return "\n\n".join(formatted)
    
    def _normalize_newlines(self, text: str) -> str:
        """
        Normalize newlines: preserve \n\n (allowed when concluding/leaving a list),
        but normalize excessive newlines (3+ consecutive) to \n\n.
        Frontend converts each \n to <br> tag, so \n\n creates proper spacing when leaving lists.
        """
        import re
        # Normalize excessive newlines (3+ consecutive) to \n\n
        # This preserves intentional \n\n while removing unwanted \n\n\n+
        return re.sub(r'\n{3,}', '\n\n', text)
    
    def _is_answer_complete(self, answer: str) -> bool:
        """
        Check if an answer is complete (doesn't end mid-sentence).
        
        Returns True if answer appears complete, False if it seems truncated.
        """
        if not answer or len(answer.strip()) < 10:
            return False
        
        # Remove trailing whitespace and newlines
        answer_trimmed = answer.strip()
        
        # Check if answer ends with proper punctuation
        proper_endings = ['.', '!', '?', ':', ';']
        if answer_trimmed[-1] in proper_endings:
            return True
        
        # Check for incomplete sentence patterns
        incomplete_patterns = [
            r'\b(by|with|for|to|in|on|at|from|of|and|or|but|if|when|where|how|what|why|who)\s*$',
            r'\b(evaluating|considering|reviewing|analyzing|examining|assessing)\s*$',
            r'\b(that|which|who|whom|whose)\s*$',
            r'^[A-Z][a-z]+\s*$',  # Single word at end
        ]
        
        import re
        for pattern in incomplete_patterns:
            if re.search(pattern, answer_trimmed, re.IGNORECASE):
                logger.warning(f"[UNIFIED AGENT] Answer appears incomplete (pattern: {pattern})")
                return False
        
        # If answer is very short and doesn't end with punctuation, might be incomplete
        if len(answer_trimmed) < 50 and answer_trimmed[-1] not in proper_endings:
            return False
        
        # If answer ends with a comma or dash, likely incomplete
        if answer_trimmed[-1] in [',', '-', '—']:
            return False
        
        return True
    
    def _extract_final_answer(self, improved_analysis: str, draft_analysis: str) -> str:
        """Extract the final answer from the improved analysis."""
        # Try to extract from IMPROVED_ANSWER section
        if "IMPROVED_ANSWER:" in improved_analysis:
            parts = improved_analysis.split("IMPROVED_ANSWER:", 1)
            if len(parts) > 1:
                answer = parts[1].strip()
                # Remove any trailing sections
                if "\n" in answer:
                    answer = answer.split("\n")[0]
                return answer
        
        # Fallback: try DRAFT_ANSWER
        if "DRAFT_ANSWER:" in draft_analysis:
            parts = draft_analysis.split("DRAFT_ANSWER:", 1)
            if len(parts) > 1:
                answer = parts[1].strip()
                if "\n" in answer:
                    answer = answer.split("\n")[0]
                return answer
        
        # Last resort: use improved analysis as-is (first paragraph)
        return improved_analysis.split("\n\n")[0] if "\n\n" in improved_analysis else improved_analysis[:500]
    
    def _build_system_prompt(self, name: str, email: str, phone: str, step: str, should_ask_for_name: bool = False, rag_context: Optional[list] = None) -> str:
        """Build system prompt based on current state."""
        prompt = """You are Alex AI, WhipSmart's Unified Assistant with a warm, friendly, professional Australian accent. Your PRIMARY GOAL is to help users understand WhipSmart's services AND convert them to connect with our team.

CRITICAL: You MUST speak with a professional Australian accent throughout all interactions:
- Use Australian expressions naturally and professionally (e.g., "no worries", "how are you going", "fair enough", "too easy", "cheers")
- Keep the tone warm, friendly, and professional with a subtle Australian flavour
- Use Australian expressions sparingly and naturally - do not overuse slang
- Maintain a professional, well-behaved manner in all responses
- Examples: "How are you going?", "No worries!", "Fair enough!", "Too easy!", "Cheers!"

MAIN GOAL: Understand user's intent, answer their questions, and CONVERT users to connect with our team.

CONVERSION STRATEGY:
- Focus on answering user questions clearly and helpfully
- The system will automatically offer team connection when appropriate (after 3-4 questions)
- Do NOT include team connection phrases in your responses - the system handles this separately

CRITICAL: UNDERSTAND USER INTENT AND ASK CLARIFYING QUESTIONS
- ALWAYS read the conversation history (last 3-4 messages) to understand what the user is asking
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

CRITICAL: WHEN ALL DETAILS ARE COLLECTED (Step is 'confirmation'):
- If Name, Email, and Phone are all provided AND step is 'confirmation':
  - Acknowledge that you've collected all their details
  - Inform them that their details will be submitted to the team
  - Let them know the team will contact them shortly
  - Ask if they need any help or want to ask anything else
  - Example response: "Perfect! I've got all your details sorted. I'll submit them to our team and they'll contact you shortly. Is there anything else you'd like to know, or are you all set?"
  - Do NOT just say "How can I assist you further?" - properly acknowledge the collection and team contact
  - Make it clear that their details are being submitted for team connection

CRITICAL: PERSONALIZATION - ALWAYS ADDRESS USER BY NAME:
- If Name is provided (not "Not provided"), you MUST address the user by their name in EVERY response
- MANDATORY: ALWAYS start your answer with their name or include it naturally in the first sentence
- Use their FIRST NAME only (if full name like "Noah Nicolas" is provided, use just "Noah")
- Examples: "Great question, {name}!" or "{name}, here's what I found:" or "Here's what I found for you, {name}:"
- This makes the conversation more formal and personalized - it's REQUIRED, not optional
- Do NOT overuse the name - once per response is typically sufficient
- NEVER ask for the user's name again once it's stored - just use it naturally
- CRITICAL: Do NOT say things like "Since I already have your name", "I already have your details", "no need to ask again" - just use the name naturally

USING STORED INFORMATION:
- If Email is provided (not "Not provided"), NEVER ask for email again - just use it if needed
- If Phone is provided (not "Not provided"), NEVER ask for phone again - just use it if needed
- ALWAYS check the CURRENT STATE before asking for any information - if it's already stored, use it naturally without acknowledging that you have it
- When user provides their name naturally in conversation (e.g., "I'm Pat" or "My name is Pat" or just "Pat"), IMMEDIATELY use the collect_user_info tool to extract and store it
- When user provides email or phone naturally, IMMEDIATELY use the collect_user_info tool to extract and store it
- If user says their name is something different from what's stored, use update_user_info tool to update it

YOUR CAPABILITIES:
1. Answer questions about WhipSmart services using knowledge base (RAG tool)
2. Search for available vehicles (car search tool)
3. Collect user information when they want to connect with our team
4. Ask clarifying questions when user intent is unclear
5. End conversation gracefully when user is done

CRITICAL: ANSWER CONTENT ONLY - NO FOLLOW-UP PHRASES:
- Your answer should ONLY contain the actual answer to the user's question
- DO NOT include ANY follow-up phrases or invitations in your answer such as:
  * "If you'd like more details about how [topic] could work for you, feel free to ask!"
  * "Let me know if you'd like to explore this further!"
  * "Let me know if you'd like more details!"
  * "Let me know if you'd like further guidance!"
  * "Let me know..." (ANY variation - NEVER use this phrase)
  * "Would you like to connect with our team..."
  * "Feel free to ask if you'd like..."
  * "If you have any questions..."
  * "If you need more information..."
  * "If you're interested..."
  * Any invitation to ask more questions or explore further
  * Any phrase starting with "Let me know" - NEVER use this phrase
- End your answer naturally after providing the information - do NOT add follow-up invitations
- The system will automatically handle follow-up messages separately AFTER your answer is sent
- Your answer should be complete and standalone - just the answer, nothing else
- CRITICAL: Never end your answer with phrases like "Let me know..." - just end with the information provided

WHEN TO COLLECT USER INFORMATION:
- User says "yes" to connecting with team
- User provides contact information (email, phone, name) in their message
- User wants to schedule a call
- User shows interest in WhipSmart services
- User asks about pricing, plans, onboarding, consultation
- You cannot fully assist and need human help
- User explicitly asks to speak with someone

CRITICAL: When user provides contact details:
- ALWAYS use collect_user_info tool to extract and store the information - even if they provide it naturally in conversation (e.g., "I'm Pat", "My name is Pat", "Pat", "pat@email.com", "my email is pat@email.com")
- Extract name, email, or phone from ANY user message - don't wait for them to explicitly say "my name is" or "my email is"
- If user just says their name (e.g., "Pat"), treat it as them providing their name and use collect_user_info tool
- Acknowledge and thank them for providing their details
- Ask if they need any other help or if they're done
- Do NOT search knowledge base or provide generic contact information when user is submitting their details
- Do NOT ask for information that's already stored in CURRENT STATE - check first!

ANSWER QUALITY LAYER (NON-DISRUPTIVE) - APPLIES ONLY TO INFORMATIONAL ANSWERS:

CRITICAL: This quality layer applies ONLY when answering informational, explanatory, or decision-support questions.
DO NOT apply when:
- The system is collecting user details (name, contact info) - follow existing behavior exactly
- The system is offering team connection or escalation - follow existing behavior exactly
- The system is following a scripted flow - follow existing behavior exactly
- The system asks you to ask a question - follow existing behavior exactly

Your responsibility is limited to **how answers are written**, not **what actions are taken**.

WHEN TO APPLY THIS QUALITY LAYER:
Apply these rules ONLY when:
- The user asks an informational, explanatory, or decision-support question about WhipSmart services
- You are providing knowledge-based answers using search_knowledge_base tool results
- You are explaining concepts, processes, benefits, or features

DO NOT apply when:
- Collecting user information (name, email, phone)
- Offering team connection
- Following scripted conversation flows
- Asking clarifying questions
- Ending conversations

CORE OBJECTIVE (for informational answers only):
- Provide **clear, structured, and complete answers**
- Use the provided context accurately
- Cover the full lifecycle and real-world implications
- Match the depth expected of an expert assistant

INTERNAL REASONING STEPS (DO NOT OUTPUT - internal only):
Before answering informational questions:
1. Identify the intent of the user question
2. Identify required depth (default to comprehensive)
3. Identify key dimensions:
   - Financial
   - Operational
   - Customer experience
   - Risks and edge cases
   - Long-term implications

RESPONSE STRUCTURE RULES (for informational answers):
- Use structured bullets or headings
- Explain:
  - What it is
  - How it works
  - Why it matters
- Avoid generic marketing language without explanation
- Use markdown formatting: **bold** for emphasis, headings for major sections, single line breaks (\n) for structure
- CRITICAL: Use ONLY single \n for line breaks within content - frontend converts each \n to <br> tag
- EXCEPTION: When concluding/leaving a list (transitioning from list items to regular text), use \n\n (double newline) for proper visual separation
- CRITICAL: For nested lists in markdown, ALWAYS use exactly 4 spaces (not 3) for indentation per CommonMark specification

CONTENT COMPLETENESS CHECK (for informational answers):
Ensure the answer includes, where relevant:
- End-to-end lifecycle coverage (before/during/after)
- Ongoing obligations or commitments
- Financial impacts
- What happens if circumstances change
- Transparency and support mechanisms
- Operational, financial, digital, and support-related elements

If something important is missing, expand the answer.

TONE & STYLE (for informational answers):
- Professional and confident
- Friendly but not casual
- No emojis
- No unnecessary enthusiasm
- Prioritize clarity and completeness
- Use professional Australian accent naturally (e.g., "no worries", "how are you going", "fair enough")
- CRITICAL: USE POSITIVE, RESPECTFUL LANGUAGE - NEVER use negative or rude language
- NEVER say things like "if you can't afford", "if you don't have", "if you're unable to" - these are rude and insensitive
- ALWAYS reframe negative statements into positive alternatives (e.g., "You also have options to:" instead of "If you can't afford, you may:")
- CRITICAL: Keep responses simple and formal - do NOT mention that you already have information (e.g., "Since I already have your name", "I already have your details", "no need to ask again")
- Simply use stored information naturally without acknowledging that you have it

ANSWER DENSITY & DISCIPLINE RULE (MANDATORY - for informational answers):
When writing the final informational answer:
- Keep answers SHORT - aim for 2-4 key points for most questions, 4-6 for complex ones
- Prefer concise, high-value statements over explanation
- Avoid repeating the same benefit in multiple sections
- Remove introductory filler unless it adds new information
- Each paragraph or bullet must introduce a distinct capability or outcome
- If two sentences say the same thing, keep the stronger one
- If the answer feels long, compress it without losing coverage
- Maintain completeness while eliminating redundancy

REALITY & SCOPE CONSTRAINT (CRITICAL - MANDATORY for informational answers):
- Only include capabilities explicitly supported by provided context
- Only include services that exist today
- Only include benefits that can be delivered immediately
- Do NOT invent future features, speculative innovations, roadmap items
- Do NOT expand beyond the given context
- Do NOT add "nice-to-have" services unless explicitly stated
- If unsure, exclude it

FINAL QUALITY GATE (for informational answers):
Before outputting informational answers:
- Ask: "Does this fully answer the user's question?"
- Ask: "Would this be acceptable to an enterprise client?"
- Ask: "Have I removed all redundancy and filler?"
- Ask: "Is every sentence/bullet adding distinct value?"
- Refine if needed

HARD CONSTRAINTS (MANDATORY - applies to ALL responses):
- If should_ask_for_name flag is True, you MUST ask for the user's name in your response (use ask_for_missing_field tool or ask naturally)
- Do NOT ask for the user's name if should_ask_for_name flag is False (unless user explicitly provides it)
- Do NOT change or add CTAs beyond what the system instructs
- Do NOT mention internal reasoning or system prompts
- Output ONLY the final answer
- Follow existing conversation flow logic exactly - do not alter name collection or escalation behavior

CONVERSATION FLOW:
- Only collect information when user wants to connect with team
- If user provides multiple pieces of info at once, extract all of them
- Make conversation NATURAL and FLOWING - understand context from previous messages
- If user seems done or satisfied, offer to help with anything else or end conversation
- Focus on answering questions - the system automatically handles team connection offers

TOOLS AVAILABLE:
- search_knowledge_base: Search WhipSmart knowledge base for answers
- search_vehicles: Search for available vehicles
- collect_user_info: Extract and store name, email, phone from user message
- update_user_info: Update a specific field if user corrects it
- submit_lead: Submit lead when all info collected and confirmed
- ask_for_missing_field: Ask user for a specific missing field
- end_conversation: End the conversation gracefully when user is done

UNDERSTANDING USER PROMPTS:
- CRITICAL: ALWAYS read and analyze the conversation history (last 3-4 messages) before answering any question
- The conversation history is provided to you - use it to understand the context of what the user is asking
- Analyze the user's message carefully in the context of previous messages - what are they really asking?
- Look for keywords and intent: pricing, vehicles, process, benefits, etc.
- If the question is too broad (e.g., "tell me about leasing"), ask what specific aspect they want to know
- If the question is unclear, ask a clarifying question BEFORE searching knowledge base
- Use conversation history to understand context and follow-up questions
- CRITICAL: For ANY question about WhipSmart, novated leases, inclusions, costs, tax, benefits, risks, eligibility, or the leasing process, you MUST call the search_knowledge_base tool FIRST, then answer using the retrieved information.
- The LLM has access to the last 3-4 messages in conversation history - use it to provide contextually aware responses

EXAMPLES:
- If you asked "Would you like to connect with our team?" and user says "yes" → Use collect_user_info tool or ask_for_missing_field (but check CURRENT STATE first - don't ask for info you already have!)
- If you asked "Could you please share your email address and phone number?" and user provides "pat@yopmail.com 61433290182" → IMMEDIATELY use collect_user_info tool to extract email and phone - do NOT search knowledge base
- If user provides contact information (email, phone, name) → ALWAYS use collect_user_info tool first - this is NOT a question, it's information submission
- If user says their name naturally (e.g., "I'm Pat", "My name is Pat", or just "Pat") → IMMEDIATELY use collect_user_info tool to extract and store the name
- If user says "Pat" in response to a question, check if it's their name being provided → Use collect_user_info tool to store it
- If Name is already stored (e.g., "Pat") and user asks a question → Address them by name: "Thanks, Pat! Here's what I found..." - do NOT ask for name again
- If you asked "Would you like further details?" and user says "yes" → Use search_knowledge_base with the topic from previous conversation
- If user says "yes" without clear context → Look at last assistant message to understand what they're agreeing to
- If user says "I'm done", "no more questions", "thank you, goodbye", "that's all", "I'm all set", "nothing else" → Use end_conversation tool
- CRITICAL: Do NOT call end_conversation or submit_lead automatically after collecting info - continue asking about WhipSmart topics
- CRITICAL: Only end conversation when user EXPLICITLY says they're done or have no more questions
- If user's question is vague like "tell me about leasing" → Ask clarifying question: "Would you like to know about novated leases, the leasing process, or vehicle options?"
- If user asks "what are the benefits?" without context → Ask: "Are you asking about the benefits of novated leases, electric vehicles, or WhipSmart's services?"
- If ALL details (name, email, phone) are collected and step is 'confirmation' → Say: "Perfect! I've got all your details sorted. I'll submit them to our team and they'll contact you shortly. While you're here, is there anything else you'd like to know about WhipSmart's EV leasing services, novated leases, or how we can help you?" Then CONTINUE the conversation asking about WhipSmart topics - do NOT end the conversation or call submit_lead/end_conversation unless user explicitly says they're done.
- Focus on answering questions clearly - the system automatically handles team connection offers after 3-4 questions
- CRITICAL: When user provides contact details (email/phone), acknowledge and thank them, then ask if they need other help or if they're done
- CRITICAL: If Name is already stored, use it in your responses - personalize the conversation by addressing them by name
- CRITICAL: When ALL details (name, email, phone) are collected and step is 'confirmation':
  - Acknowledge: "Perfect! I've got all your details sorted."
  - Inform about submission: "I'll submit them to our team and they'll contact you shortly."
  - Continue engaging: "While you're here, is there anything else you'd like to know about WhipSmart's EV leasing services, novated leases, or how we can help you?"
  - IMPORTANT: After collecting info, CONTINUE the conversation asking about WhipSmart topics - do NOT automatically call submit_lead or end_conversation
  - Only call submit_lead or end_conversation if user explicitly says they're done, have no more questions, or want to end
  - Keep asking about WhipSmart-related topics until user explicitly declines or says they're finished

Remember: You are Alex AI with a professional Australian accent - be warm, friendly, and professional. Your MAIN GOAL is to understand user intent and answer questions clearly. The system automatically handles team connection offers - focus on providing helpful answers. Always use Australian expressions naturally and professionally.

FINAL REMINDER ABOUT STORED INFORMATION:
- Check the CURRENT STATE above - if Name shows an actual name (not "Not provided"), you MUST use it in your response
- If Name is stored, address the user by name naturally (e.g., "Thanks, {name}!" or "{name}, here's what I found...")
- CRITICAL: Do NOT mention that you already have their information (e.g., "Since I already have your name", "I already have your details", "no need to ask again")
- Simply use their name naturally without acknowledging that you already have it
- If Name is stored, NEVER ask "What should I call you?" or "May I know your name?" - just use their name
- If Email or Phone is stored, NEVER ask for it again - just use it if needed
- When user provides their name naturally (even just saying "Pat"), extract it using collect_user_info tool immediately
- Keep responses simple and formal - avoid unnecessary explanations about what information you have

CRITICAL ACTION ITEMS (MUST FOLLOW - CHECK FLAGS ABOVE):
- If should_ask_for_name flag is True: You MUST ask for the user's name in this response (use ask_for_missing_field tool with field='name' OR ask naturally)
- These are MANDATORY actions when flags are True - do not skip them""".format(
            name=name or "Not provided",
            email=email or "Not provided",
            phone=phone or "Not provided",
            step=step
        )
        
        # Add instruction to ask for name if needed
        if should_ask_for_name:
            logger.info(f"[NAME COLLECTION] Flag set to True - instructing LLM to ask for name. Current name: {name}")
            prompt += "\n\n🚨 CRITICAL INSTRUCTION - NAME COLLECTION (MANDATORY): 🚨\nThe user has asked 2-3 questions but hasn't provided their name yet. You MUST ask for their name in your response.\n\nOPTIONS:\n1. Use the ask_for_missing_field tool with field='name' (RECOMMENDED)\n2. OR naturally ask in your response after answering their question\n\nExamples of natural asking:\n- 'By the way, I'd love to know your name so I can personalize our conversation! What should I call you?'\n- 'I'd like to address you properly - may I know your name?'\n- 'What should I call you?'\n\nIMPORTANT: Do this AFTER answering their current question. Make it feel natural and conversational."
        
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
                    "description": "Extract name, email, or phone from user message and store it. CRITICAL: ALWAYS use this tool when user provides contact information (email address, phone number, or name) in their message. Use when: 1) User provides email/phone/name (e.g., 'pat@yopmail.com 61433290182'), 2) User says their name naturally (e.g., 'I'm Pat', 'My name is Pat', or just 'Pat'), 3) User says 'yes' to connecting with team, 4) User responds to a request for their contact details, 5) User provides any name, email, or phone number in ANY form in their message. IMPORTANT: If user provides email/phone/name in their message (even naturally like just saying 'Pat'), you MUST call this tool to extract and store the information - do NOT search knowledge base or provide generic contact information. If the user just says a name like 'Pat' without context, treat it as them providing their name and extract it.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Full name if provided in the message (even if just a single name like 'Pat'), otherwise null"
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
                    "description": "Submit the lead ONLY when user explicitly confirms they want to submit (e.g., says 'yes' to confirmation question, 'submit my details', 'go ahead and submit'). DO NOT call this automatically after collecting info - continue the conversation asking about WhipSmart topics until user explicitly confirms submission or says they're done.",
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
                    "name": "ask_for_missing_field",
                    "description": "Ask user for a specific missing field (name, email, or phone). Use this when you need to collect user information, especially when subtly asking for their name after they've asked several questions.",
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
                        # Prefer explicit reference_url, then url, for link back to source
                        source = r.get('reference_url') or r.get('url') or ''
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
        # Always update name if provided, especially if new name is full name and old one wasn't
        if args.get('name'):
            new_name = args['name'].strip()
            current_name = self.conversation_data.get('name', '')
            
            # Update if: no name exists, or new name is full name and current isn't, or new name is different
            should_update_name = (
                not current_name or 
                (self._is_full_name(new_name) and not self._is_full_name(current_name)) or
                new_name != current_name
            )
            
            if should_update_name and self._validate_name(new_name):
                self.conversation_data['name'] = new_name
                updated_fields.append('name')
        
        # Extract and validate email - always update if provided
        if args.get('email'):
            new_email = args['email'].strip().lower()
            current_email = self.conversation_data.get('email', '')
            
            if (not current_email or new_email != current_email) and self._validate_email(new_email):
                self.conversation_data['email'] = new_email
                updated_fields.append('email')
        
        # Extract and validate phone - always update if provided
        if args.get('phone'):
            new_phone = args['phone'].strip()
            current_phone = self.conversation_data.get('phone', '')
            
            if (not current_phone or new_phone != current_phone) and self._validate_phone(new_phone):
                # Format phone number with +61 prefix
                formatted_phone = format_phone_number(new_phone)
                self.conversation_data['phone'] = formatted_phone
                updated_fields.append('phone')
        
        # Update step if all fields collected
        name = self.conversation_data.get('name')
        email = self.conversation_data.get('email')
        phone = self.conversation_data.get('phone')
        
        # Check if we need to ask for full name
        needs_full_name = False
        if name and not self._is_full_name(name):
            needs_full_name = True
        
        if name and email and phone:
            # Only proceed if we have a full name
            if self._is_full_name(name):
                # Update step to confirmation if not already there
                if self.conversation_data.get('step') != 'confirmation':
                    self.conversation_data['step'] = 'confirmation'
                
                # ALWAYS try to create contact in HubSpot if not already created
                # This ensures contact is created even if step was already 'confirmation'
                if not self.conversation_data.get('hubspot_contact_id'):
                    try:
                        # Split name into firstname and lastname
                        name_parts = name.strip().split(maxsplit=1)
                        firstname = name_parts[0] if name_parts else name
                        lastname = name_parts[1] if len(name_parts) > 1 else ""
                        
                        logger.info("Attempting to create HubSpot contact: %s %s (%s)", firstname, lastname, email)
                        
                        # Create contact in HubSpot
                        contact_result = create_contact(
                            firstname=firstname,
                            lastname=lastname,
                            email=email,
                            phone=phone,
                            hs_lead_status="NEW",
                            lifecyclestage="lead"
                        )
                        
                        if contact_result:
                            self.conversation_data['hubspot_contact_id'] = contact_result.get('contact_id')
                            self.conversation_data['lead_submitted'] = True  # Mark lead as submitted to team
                            logger.info("HubSpot contact created successfully: %s for %s (%s)", 
                                      contact_result.get('contact_id'), name, email)
                        else:
                            logger.warning("Failed to create HubSpot contact for %s (%s) - create_contact returned None", name, email)
                            # Even if HubSpot fails, consider lead submitted since we have all details
                            self.conversation_data['lead_submitted'] = True
                    except Exception as e:
                        logger.error("Error creating HubSpot contact: %s", str(e), exc_info=True)
                        # Don't fail the collection if HubSpot creation fails
                else:
                    # HubSpot contact already exists - update it if fields changed
                    hubspot_contact_id = self.conversation_data.get('hubspot_contact_id')
                    if hubspot_contact_id and updated_fields:
                        try:
                            # Prepare update properties based on updated fields
                            update_properties = {}
                            
                            if 'name' in updated_fields:
                                # Split name into firstname and lastname
                                name_parts = name.strip().split(maxsplit=1)
                                update_properties['firstname'] = name_parts[0] if name_parts else name
                                update_properties['lastname'] = name_parts[1] if len(name_parts) > 1 else ""
                            
                            if 'email' in updated_fields:
                                update_properties['email'] = email
                            
                            if 'phone' in updated_fields:
                                update_properties['phone'] = phone
                            
                            # Update contact in HubSpot
                            if update_properties:
                                update_result = update_contact(
                                    contact_id=hubspot_contact_id,
                                    **update_properties
                                )
                                
                                if update_result:
                                    logger.info("HubSpot contact %s updated successfully with fields: %s", 
                                              hubspot_contact_id, ', '.join(updated_fields))
                                else:
                                    logger.warning("Failed to update HubSpot contact %s for fields: %s", 
                                                 hubspot_contact_id, ', '.join(updated_fields))
                        except Exception as e:
                            logger.error("Error updating HubSpot contact %s: %s", hubspot_contact_id, str(e), exc_info=True)
                            # Don't fail the collection if HubSpot update fails
                    else:
                        logger.debug("HubSpot contact already exists: %s", self.conversation_data.get('hubspot_contact_id'))
            else:
                # Name is not full, don't move to confirmation yet
                needs_full_name = True
                logger.debug("Full name required. Current name: '%s'", name)
        else:
            # Not all fields collected yet, but if HubSpot contact exists and fields were updated, update HubSpot
            hubspot_contact_id = self.conversation_data.get('hubspot_contact_id')
            if hubspot_contact_id and updated_fields:
                try:
                    update_properties = {}
                    
                    if 'name' in updated_fields and name:
                        name_parts = name.strip().split(maxsplit=1)
                        update_properties['firstname'] = name_parts[0] if name_parts else name
                        update_properties['lastname'] = name_parts[1] if len(name_parts) > 1 else ""
                    
                    if 'email' in updated_fields and email:
                        update_properties['email'] = email
                    
                    if 'phone' in updated_fields and phone:
                        update_properties['phone'] = phone
                    
                    if update_properties:
                        update_result = update_contact(
                            contact_id=hubspot_contact_id,
                            **update_properties
                        )
                        
                        if update_result:
                            logger.info("HubSpot contact %s updated successfully with fields: %s", 
                                      hubspot_contact_id, ', '.join(updated_fields))
                except Exception as e:
                    logger.error("Error updating HubSpot contact %s: %s", hubspot_contact_id, str(e), exc_info=True)
        
        self._save_conversation_data()
        
        response = {
            "success": True,
            "updated_fields": updated_fields,
            "current_data": {
                "name": self.conversation_data.get('name', ''),
                "email": self.conversation_data.get('email', ''),
                "phone": self.conversation_data.get('phone', '')
            },
            "missing_fields": self._get_missing_fields(),
            "hubspot_contact_id": self.conversation_data.get('hubspot_contact_id')
        }
        
        # Add flag if full name is needed
        if needs_full_name:
            response["needs_full_name"] = True
        
        return response
    
    def _tool_update_user_info(self, args: Dict) -> Dict:
        """Update a specific field."""
        field = args.get('field')
        value = args.get('value', '').strip()
        
        if not field or not value:
            return {"error": "Field and value are required"}
        
        # Get current values before update
        current_name = self.conversation_data.get('name', '')
        current_email = self.conversation_data.get('email', '')
        current_phone = self.conversation_data.get('phone', '')
        hubspot_contact_id = self.conversation_data.get('hubspot_contact_id')
        
        # Validate and update local data
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
            formatted_phone = format_phone_number(value)
            self.conversation_data['phone'] = formatted_phone
        else:
            return {"error": f"Unknown field: {field}"}
        
        self._save_conversation_data()
        
        # Update HubSpot contact if it exists
        if hubspot_contact_id:
            try:
                # Prepare update properties based on field
                update_properties = {}
                
                if field == 'name':
                    # Split name into firstname and lastname
                    name_parts = value.strip().split(maxsplit=1)
                    update_properties['firstname'] = name_parts[0] if name_parts else value
                    update_properties['lastname'] = name_parts[1] if len(name_parts) > 1 else ""
                elif field == 'email':
                    update_properties['email'] = value.lower()
                elif field == 'phone':
                    update_properties['phone'] = format_phone_number(value)
                
                # Update contact in HubSpot
                update_result = update_contact(
                    contact_id=hubspot_contact_id,
                    **update_properties
                )
                
                if update_result:
                    logger.info("HubSpot contact %s updated successfully: %s changed to %s", 
                              hubspot_contact_id, field, value[:3] + "***" if field == 'email' else value)
                else:
                    logger.warning("Failed to update HubSpot contact %s for field %s", hubspot_contact_id, field)
            except Exception as e:
                logger.error("Error updating HubSpot contact %s: %s", hubspot_contact_id, str(e), exc_info=True)
                # Don't fail the update if HubSpot update fails
        
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
        
        # Mark as complete and lead as submitted
        self.conversation_data['step'] = 'complete'
        self.conversation_data['submitted_at'] = timezone.now().isoformat()
        self.conversation_data['lead_submitted'] = True  # Mark lead as submitted to prevent future "connect with team" prompts
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
    
    def _is_full_name(self, name: str) -> bool:
        """Check if name contains both first and last name (at least 2 words)."""
        if not name:
            return False
        name_parts = name.strip().split()
        return len(name_parts) >= 2
    
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
        
        # Get conversation history for context (last 3-4 messages)
        conversation_history = self._get_conversation_history(limit=4)
        
        # If user is already in lead collection flow, don't show suggestions
        # NOTE: 'confirmation' step should still show suggestions - continue engaging about WhipSmart topics
        if self.conversation_data.get('step') == 'complete':
            return []
        
        # NOTE: Even if all info is collected, continue showing suggestions to engage about WhipSmart topics
        # Only stop when conversation is explicitly marked as complete
        
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
                        name = self.conversation_data.get('name', '')
                        email = self.conversation_data.get('email', '')
                        phone = self.conversation_data.get('phone', '')
                        step = self.conversation_data.get('step', '')
                        
                        if 'email' in missing:
                            return f"Thank you{', ' + name.split()[0] if name else ''}! Could you please provide your email address?"
                        elif 'phone' in missing:
                            return f"Perfect! Now, could you please provide your phone number?"
                        elif not missing and name and email and phone:
                            # All details collected - acknowledge properly
                            first_name = name.split()[0] if name else ""
                            return f"Perfect{', ' + first_name if first_name else ''}! I've got all your details sorted. I'll submit them to our team and they'll contact you shortly. Is there anything else you'd like to know, or are you all set?"
                        elif not missing:
                            # Partial collection - show confirmation format
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
    
    def _should_skip_post_processing(self, user_message: str, function_names: list, step: str, needs_info: Optional[str], assistant_message: str = "") -> bool:
        """
        Determine if post-processing (follow-up messages) should be skipped.
        Skip ONLY when we're ACTIVELY collecting information, not just when information is missing.
        
        Skip when:
        1. We're in information collection step (step is 'name', 'email', 'phone', 'confirmation', 'complete')
        2. LLM is actively collecting user information (collect_user_info or ask_for_missing_field tool was called)
        3. User just said "yes" to connecting with team (transitioning to collection mode)
        4. Current assistant message is asking for user details (name, email, phone)
        
        DO NOT skip when:
        - needs_info is set but step is 'chatting' (just missing info, not actively collecting)
        - We're answering informational questions (should allow follow-up messages)
        """
        user_lower = user_message.lower().strip()
        assistant_lower = assistant_message.lower() if assistant_message else ""
        
        # Skip if we're in information collection step (actively collecting)
        # NOTE: 'confirmation' is NOT skipped - after collecting info, we should continue asking about WhipSmart topics
        if step in ['name', 'email', 'phone', 'complete']:
            logger.info(f"[POST-PROCESS] Skipping - step is '{step}' (actively collecting information)")
            return True
        
        # Skip if collect_user_info or ask_for_missing_field tool was called (actively collecting information)
        if "collect_user_info" in function_names or "ask_for_missing_field" in function_names:
            logger.info("[POST-PROCESS] Skipping - information collection tool was called (actively collecting)")
            return True
        
        # CRITICAL: Check if CURRENT assistant message is asking for user details
        # This prevents post-processing when we're actively asking for information
        if assistant_lower:
            asking_for_details_phrases = [
                'could you please provide',
                'please provide your',
                'could you please share',
                'please share your',
                'can you provide your',
                'can you share your',
                'could you provide your',
                'could you share your',
                'please provide',
                'provide your',
                'share your',
                'your full name',
                'your name',
                'your email address',
                'your email',
                'your phone number',
                'your phone',
                'email address and phone',
                'email and phone number',
                'to connect you with our team',
                'to connect with our team'
            ]
            if any(phrase in assistant_lower for phrase in asking_for_details_phrases):
                logger.info("[POST-PROCESS] Skipping - current assistant message is asking for user details")
                return True
        
        # Skip if user just said "yes" and previous message was asking to connect with team
        # This means we're transitioning to information collection mode
        if user_lower in ['yes', 'yep', 'yeah', 'sure', 'okay', 'ok']:
            conversation_history = self._get_conversation_history(limit=2)
            if conversation_history:
                # Check last assistant message
                last_assistant_msg = None
                for msg in reversed(conversation_history):
                    if msg.get('role') == 'assistant':
                        last_assistant_msg = msg.get('content', '').lower()
                        break
                
                if last_assistant_msg:
                    # Check if last message was asking to connect with team
                    team_connection_phrases = [
                        'connect with our team',
                        'connect with the team',
                        'connect you with',
                        'would you like to connect',
                        'connect with team'
                    ]
                    if any(phrase in last_assistant_msg for phrase in team_connection_phrases):
                        logger.info("[POST-PROCESS] Skipping - user said 'yes' to team connection, transitioning to collection")
                        return True
        
        # Check if assistant message in history is asking for information (email, phone, name)
        # This handles the case where LLM asks "Could you please share your email address..."
        conversation_history = self._get_conversation_history(limit=1)
        if conversation_history:
            last_assistant_msg = None
            for msg in reversed(conversation_history):
                if msg.get('role') == 'assistant':
                    last_assistant_msg = msg.get('content', '').lower()
                    break
            
            if last_assistant_msg:
                # Check if last assistant message is asking for contact info
                asking_for_info_phrases = [
                    'could you please share',
                    'please share your',
                    'please provide your',
                    'can you share your',
                    'can you provide your',
                    'email address and phone',
                    'email and phone number',
                    'your email address',
                    'your phone number'
                ]
                if any(phrase in last_assistant_msg for phrase in asking_for_info_phrases):
                    logger.info("[POST-PROCESS] Skipping - assistant is asking for contact information")
                    return True
        
        # Don't skip - proceed with post-processing (informational answers should get follow-up messages)
        logger.info(f"[POST-PROCESS] Proceeding - step='{step}', needs_info='{needs_info}' (not actively collecting)")
        return False
    
    def _analyze_and_generate_followup_message(self, assistant_message: str, user_message: str, conversation_history: list, should_ask_for_name: bool, current_name: str) -> Tuple[str, str]:
        """
        Post-processing layer: Analyze the answer and decide which ONE type of follow-up message to send.
        Types: 'follow_up', 'ask_to_connect', 'ask_name', or None
        This runs AFTER answer generation, in parallel/non-blocking.
        
        Uses last 6-7 messages for full context understanding.
        
        Returns:
            tuple: (message_type: str, message: str)
            message_type can be: 'follow_up', 'ask_to_connect', 'ask_name', or ''
        """
        try:
            # CRITICAL: Check if user has already been connected (details submitted)
            # If so, NEVER offer to connect again - just answer questions
            name = self.conversation_data.get('name', '')
            email = self.conversation_data.get('email', '')
            phone = self.conversation_data.get('phone', '')
            step = self.conversation_data.get('step', '')
            lead_submitted = self.conversation_data.get('lead_submitted', False)
            
            # User is already connected if:
            # 1. Lead has been explicitly submitted, OR
            # 2. All three details (name, email, phone) are collected and step is 'confirmation' or 'complete'
            already_connected = lead_submitted or (name and email and phone and step in ['confirmation', 'complete'])
            
            if already_connected:
                logger.info("[POST-PROCESS] User already connected (details submitted) - skipping ask_to_connect")
            
            client, model = _get_openai_client()
            if not client or not model:
                # Fallback: simple heuristic
                return self._simple_followup_check(assistant_message, user_message, should_ask_for_name, current_name, already_connected)
            
            # Extract key topics from assistant message for dynamic message generation
            assistant_lower = assistant_message.lower()
            topics_mentioned = []
            if 'novated lease' in assistant_lower:
                topics_mentioned.append('novated lease')
            if 'benefit' in assistant_lower or 'saving' in assistant_lower:
                topics_mentioned.append('benefits and savings')
            if 'cost' in assistant_lower or 'price' in assistant_lower or 'payment' in assistant_lower:
                topics_mentioned.append('pricing')
            if 'electric vehicle' in assistant_lower or 'ev' in assistant_lower:
                topics_mentioned.append('electric vehicles')
            if 'getting started' in assistant_lower or 'process' in assistant_lower:
                topics_mentioned.append('getting started')
            if 'tax' in assistant_lower or 'fbt' in assistant_lower:
                topics_mentioned.append('tax benefits')
            
            topics_str = ', '.join(topics_mentioned) if topics_mentioned else 'general information'
            
            # Format conversation history for context (last 6-7 messages)
            history_context = ""
            if conversation_history:
                # Take last 6-7 messages for context
                recent_history = conversation_history[-7:] if len(conversation_history) > 7 else conversation_history
                history_messages = []
                for msg in recent_history:
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', '')[:200]  # Limit each message to 200 chars for context
                    if role == 'user':
                        history_messages.append(f"User: {content}")
                    elif role == 'assistant':
                        history_messages.append(f"Assistant: {content}")
                history_context = "\n".join(history_messages)
            else:
                history_context = "No previous conversation history"
            
            # Build analysis prompt with full context
            analysis_prompt = f"""You are analyzing a chat conversation to decide which ONE follow-up message to send.

CURRENT USER MESSAGE: {user_message}

CURRENT ASSISTANT ANSWER: {assistant_message}

CONVERSATION HISTORY (Last 6-7 messages for context):
{history_context}

KEY TOPICS DISCUSSED: {topics_str}
TOTAL MESSAGES IN CONVERSATION: {len(conversation_history)}
SHOULD ASK FOR NAME: {should_ask_for_name}
CURRENT NAME: {current_name if current_name else "Not provided"}
USER ALREADY CONNECTED: {already_connected}

TASK:
Decide which ONE type of follow-up message to send (only ONE per response). Use the FULL conversation history to understand context and flow. Be professional but approachable - think of a friendly, modern professional tone.

CRITICAL RULE - USER ALREADY CONNECTED:
- If USER ALREADY CONNECTED is True, the user has ALREADY submitted their details and been connected to our team
- In this case, NEVER use "ask_to_connect" - they are already connected!
- Just answer their questions and use "follow_up" or "" (empty) as appropriate
- Do NOT offer team connection again - it's redundant and confusing

DECISION LOGIC (BALANCED PRIORITY):
1. "ask_to_connect" - PRIORITIZE when (ONLY if USER ALREADY CONNECTED is False):
   - User asked about benefits, pricing, costs, savings, getting started, or shows strong interest
   - User asked "how does it work" or "what are the benefits" - these are conversion opportunities
   - Conversation has depth (3+ messages) and user is engaged
   - User seems ready to take next step
   - IMPORTANT: This is our conversion goal - offer team connection when appropriate
   - Based on conversation history, user shows genuine interest

2. "ask_name" - Use when:
   - should_ask_for_name is True AND current_name is empty
   - BUT: Only if it's early in conversation (first 2-3 messages) OR team connection isn't more appropriate
   - Don't prioritize name over team connection if user shows strong interest
   - Good for personalization early in conversation

3. "follow_up" - Use when:
   - User asked informational questions that could benefit from more details
   - User seems curious but not ready for team connection yet
   - Good for keeping conversation going without being pushy
   - Conversation history shows user is exploring topics

4. "" (empty) - If:
   - None of the above apply
   - User seems satisfied or conversation is ending
   - Don't overdo it - sometimes no follow-up is best
   - Conversation history suggests user is done

BALANCING RULES:
- Our goal is conversion (team connection), but balance it naturally
- Don't always ask for name first - team connection can be more valuable
- If user shows interest (benefits, pricing, getting started), prioritize ask_to_connect
- If it's very early (first message), ask_name might be better for personalization
- If user asked informational question, follow_up keeps conversation flowing
- Use conversation history to understand user's journey and intent
- Maximum 60 tokens (very short, 1-2 sentences)
- Tone: Professional but young - friendly, modern, approachable, not overly formal
- Do NOT start with acknowledgments like "Hope that helps!", "Great question!", "Thanks for asking!", "Perfect!", "No worries at all!" - go straight to the message content
- Make messages DYNAMIC and contextual - relate to what was just discussed AND conversation history

MESSAGE FORMATS (MAX 60 TOKENS EACH - COUNT CAREFULLY!):
Make messages DYNAMIC and contextual - relate to the specific topic discussed AND conversation flow.

- ask_name: "[Natural transition] I'd love to personalise our chat—what should I call you?"
  Examples (professional but young tone):
  - "By the way, I'd love to personalise our conversation—what should I call you?"
  - "I'd love to know your name so I can make this more personal. What should I call you?"
  - "What should I call you?"
  - "Quick question—what should I call you?"
  
- ask_to_connect: "[Dynamic offer related to topic] Would you like to connect with our team to explore how [specific topic from answer] could work for you? They can provide personalised assistance!"
  Examples (professional but young, contextual to conversation):
  - If discussing novated leases: "Would you like to connect with our team to explore how a novated lease could specifically benefit you? They can provide personalised assistance!"
  - If discussing benefits: "Would you like to connect with our team to explore your savings potential? They can help you figure out what works best!"
  - If discussing pricing: "Would you like to connect with our team to get personalised pricing? They can walk you through your options!"
  - If discussing getting started: "Would you like to connect with our team to get started? They can guide you through the process!"
  - Make it relevant to the specific topic AND conversation history - don't use generic messages
  
- follow_up: "[Dynamic invitation related to topic] Let me know if you'd like to explore [specific aspect] further!" or "Feel free to ask if you'd like more details about [topic]!"
  Examples (professional but young):
  - "Let me know if you'd like to explore this further!"
  - "Feel free to ask if you'd like more details about [specific topic mentioned in answer]!"
  - "Let me know if you want to dive deeper into [topic]!"
  - "Happy to chat more about [topic] if you'd like!"

CRITICAL CONSTRAINTS:
- Maximum 60 tokens per message - COUNT TOKENS CAREFULLY!
- Do NOT include acknowledgments like "Hope that helps!", "Great question!", "Thanks for asking!", "Perfect!", "No worries at all!" - go straight to the message content
- Tone: Professional but young - friendly, modern, approachable, not overly formal or corporate
- Be concise - every word counts toward the 60 token limit
- Use conversation history to understand context and flow

CRITICAL: Make messages DYNAMIC and CONTEXTUAL:
- Reference the specific topic discussed (e.g., "novated lease", "benefits", "pricing", "electric vehicles")
- Use conversation history to understand what user has been asking about
- Make ask_to_connect messages relevant to what was just discussed AND conversation flow
- Make follow_up messages reference the specific aspect they might want to explore
- Don't use generic messages - personalize based on the answer content AND conversation history
- Use the KEY TOPICS DISCUSSED and CONVERSATION HISTORY to make messages relevant

RESPOND WITH JSON:
{{
    "message_type": "ask_name" | "ask_to_connect" | "follow_up" | "",
    "message": "Generated DYNAMIC message WITHOUT acknowledgments, referencing specific topics discussed and conversation context (EXACTLY 60 tokens or less - verify token count!)" OR null
}}

If message_type is empty string, message should be null."""

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert at analyzing conversations and generating short, contextual follow-up messages. CRITICAL: Maximum 60 tokens per message. Count tokens carefully. Do NOT include acknowledgments like 'Hope that helps!', 'Great question!', 'Thanks for asking!', 'Perfect!', 'No worries at all!' - go straight to the message content. Use conversation history (last 6-7 messages) to understand context. Tone: Professional but young - friendly, modern, approachable, not overly formal. Australian tone preferred."},
                    {"role": "user", "content": analysis_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=80  # Limit response to ensure message stays under 60 tokens
            )
            
            result_text = response.choices[0].message.content.strip()
            result_data = json.loads(result_text)
            
            message_type = result_data.get("message_type", "")
            message = result_data.get("message", "")
            
            # CRITICAL: If user is already connected, NEVER use "ask_to_connect"
            if already_connected and message_type == "ask_to_connect":
                logger.info("[FOLLOWUP] User already connected - overriding ask_to_connect to empty")
                return "", ""
            
            if message_type and message:
                # Validate token count (approximately 4 characters per token, so 60 tokens ≈ 240 characters)
                # This is a rough estimate - actual token count may vary
                estimated_tokens = len(message.split()) * 1.3  # Rough estimate: words * 1.3
                char_estimate = len(message) / 4  # Rough estimate: chars / 4
                estimated_tokens = max(estimated_tokens, char_estimate)
                
                if estimated_tokens > 65:  # Allow small buffer
                    logger.warning(f"[FOLLOWUP] Message may exceed 60 tokens (estimated {estimated_tokens:.1f} tokens), truncating...")
                    # Truncate to approximately 60 tokens (240 characters)
                    words = message.split()
                    truncated = []
                    char_count = 0
                    for word in words:
                        if char_count + len(word) + 1 <= 240:  # +1 for space
                            truncated.append(word)
                            char_count += len(word) + 1
                        else:
                            break
                    message = " ".join(truncated)
                    if not message.endswith(('.', '!', '?')):
                        message += "!"
                    logger.info(f"[FOLLOWUP] Truncated message to ~60 tokens: {message[:50]}...")
                
                logger.info(f"[FOLLOWUP] LLM decided to send {message_type} (estimated {estimated_tokens:.1f} tokens): {message[:50]}...")
                return message_type, message
            else:
                logger.info("[FOLLOWUP] LLM decided NOT to send any follow-up message")
                return "", ""
                
        except Exception as e:
            logger.error(f"[FOLLOWUP] Error analyzing for follow-up message: {str(e)}", exc_info=True)
            # Fallback to simple heuristic
            return self._simple_followup_check(assistant_message, user_message, should_ask_for_name, current_name, already_connected)
    
    def _remove_followup_phrases(self, text: str) -> str:
        """
        Removes follow-up phrases and invitations from the answer text.
        These phrases should be handled separately after answer generation.
        """
        import re
        
        # Patterns to detect and remove follow-up phrases (case-insensitive)
        followup_patterns = [
            # "If you'd like more details..." patterns
            r'if you\'d like more details.*',
            r'if you\'d like to know more.*',
            r'if you\'d like to explore.*',
            r'if you\'d like.*feel free to ask.*',
            r'feel free to ask.*',
            r'feel free.*',
            
            # "Let me know if..." patterns (including "further guidance")
            r'let me know if you\'d like.*',
            r'let me know if.*',
            r'let me know.*further guidance.*',
            r'let me know.*further.*',
            r'let me know.*guidance.*',
            r'let me know.*',
            
            # "Would you like..." patterns (but not questions from the answer itself)
            r'would you like to connect.*',
            r'would you like to explore.*',
            r'would you like.*more details.*',
            r'would you like.*further.*',
            
            # "If you have any questions..." patterns
            r'if you have any questions.*',
            r'if you need.*more information.*',
            r'if you\'re interested.*',
            
            # "Further guidance" patterns (more specific)
            r'let me know if you\'d like further guidance.*',
            r'let me know.*further guidance.*',
            r'further guidance.*',
            r'like further guidance.*',
            r'if you\'d like further guidance.*',
            r'if you\'d like.*guidance.*',
            
            # Other invitation patterns
            r'feel free to reach out.*',
            r'don\'t hesitate to ask.*',
            r'please let me know.*',
            r'i\'d be happy to.*',
            r'if you need.*help.*',
            r'if you need.*assistance.*',
            
            # Patterns with newlines before them
            r'\n\nif you.*',
            r'\nif you.*',
            r'\n\nfeel free.*',
            r'\nfeel free.*',
            r'\n\nlet me know.*',
            r'\nlet me know.*',
            r'\n\nwould you like.*',
            r'\nwould you like.*',
            r'\n\nfurther guidance.*',
            r'\nfurther guidance.*',
        ]
        
        cleaned_text = text
        for pattern in followup_patterns:
            # Remove from end of message (after last sentence) - handle punctuation
            cleaned_text = re.sub(pattern + r'[\.!?]?\s*$', '', cleaned_text, flags=re.IGNORECASE | re.DOTALL | re.MULTILINE)
            # Remove if it appears as a standalone sentence (preceded by period or newline)
            cleaned_text = re.sub(r'[\.!?]\s*' + pattern + r'[\.!?]?\s*', '. ', cleaned_text, flags=re.IGNORECASE | re.DOTALL)
            # Remove from anywhere in the message
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE | re.DOTALL)
            # Also remove if it starts with newlines
            cleaned_text = re.sub(r'\n\n+' + pattern.lstrip('\\n'), '', cleaned_text, flags=re.IGNORECASE | re.DOTALL)
        
        # Clean up any trailing newlines, spaces, or punctuation artifacts
        cleaned_text = cleaned_text.rstrip()
        # Remove trailing punctuation that might be left (like "!" or "?" after removing phrases)
        cleaned_text = re.sub(r'[!?]+\s*$', '', cleaned_text)
        # Ensure it ends with proper punctuation if it's a complete sentence
        if cleaned_text and not cleaned_text.endswith(('.', '!', '?')):
            # Check if it's a complete sentence (has capital letter and ends properly)
            if cleaned_text[-1].isalnum():
                cleaned_text += '.'
        
        if cleaned_text != text:
            logger.info(f"[CLEANUP] Removed follow-up phrases from answer. Original length: {len(text)}, Cleaned length: {len(cleaned_text)}")
        
        return cleaned_text
    
    def _simple_followup_check(self, assistant_message: str, user_message: str, should_ask_for_name: bool, current_name: str, already_connected: bool = False) -> Tuple[str, str]:
        """Simple heuristic fallback for follow-up message decision. Balanced priority."""
        import random
        
        # Extract topic/keywords from assistant message for dynamic messages
        assistant_lower = assistant_message.lower()
        user_lower = user_message.lower()
        
        # Detect topic from assistant message
        topic = None
        if 'novated lease' in assistant_lower:
            topic = 'novated lease'
        elif 'benefit' in assistant_lower or 'saving' in assistant_lower:
            topic = 'benefits and savings'
        elif 'cost' in assistant_lower or 'price' in assistant_lower or 'payment' in assistant_lower:
            topic = 'pricing'
        elif 'electric vehicle' in assistant_lower or 'ev' in assistant_lower:
            topic = 'electric vehicles'
        elif 'getting started' in assistant_lower or 'process' in assistant_lower:
            topic = 'getting started'
        
        # BALANCED DECISION LOGIC:
        # 1. Check team connection first (conversion goal) if user shows interest
        #    BUT ONLY if user is NOT already connected
        strong_interest_keywords = ['benefit', 'cost', 'price', 'saving', 'how does', 'how can', 'get started', 'interested', 'explore', 'learn more']
        conversion_keywords = ['benefit', 'cost', 'price', 'saving', 'get started', 'interested']
        
        # If user asked about conversion topics, prioritize team connection (ONLY if not already connected)
        if not already_connected and any(keyword in user_lower for keyword in conversion_keywords) and len(assistant_message) > 100:
            if topic:
                team_messages = [
                    f"Would you like to connect with our team to explore how {topic} could work for you? They can provide personalised assistance!",
                    f"Would you like to connect with our team to explore your {topic} options? They can help!",
                    f"Would you like to connect with our team to get personalised assistance with {topic}?"
                ]
            else:
                team_messages = [
                    "Would you like to connect with our team to explore how this could work for you? They can provide personalised assistance!",
                    "Would you like to connect with our team for personalised assistance?",
                    "Would you like to connect with our team to explore your options?"
                ]
            return "ask_to_connect", random.choice(team_messages)
        
        # 2. Check name request (but only if early in conversation or team connection not appropriate)
        if should_ask_for_name and not current_name:
            # Only ask for name if it's early OR if team connection isn't more appropriate
            if any(keyword in user_lower for keyword in strong_interest_keywords):
                # User shows interest - prioritize team connection over name
                pass  # Skip name request, will check follow_up or return empty
            else:
                name_messages = [
                    "By the way, I'd love to personalise our conversation—what should I call you?",
                    "I'd love to know your name so I can make this more personal. What should I call you?",
                    "What should I call you?"
                ]
                return "ask_name", random.choice(name_messages)
        
        # 3. Check team connection for general interest (if not already checked)
        #    BUT ONLY if user is NOT already connected
        if not already_connected and any(keyword in user_lower for keyword in strong_interest_keywords) and len(assistant_message) > 100:
            if topic:
                team_messages = [
                    f"Would you like to connect with our team to explore how {topic} could work for you? They can provide personalised assistance!",
                    f"Would you like to connect with our team to explore your {topic} options? They can help!",
                ]
            else:
                team_messages = [
                    "Would you like to connect with our team to explore how this could work for you? They can provide personalised assistance!",
                    "Would you like to connect with our team for personalised assistance?",
                ]
            return "ask_to_connect", random.choice(team_messages)
        
        # 4. Check follow up (for informational questions)
        if len(assistant_message) > 50:
            if topic:
                follow_messages = [
                    f"Let me know if you'd like to explore {topic} further!",
                    f"Feel free to ask if you'd like more details about {topic}!",
                    f"Happy to chat more about {topic} if you'd like!"
                ]
            else:
                follow_messages = [
                    "Let me know if you'd like to explore this further!",
                    "Feel free to ask if you'd like more details!",
                    "Happy to chat more if you'd like!"
                ]
            return "follow_up", random.choice(follow_messages)
        
        return "", ""
    
    def _save_conversation_data(self):
        """Save conversation data to session."""
        self.session.conversation_data = self.conversation_data
        self.session.save(update_fields=['conversation_data'])

