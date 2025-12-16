"""
Alex AI - Smart Greeting Rules
Generates time and day-based greetings with Australian accent.
Uses Melbourne timezone (Australia/Melbourne) for accurate time-based greetings.
"""
import random
from django.utils import timezone  # type: ignore
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback for Python < 3.9 (though Django 5.1+ requires Python 3.10+)
    from backports.zoneinfo import ZoneInfo  # type: ignore


def _get_melbourne_time():
    """
    Get current time in Melbourne timezone (Australia/Melbourne).
    Handles both AEST (Australian Eastern Standard Time) and AEDT (Australian Eastern Daylight Time).
    """
    now_utc = timezone.now()
    melbourne_tz = ZoneInfo('Australia/Melbourne')
    melbourne_time = now_utc.astimezone(melbourne_tz)
    return melbourne_time


def get_alex_greeting() -> str:
    """
    Generate an Alex AI greeting based on current time and day in Melbourne timezone.
    Returns a greeting message with Australian accent, properly structured.
    Time greeting comes first, then day greeting.
    """
    melbourne_time = _get_melbourne_time()
    current_hour = melbourne_time.hour
    current_day = melbourne_time.strftime('%A')
    
    # Get time-based greeting first
    time_greeting = _get_time_greeting(current_hour)
    
    # Get day-based greeting (time-aware)
    day_greeting = _get_day_greeting(current_day, current_hour)
    
    # Build structured greeting - time greeting first, then day greeting
    greeting_parts = []
    
    if time_greeting:
        greeting_parts.append(time_greeting)
    
    if day_greeting:
        greeting_parts.append(day_greeting)
    
    if greeting_parts:
        # Join with proper spacing
        return " ".join(greeting_parts)
    else:
        # Fallback casual greeting
        return _get_casual_greeting()


def _get_time_greeting(hour: int) -> str:
    """
    Get time-based greeting based on hour in Melbourne timezone.
    Returns greeting string or None.
    Professional Australian greetings.
    """
    # Early Morning (before 9 AM)
    if hour < 9:
        greetings = [
            "Good morning!",
            "G'day! Good morning!"
        ]
        return random.choice(greetings)
    
    # Morning (9 AM – 11:59 AM)
    elif hour < 12:
        greetings = [
            "Good morning!",
            "G'day! Good morning!"
        ]
        return random.choice(greetings)
    
    # Afternoon (12 PM – 4:59 PM)
    elif hour < 17:
        greetings = [
            "Good afternoon!",
            "G'day! Good afternoon!"
        ]
        return random.choice(greetings)
    
    # Late Afternoon / Early Evening (5 PM – 7:59 PM)
    elif hour < 20:
        greetings = [
            "Good evening!",
            "G'day! Good evening!"
        ]
        return random.choice(greetings)
    
    # Evening (after 8 PM)
    else:
        greetings = [
            "Good evening!",
            "G'day! Good evening!"
        ]
        return random.choice(greetings)


