"""
Configuration and constants for the LangGraph agent.
"""
from typing import Dict, List
from enum import Enum

# Conversation steps
class ConversationStep(str, Enum):
    CHATTING = "chatting"
    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"
    CONFIRMATION = "confirmation"
    COMPLETE = "complete"

# Question types
class QuestionType(str, Enum):
    DOMAIN = "domain"  # Needs RAG
    USER_ACTION = "user_action"  # No RAG needed
    UNCLEAR = "unclear"

# Domain keywords that require RAG
DOMAIN_KEYWORDS = [
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

# User action keywords that bypass RAG
USER_ACTION_KEYWORDS = [
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

# Connection intent patterns
CONNECTION_INTENT_PATTERNS = [
    r'\b(?:i\s+)?(?:would|want|need|like|wish)\s+(?:to\s+)?(?:connect|speak|talk|contact|reach)',
    r'\b(?:can|could|may)\s+(?:i|we)\s+(?:connect|speak|talk|contact|reach)',
    r'\b(?:let|help)\s+(?:me\s+)?(?:connect|speak|talk|contact|reach)',
    r'\b(?:i\s+)?(?:am|would\s+be)\s+(?:interested\s+in\s+)?(?:connecting|speaking|talking|contacting)',
    r'\b(?:arrange|set\s+up|book|schedule)\s+(?:a\s+)?(?:call|meeting|conversation)'
]

# Decline patterns
DECLINE_PATTERNS = [
    r'^no\s+thanks',
    r'^no\s+thank\s+you',
    r'^not\s+interested',
    r"^don'?t\s+want",
    r"^don'?t\s+need",
    r'^not\s+right\s+now',
    r'^maybe\s+later'
]

# Team connection phrases
TEAM_CONNECTION_PHRASES = [
    'connect with our team',
    'connect with the team',
    'connect you with',
    'would you like to connect',
    'connect with team',
    'connect with our sales team'
]

# Info request keywords
INFO_REQUEST_KEYWORDS = ['email', 'phone', 'contact', 'details', 'information', 'share']

# LLM parameters
LLM_TEMPERATURE_CLASSIFICATION = 0.3
LLM_TEMPERATURE_RESPONSE = 0.7
LLM_MAX_TOKENS_RESPONSE = 512
LLM_MAX_TOKENS_FINAL = 256

# RAG parameters
RAG_TOP_K = 4
RAG_CONTEXT_LIMIT = 500

# Conversation history limits
CONVERSATION_HISTORY_LIMIT = 4
EXTENDED_HISTORY_LIMIT = 7

# Name collection thresholds
NAME_COLLECTION_THRESHOLD = 2  # Ask after 2-3 questions
TEAM_CONNECTION_THRESHOLD = 3  # Offer after 3-4 questions
