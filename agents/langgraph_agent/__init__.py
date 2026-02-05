"""
LangGraph-based unified agent for WhipSmart.

This module provides a refactored agent implementation using LangGraph and LangChain
with properly separated concerns:

- config.py: Configuration and constants
- state.py: Agent state definition
- classifier.py: Question classification logic
- prompts.py: LLM prompts
- tools.py: LangChain tools
- agent.py: Main agent orchestrator

Usage:
    from agents.langgraph_agent.agent import LangGraphAgent
    from chats.models import Session
    
    session = Session.objects.get(id=session_id)
    agent = LangGraphAgent(session)
    response = agent.handle_message(user_message)
"""

from agents.langgraph_agent.agent import LangGraphAgent
from agents.langgraph_agent.state import AgentState
from agents.langgraph_agent.classifier import QuestionClassifier

__all__ = [
    'LangGraphAgent',
    'AgentState',
    'QuestionClassifier',
]
