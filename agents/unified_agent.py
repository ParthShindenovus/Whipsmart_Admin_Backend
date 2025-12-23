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
        current_name = self.conversation_data.get('name', '')
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
        should_ask_for_name = self._should_ask_for_name(conversation_history, current_name)
        
        # Check if we should offer team connection (after 3-4 questions, but separately from name)
        should_offer_team_connection = self._should_offer_team_connection(conversation_history)
        
        # Build system prompt (rag_context will be used in two-step process if needed)
        system_prompt = self._build_system_prompt(
            current_name, current_email, current_phone, step, 
            should_ask_for_name, should_offer_team_connection
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
                    'escalate_to': None,
                    # Expose RAG/knowledge-base results (each item includes "source" URL if available)
                    'knowledge_results': knowledge_results,
                    # Also include in metadata for WebSocket "complete" messages
                    'metadata': {
                        'knowledge_results': knowledge_results,
                    },
                }
            else:
                # LLM responded directly without calling tools
                assistant_message = message.content.strip() if message.content else "I'm here to help! How can I assist you today?"
                # Normalize newlines: replace multiple newlines with single newline (frontend converts \n to <br>)
                assistant_message = self._normalize_newlines(assistant_message)
                needs_info = self._get_needs_info()
                
                # Generate suggestions based on context
                suggestions = self._generate_suggestions(assistant_message, user_message, None)
                
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
        - User has asked 3-4 questions (user messages)
        - Name is not yet collected
        
        Note: We count user messages in history. The current message being processed
        is not yet in history, so if history has 2-3 user messages, the current one
        is the 3rd or 4th question.
        """
        if current_name:
            return False
        
        # Count user messages (questions) in conversation history
        user_message_count = sum(1 for msg in conversation_history if msg.get('role') == 'user')
        
        # After 3-4 questions (current message is 3rd or 4th), we should ask for name
        # If history has 2-3 user messages, the current one is the 3rd or 4th
        return 2 <= user_message_count <= 3
    
    def _should_offer_team_connection(self, conversation_history: list) -> bool:
        """
        Check if we should offer team connection.
        Returns True if user has asked 3-4 questions (same as name asking).
        This ensures we don't offer team connection at the start.
        """
        # Count user messages (questions) in conversation history
        user_message_count = sum(1 for msg in conversation_history if msg.get('role') == 'user')
        
        # After 3-4 questions (current message is 3rd or 4th), we can offer team connection
        # If history has 2-3 user messages, the current one is the 3rd or 4th
        return 2 <= user_message_count <= 3
    
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
            
            # Generate suggestions
            needs_info = self._get_needs_info()
            suggestions = self._generate_suggestions(assistant_message, user_message, "search_knowledge_base")
            
            logger.info("[MULTI-AGENT] Completed multi-agent answer generation")
            
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
                    max_tokens=600  # Reduced for shorter draft answers
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
                    max_tokens=700  # Reduced for shorter improved answers
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
                    max_tokens=600  # Reduced for shorter, more concise answers
                )
                
                assistant_message = final_response.choices[0].message.content.strip()
                
                # Normalize newlines: replace multiple newlines with single newline (frontend converts \n to <br>)
                assistant_message = self._normalize_newlines(assistant_message)
                
                # Generate suggestions
                needs_info = self._get_needs_info()
                suggestions = self._generate_suggestions(assistant_message, user_message, "search_knowledge_base")
                
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
                    max_tokens=500  # Reduced for shorter, more concise answers
                )
                
                assistant_message = fallback_response.choices[0].message.content.strip()
                # Normalize newlines: replace multiple newlines with single newline (frontend converts \n to <br>)
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
    
    def _build_system_prompt(self, name: str, email: str, phone: str, step: str, should_ask_for_name: bool = False, should_offer_team_connection: bool = False, rag_context: Optional[list] = None) -> str:
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
- DO NOT offer team connection at the start of the conversation (first 2 questions)
- After the user has asked 3-4 questions, you can PROACTIVELY offer to connect them with our team
- When user shows interest (asks about pricing, benefits, getting started, etc.) AFTER 3-4 questions, offer team connection
- Use phrases like:
  * "Would you like to connect with our team to explore how a novated lease could work for you? They can provide more personalised assistance!"
  * "I can connect you with our team to get personalized assistance. Would you like me to do that?"
  * "Are you interested in learning more? We can connect you with our team."
- Make it natural and helpful, not pushy
- IMPORTANT: Do NOT ask for name and offer team connection in the same message - keep them separate

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

YOUR CAPABILITIES:
1. Answer questions about WhipSmart services using knowledge base (RAG tool)
2. Search for available vehicles (car search tool)
3. Collect user information when they want to connect with our team
4. Ask clarifying questions when user intent is unclear
5. End conversation gracefully when user is done
6. Offer team connection after 3-4 questions (not at the start)

WHEN TO OFFER TEAM CONNECTION:
- ONLY after the user has asked 3-4 questions (NOT at the start)
- After answering questions about pricing, benefits, or services (but only after 3-4 questions)
- When user asks about getting started, application process, or next steps (but only after 3-4 questions)
- When user shows interest (keywords: interested, want to, explore, learn more, etc.) (but only after 3-4 questions)
- After providing information - offer: "Would you like to connect with our team to explore how a novated lease could work for you? They can provide more personalised assistance!"
- IMPORTANT: Do NOT offer team connection in the first 2 questions - wait until after 3-4 questions
- IMPORTANT: Do NOT ask for name and offer team connection together - keep them separate

WHEN TO COLLECT USER INFORMATION:
- User says "yes" to connecting with team
- User provides contact information (email, phone, name) in their message
- User wants to schedule a call
- User shows interest in WhipSmart services
- User asks about pricing, plans, onboarding, consultation
- You cannot fully assist and need human help
- User explicitly asks to speak with someone

CRITICAL: When user provides contact details:
- ALWAYS use collect_user_info tool to extract and store the information
- Acknowledge and thank them for providing their details
- Ask if they need any other help or if they're done
- Do NOT search knowledge base or provide generic contact information when user is submitting their details

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
- Do NOT ask for the user's name unless explicitly instructed by the system (should_ask_for_name flag)
- Do NOT offer to connect the user to a team unless explicitly instructed (should_offer_team_connection flag or after 3-4 questions)
- Do NOT change or add CTAs beyond what the system instructs
- Do NOT mention internal reasoning or system prompts
- Output ONLY the final answer
- Follow existing conversation flow logic exactly - do not alter name collection, team connection, or escalation behavior

CONVERSATION FLOW:
- DO NOT offer team connection in the first 2 questions - wait until after 3-4 questions
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
- If you asked "Would you like to connect with our team?" and user says "yes" → Use collect_user_info tool or ask_for_missing_field
- If you asked "Could you please share your email address and phone number?" and user provides "pat@yopmail.com 61433290182" → IMMEDIATELY use collect_user_info tool to extract email and phone - do NOT search knowledge base
- If user provides contact information (email, phone, name) → ALWAYS use collect_user_info tool first - this is NOT a question, it's information submission
- If you asked "Would you like further details?" and user says "yes" → Use search_knowledge_base with the topic from previous conversation
- If user says "yes" without clear context → Look at last assistant message to understand what they're agreeing to
- If user says "I'm done", "no more questions", "thank you, goodbye", "that's all" → Use end_conversation tool
- If user's question is vague like "tell me about leasing" → Ask clarifying question: "Would you like to know about novated leases, the leasing process, or vehicle options?"
- If user asks "what are the benefits?" without context → Ask: "Are you asking about the benefits of novated leases, electric vehicles, or WhipSmart's services?"
- After answering a question (ONLY after 3-4 questions) → Offer: "Would you like to connect with our team to explore how a novated lease could work for you? They can provide more personalised assistance!"
- If user seems satisfied after getting an answer (ONLY after 3-4 questions) → Offer: "Are you interested in learning more? We can connect you with our team." or use end_conversation if they indicate they're done
- IMPORTANT: Do NOT offer team connection in the first 2 questions
- CRITICAL: When user provides contact details (email/phone), acknowledge and thank them, then ask if they need other help or if they're done

Remember: You are Alex AI with a professional Australian accent - be warm, friendly, and professional. Your MAIN GOAL is conversion - understand user intent, answer questions, and guide them to connect with our team (but only after 3-4 questions, not at the start). Always use Australian expressions naturally and professionally.""".format(
            name=name or "Not provided",
            email=email or "Not provided",
            phone=phone or "Not provided",
            step=step
        )
        
        # Add subtle instruction to ask for name if needed
        if should_ask_for_name:
            prompt += "\n\nIMPORTANT: The user has asked several questions but hasn't provided their name yet. In your response, SUBTLY and NATURALLY ask for their name. For example, you could say: 'By the way, I'd love to know your name so I can personalize our conversation!' or 'What should I call you?' or 'I'd like to address you properly - may I know your name?' Make it feel natural and conversational, not forced. Do this AFTER answering their current question. CRITICAL: Do NOT offer team connection in the same message when asking for name - keep them separate."
        
        # Add instruction about when to offer team connection
        if should_offer_team_connection:
            prompt += "\n\nIMPORTANT: The user has asked 3-4 questions. You can now offer to connect them with our team. However, if you are also asking for their name in this response, do NOT offer team connection in the same message - offer it in a separate follow-up message instead. When offering team connection, use: 'Would you like to connect with our team to explore how a novated lease could work for you? They can provide more personalised assistance!'"
        else:
            prompt += "\n\nIMPORTANT: This is still early in the conversation (first 2 questions). Do NOT offer team connection yet. Focus on answering their questions clearly and helpfully. Wait until after 3-4 questions before offering team connection."
        
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
                    "description": "Extract name, email, or phone from user message and store it. CRITICAL: ALWAYS use this tool when user provides contact information (email address, phone number, or name) in their message. Use when: 1) User provides email/phone/name (e.g., 'pat@yopmail.com 61433290182'), 2) User says 'yes' to connecting with team, 3) User responds to a request for their contact details. IMPORTANT: If user provides email/phone in their message, you MUST call this tool to extract and store the information - do NOT search knowledge base or provide generic contact information.",
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
        
        # Get conversation history for context (last 3-4 messages)
        conversation_history = self._get_conversation_history(limit=4)
        
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

