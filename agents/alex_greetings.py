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
    Generate an Alex AI greeting based on current time in Melbourne timezone.
    Returns a greeting message with professional Australian accent.
    Only time-based greetings (no day greetings).
    """
    melbourne_time = _get_melbourne_time()
    current_hour = melbourne_time.hour
    
    # Get time-based greeting only
    time_greeting = _get_time_greeting(current_hour)
    
    if time_greeting:
        return time_greeting
    else:
        # Fallback greeting
        return "Hello!"


def _get_time_greeting(hour: int) -> str:
    """
    Get time-based greeting based on hour in Melbourne timezone.
    Returns greeting string.
    Professional Australian greetings - time only, no day references.
    """
    # Early Morning (before 9 AM)
    if hour < 9:
        return "Good morning!"
    
    # Morning (9 AM – 11:59 AM)
    elif hour < 12:
        return "Good morning!"
    
    # Afternoon (12 PM – 4:59 PM)
    elif hour < 17:
        return "Good afternoon!"
    
    # Late Afternoon / Early Evening (5 PM – 7:59 PM)
    elif hour < 20:
        return "Good evening!"
    
    # Evening (after 8 PM)
    else:
        return "Good evening!"


def _get_day_greeting(day: str, hour: int) -> str:
    """
    Day greetings are no longer used - this function is kept for compatibility.
    Returns empty string.
    """
    return ""


def _get_casual_greeting() -> str:
    """
    Get a casual friendly opener.
    Simple greeting without questions.
    """
    return "Hello!"


def get_full_alex_greeting() -> str:
    """
    Get a full Alex AI greeting with introduction.
    Uses only time-based greeting (no day greetings).
    Properly formatted for UI display with markdown formatting (bold, line breaks).
    Uses Melbourne timezone for accurate time-based greetings.
    Professional Australian support agent greeting.
    """
    melbourne_time = _get_melbourne_time()
    current_hour = melbourne_time.hour
    
    # Get time-based greeting only (e.g., "Good afternoon!")
    time_greeting = _get_time_greeting(current_hour)
    
    # Build structured message with proper formatting and line breaks
    message_lines = []
    
    # Start with time greeting (bold)
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