def _get_day_greeting(day: str, hour: int) -> str:
    """
    Get day-based greeting that's time-aware.
    Returns greeting string.
    Professional Australian support agent greetings.
    
    - Morning (before 12 PM): Uses "Happy [Day]!" or similar
    - After morning (12 PM onwards): Uses "Hope your [Day] is going well" or similar
    """
    # Morning greetings (before 12 PM)
    if hour < 12:
        day_greetings = {
            'Monday': [
                "Happy Monday!",
                "Hope you're having a great start to your week!",
                "Hope your week is off to a fantastic start!"
            ],
            'Tuesday': [
                "Happy Tuesday!",
                "Hope you're having a terrific Tuesday!",
                "Hope your Tuesday is shaping up nicely!"
            ],
            'Wednesday': [
                "Happy Hump Day!",
                "Hope you're having a wonderful Wednesday!",
                "Hope your week is going well!"
            ],
            'Thursday': [
                "Happy Thursday!",
                "Hope you're having a fantastic Thursday!",
                "Hope your Thursday is treating you well!"
            ],
            'Friday': [
                "Happy Friday!",
                "Hope you're having a ripper Friday!",
                "Hope your Friday is off to a great start!"
            ],
            'Saturday': [
                "Happy Saturday!",
                "Hope you're having a wonderful Saturday!",
                "Hope your weekend is off to a great start!"
            ],
            'Sunday': [
                "Happy Sunday!",
                "Hope you're having a lovely Sunday!",
                "Hope your weekend is going well!"
            ]
        }
    else:
        # After morning (12 PM onwards) - more contextual greetings
        day_greetings = {
            'Monday': [
                "Hope your Monday is going well so far!",
                "Hope you're having a productive Monday!",
                "Hope your week is off to a great start!"
            ],
            'Tuesday': [
                "Hope your Tuesday is going well so far!",
                "Hope you're having a terrific Tuesday!",
                "Hope your Tuesday is treating you well!"
            ],
            'Wednesday': [
                "Hope your Wednesday is going well so far!",
                "Hope you're having a wonderful Wednesday!",
                "Hope your week is going well!"
            ],
            'Thursday': [
                "Hope your Thursday is going well so far!",
                "Hope you're having a fantastic Thursday!",
                "Hope your Thursday is treating you well!"
            ],
            'Friday': [
                "Hope your Friday is going well so far!",
                "Hope you're having a ripper Friday!",
                "Hope you're wrapping up a great week!"
            ],
            'Saturday': [
                "Hope your Saturday is going well so far!",
                "Hope you're having a wonderful Saturday!",
                "Hope your weekend is going well!"
            ],
            'Sunday': [
                "Hope your Sunday is going well so far!",
                "Hope you're having a lovely Sunday!",
                "Hope your weekend is treating you well!"
            ]
        }
    
    greetings = day_greetings.get(day)
    if greetings:
        return random.choice(greetings)
    # Fallback - should never happen, but just in case
    if hour < 12:
        return "Hope you're having a great day!"
    else:
        return "Hope your day is going well so far!"


def _get_casual_greeting() -> str:
    """
    Get a casual friendly opener.
    Simple greeting without questions.
    """
    casual_greetings = [
        "G'day!",
        "G'day!"
    ]
    return random.choice(casual_greetings)


def get_full_alex_greeting() -> str:
    """
    Get a full Alex AI greeting with introduction.
    Combines time/day greeting with introduction message.
    Properly formatted for UI display with markdown formatting (bold, line breaks).
    Uses Melbourne timezone for accurate time-based greetings.
    Professional Australian support agent greeting.
    """
    melbourne_time = _get_melbourne_time()
    current_hour = melbourne_time.hour
    current_day = melbourne_time.strftime('%A')
    
    # Get time-based greeting first (e.g., "Good afternoon!")
    time_greeting = _get_time_greeting(current_hour)
    
    # Get day-based greeting (time-aware, e.g., "Hope your Tuesday is going well so far!")
    day_greeting = _get_day_greeting(current_day, current_hour)
    
    # Build structured message with proper formatting and line breaks
    message_lines = []
    
    # Start with time greeting first (bold)
    if time_greeting:
        message_lines.append(f"**{time_greeting}**")
    else:
        # Fallback if no time greeting
        if current_hour < 12:
            message_lines.append("**Good morning!**")
        elif current_hour < 17:
            message_lines.append("**Good afternoon!**")
        else:
            message_lines.append("**Good evening!**")
    
    # Add day greeting second (bold)
    if day_greeting:
        message_lines.append(f"**{day_greeting}**")
    
    # Add multiple blank lines for better visual separation
    message_lines.append("")
    message_lines.append("")
    
    # Add introduction with bold for name and company
    intro = "I'm **Alex AI**, your friendly assistant here at **WhipSmart**."
    message_lines.append(intro)
    
    intro2 = "I'm here to help you with everything related to electric vehicle leasing and novated leases."
    message_lines.append(intro2)
    
    # Add multiple blank lines for better visual separation
    message_lines.append("")
    message_lines.append("")
    
    # Add call to action with emphasis
    cta = "**What can I help you with today?**"
    message_lines.append(cta)
    
    # Join with line breaks for proper formatting
    return "\n".join(message_lines)

