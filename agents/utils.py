"""
Utility functions for agent operations.
"""
import re
from agents.alex_greetings import get_full_alex_greeting


def is_greeting(message: str) -> bool:
    """
    Check if a message is a greeting or common conversational statement.
    
    Args:
        message: User's message text
        
    Returns:
        True if message is a greeting/common statement, False otherwise
    """
    if not message:
        return False
    
    # Normalize message
    message_lower = message.lower().strip()
    
    # Remove punctuation for matching
    message_clean = re.sub(r'[^\w\s]', '', message_lower)
    
    # Greeting patterns
    greeting_patterns = [
        r'^(hi|hello|hey|greetings|good morning|good afternoon|good evening|good day|hi there|hello there)',
        r'^(thanks|thank you|thx|ty|appreciate it)',
        r'^(bye|goodbye|see you|farewell|have a good day|take care)',
        r'^(ok|okay|alright|sure|got it|understood)',
        r'^(yes|yeah|yep|yup|no|nope|nah)',
        r'^(how are you|how\'?s it going|what\'?s up|sup|how do you do)',
        r'^(nice|great|awesome|cool|good|perfect|excellent)',
    ]
    
    # Check if message matches greeting patterns
    for pattern in greeting_patterns:
        if re.match(pattern, message_clean):
            return True
    
    # Check for very short messages that are likely greetings
    if len(message_clean.split()) <= 2 and message_clean in ['hi', 'hey', 'hello', 'thanks', 'thank you', 'bye', 'ok', 'okay', 'yes', 'no']:
        return True
    
    return False


def get_greeting_response(message: str) -> str:
    """
    Generate an appropriate response for greetings and common statements with professional Australian accent.
    
    Args:
        message: User's message text
        
    Returns:
        Appropriate response string with professional Australian accent
    """
    message_lower = message.lower().strip()
    message_clean = re.sub(r'[^\w\s]', '', message_lower)
    
    # Greeting responses with professional Australian accent
    if re.match(r'^(hi|hello|hey|greetings|good morning|good afternoon|good evening|good day|hi there|hello there)', message_clean):
        return """Hello! 👋 I'm Whip-E AI, your friendly assistant here at WhipSmart. I'm here to help you with everything related to electric vehicle leasing and novated leases.

I can help you with:
• Understanding novated leases and how they work
• Electric vehicle (EV) leasing options and processes
• Tax benefits and FBT exemptions
• Vehicle selection and availability
• Leasing terms, payments, and running costs
• End-of-lease options and residual payments
• WhipSmart's services and platform features

What would you like to know about EV leasing or novated leases?"""
    
    # Thank you responses with professional Australian accent
    elif re.match(r'^(thanks|thank you|thx|ty|appreciate it)', message_clean):
        return """No worries! 😊 Happy to help. If you've got any other questions about WhipSmart's EV leasing services or novated leases, feel free to ask!"""
    
    # Goodbye responses with professional Australian accent
    elif re.match(r'^(bye|goodbye|see you|farewell|have a good day|take care)', message_clean):
        return """Cheers! 👋 Feel free to come back anytime if you've got questions about WhipSmart's electric vehicle leasing services or novated leases. Have a great day!"""
    
    # Acknowledgment responses with professional Australian accent
    elif re.match(r'^(ok|okay|alright|sure|got it|understood)', message_clean):
        return """Too easy! Is there anything else you'd like to know about WhipSmart's EV leasing services or novated leases?"""
    
    # Default greeting response with professional Australian accent
    else:
        return """Hello! 👋 I'm Whip-E AI, your friendly assistant here at WhipSmart. I'm here to help you with everything related to electric vehicle leasing and novated leases.

I can help you with:
• Understanding novated leases and how they work
• Electric vehicle (EV) leasing options and processes
• Tax benefits and FBT exemptions
• Vehicle selection and availability
• Leasing terms, payments, and running costs
• End-of-lease options and residual payments
• WhipSmart's services and platform features

What would you like to know about EV leasing or novated leases?"""

