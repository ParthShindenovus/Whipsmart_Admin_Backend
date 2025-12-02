"""
Agent state for LangGraph.
Adapted to work with Django models.
"""
from typing import List, Dict, Optional, Any
from datetime import datetime


class AgentState:
    """
    Agent state that maintains conversation context and tool results.
    This is a simple class (not Pydantic) to work with Django.
    """
    def __init__(self, session_id: str, messages: List[Dict[str, Any]] = None,
                 tool_result: Optional[Dict[str, Any]] = None,
                 next_action: Optional[str] = None,
                 tool_calls: List[Dict[str, Any]] = None,
                 last_activity: Optional[datetime] = None):
        self.session_id = session_id
        self.messages = messages or []
        self.tool_result = tool_result
        self.next_action = next_action
        self.tool_calls = tool_calls or []
        self.last_activity = last_activity or datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for LangGraph"""
        return {
            'session_id': self.session_id,
            'messages': self.messages,
            'tool_result': self.tool_result,
            'next_action': self.next_action,
            'tool_calls': self.tool_calls,
            'last_activity': self.last_activity.isoformat() if isinstance(self.last_activity, datetime) else self.last_activity
        }
    
    @classmethod
    def from_dict(cls, data) -> 'AgentState':
        """Create state from dictionary or AgentState object"""
        # If data is already an AgentState, return it
        if isinstance(data, AgentState):
            return data
        
        # If data is a dict, create from dict
        if isinstance(data, dict):
            # Handle datetime string conversion
            last_activity = data.get('last_activity')
            if isinstance(last_activity, str):
                try:
                    last_activity = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                except:
                    last_activity = datetime.now()
            elif last_activity is None:
                last_activity = datetime.now()
            
            return cls(
                session_id=data.get('session_id', ''),
                messages=data.get('messages', []),
                tool_result=data.get('tool_result'),
                next_action=data.get('next_action'),
                tool_calls=data.get('tool_calls', []),
                last_activity=last_activity
            )
        
        # Fallback: try to create from object attributes
        return cls(
            session_id=getattr(data, 'session_id', ''),
            messages=getattr(data, 'messages', []),
            tool_result=getattr(data, 'tool_result', None),
            next_action=getattr(data, 'next_action', None),
            tool_calls=getattr(data, 'tool_calls', []),
            last_activity=getattr(data, 'last_activity', datetime.now())
        )

