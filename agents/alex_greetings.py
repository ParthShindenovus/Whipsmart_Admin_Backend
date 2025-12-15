"""
Alex AI - Smart Greeting Rules
Generates time and day-based greetings with Australian accent.
"""
import random
from datetime import datetime
from django.utils import timezone


def get_alex_greeting() -> str:
    """
    Generate an Alex AI greeting based on current time and day.
    Returns a greeting message with Australian accent, properly structured.
    """
    now = timezone.now()
    current_hour = now.hour
    current_day = now.strftime('%A')
    
    # Get time-based greeting
    time_greeting = _get_time_greeting(current_hour)
    
    # Get day-based greeting
    day_greeting = _get_day_greeting(current_day)
    
    # Build structured greeting - prioritize day greeting, then time greeting
    greeting_parts = []
    
    if day_greeting:
        greeting_parts.append(day_greeting)
    
    if time_greeting:
        # Only add time greeting if it doesn't conflict with day greeting
        # For example, if day greeting already has "G'day", don't add another "G'day"
        if not (day_greeting and "G'day" in day_greeting and "G'day" in time_greeting):
            greeting_parts.append(time_greeting)
    
    if greeting_parts:
        # Join with proper spacing
        return " ".join(greeting_parts)
    else:
        # Fallback casual greeting
        return _get_casual_greeting()


def _get_time_greeting(hour: int) -> str:
    """
    Get time-based greeting based on hour.
    Returns greeting string or None.
    Simple greetings without questions.
    """
    # Morning (before 12 PM)
    if hour < 12:
        greetings = [
            "Hope your day's off to a great start! ☀️",
            "Good morning!"
        ]
        return random.choice(greetings)
    
    # Afternoon (12 PM – 4:59 PM)
    elif hour < 17:
        greetings = [
            "Good afternoon!",
            "Hope you're having a good arvo!"
        ]
        return random.choice(greetings)
    
    # Late Afternoon / 5 PM (Beer O'Clock 🍺)
    elif hour == 17:
        greetings = [
            "It's 5 o'clock — beer o'clock! 🍻",
            "Looks like beer o'clock! 🍺"
        ]
        return random.choice(greetings)
    
    # Evening (after 5 PM)
    else:
        greetings = [
            "Good evening!",
            "Hope you've had a solid day."
        ]
        return random.choice(greetings)


def _get_day_greeting(day: str) -> str:
    """
    Get day-based greeting.
    Returns greeting string or None.
    """
    day_greetings = {
        'Monday': [
            "G'day! Happy Monday!",
            "G'day! Happy Monday!"
        ],
        'Tuesday': [
            "G'day! Happy Tuesday!",
            "G'day! Happy Tuesday!"
        ],
        'Wednesday': [
            "G'day! Happy Hump Day! 🐪",
            "G'day! Happy Hump Day! 🐪"
        ],
        'Thursday': [
            "G'day! Happy Thursday!",
            "G'day! Happy Thursday!"
        ],
        'Friday': [
            "G'day! Happy Friday — TGIF! 🎉",
            "G'day! Happy Friday — TGIF! 🎉"
        ],
        'Saturday': [
            "G'day! Happy Saturday!",
            "G'day! Happy Saturday!"
        ],
        'Sunday': [
            "G'day! Happy Sunday!",
            "G'day! Happy Sunday!"
        ]
    }
    
    greetings = day_greetings.get(day)
    if greetings:
        return random.choice(greetings)
    return None


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
    Simple greeting without casual questions.
    """
    now = timezone.now()
    current_hour = now.hour
    current_day = now.strftime('%A')
    
    # Get day-based greeting (simple, no questions)
    day_greeting = _get_day_greeting(current_day)
    
    # Get time-based greeting (simple, no questions)
    time_greeting = _get_time_greeting(current_hour)
    
    # Build structured message with proper formatting and line breaks
    message_lines = []
    
    # Start with bold day greeting
    if day_greeting:
        message_lines.append(f"**{day_greeting}**")
    else:
        # Fallback if no day greeting
        message_lines.append("**G'day!**")
    
    # Add time greeting if available (simple, no questions)
    if time_greeting:
        message_lines.append(time_greeting)
    
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

