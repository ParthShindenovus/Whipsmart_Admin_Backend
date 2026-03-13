"""
LangGraph state definition for the unified agent.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class AgentState:
    """
    State for the LangGraph agent.
    Maintains conversation context, user info, and tool results.
    """
    # Session and conversation
    session_id: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    
    # User information
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    
    # Visitor profile data (persistent across sessions)
    visitor_profile: Dict[str, Any] = field(default_factory=dict)
    
    # Conversation state
    step: str = "chatting"  # chatting, name, email, phone, confirmation, complete
    
    # Tool results and routing
    tool_result: Optional[Dict[str, Any]] = None
    next_action: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    
    # RAG context
    rag_context: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_results: List[Dict[str, Any]] = field(default_factory=list)
    
    # Question classification
    question_type: Optional[str] = None  # domain, user_action, unclear
    rag_query: Optional[str] = None
    
    # Flags for conversation flow
    asking_for_info_after_decline: bool = False
    asking_before_end: bool = False
    should_ask_for_name: bool = False
    should_offer_team_connection: bool = False
    
    # Response tracking
    last_assistant_message: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    followup_type: str = ""  # ask_name, ask_to_connect, follow_up, or empty
    followup_message: str = ""
    
    # Metadata
    last_activity: datetime = field(default_factory=datetime.now)
    is_complete: bool = False
    needs_info: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            'session_id': self.session_id,
            'messages': self.messages,
            'user_name': self.user_name,
            'user_email': self.user_email,
            'user_phone': self.user_phone,
            'visitor_profile': self.visitor_profile,
            'step': self.step,
            'tool_result': self.tool_result,
            'next_action': self.next_action,
            'tool_calls': self.tool_calls,
            'rag_context': self.rag_context,
            'knowledge_results': self.knowledge_results,
            'question_type': self.question_type,
            'rag_query': self.rag_query,
            'asking_for_info_after_decline': self.asking_for_info_after_decline,
            'asking_before_end': self.asking_before_end,
            'should_ask_for_name': self.should_ask_for_name,
            'should_offer_team_connection': self.should_offer_team_connection,
            'last_assistant_message': self.last_assistant_message,
            'suggestions': self.suggestions,
            'followup_type': self.followup_type,
            'followup_message': self.followup_message,
            'last_activity': self.last_activity.isoformat() if isinstance(self.last_activity, datetime) else self.last_activity,
            'is_complete': self.is_complete,
            'needs_info': self.needs_info,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentState':
        """Create state from dictionary."""
        if isinstance(data, cls):
            return data
        
        # Handle datetime conversion
        last_activity = data.get('last_activity')
        if isinstance(last_activity, str):
            try:
                last_activity = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                last_activity = datetime.now()
        elif not isinstance(last_activity, datetime):
            last_activity = datetime.now()
        
        return cls(
            session_id=data.get('session_id', ''),
            messages=data.get('messages', []),
            user_name=data.get('user_name'),
            user_email=data.get('user_email'),
            user_phone=data.get('user_phone'),
            visitor_profile=data.get('visitor_profile', {}),
            step=data.get('step', 'chatting'),
            tool_result=data.get('tool_result'),
            next_action=data.get('next_action'),
            tool_calls=data.get('tool_calls', []),
            rag_context=data.get('rag_context', []),
            knowledge_results=data.get('knowledge_results', []),
            question_type=data.get('question_type'),
            rag_query=data.get('rag_query'),
            asking_for_info_after_decline=data.get('asking_for_info_after_decline', False),
            asking_before_end=data.get('asking_before_end', False),
            should_ask_for_name=data.get('should_ask_for_name', False),
            should_offer_team_connection=data.get('should_offer_team_connection', False),
            last_assistant_message=data.get('last_assistant_message'),
            suggestions=data.get('suggestions', []),
            followup_type=data.get('followup_type', ''),
            followup_message=data.get('followup_message', ''),
            last_activity=last_activity,
            is_complete=data.get('is_complete', False),
            needs_info=data.get('needs_info'),
        )
