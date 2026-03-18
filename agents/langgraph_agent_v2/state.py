"""
Enhanced state definition for LangGraph Agent V2.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AgentState:
    """
    Enhanced state for LangGraph Agent V2.
    Maintains conversation context, user info, and all processing results.
    """
    # Core
    session_id: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    
    # User Information
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    callback_preferred_datetime: Optional[str] = None  # free-text preferred callback date+time
    callback_timezone: Optional[str] = None  # free-text timezone, e.g. "AEST", "UTC+10"
    step: str = "chatting"  # chatting, name, email, phone, confirmation, callback_schedule, complete

    # Conversation counters / flow control
    question_count: int = 0  # number of user questions/messages (used for team connection offer cadence)
    last_team_offer_count: int = 0  # last question_count when we offered team connection
    awaiting_team_connection_confirm: bool = False  # waiting for user yes/no to connect with team
    
    # Preprocessing Results
    question_type: Optional[str] = None  # service_discovery, domain_question, vehicle_search, contact_request, greeting, goodbye
    rag_query: Optional[str] = None
    context_analysis: Optional[Dict] = None
    contact_info_detected: bool = False
    
    # Routing
    next_action: Optional[str] = None  # knowledge, vehicle, direct, contact
    routing_reason: Optional[str] = None
    
    # Knowledge Retrieval
    rag_context: List[Dict] = field(default_factory=list)
    knowledge_results: List[Dict] = field(default_factory=list)
    used_rag: bool = False  # True only when we actually performed knowledge retrieval
    
    # Reasoning
    reasoning_output: Optional[Dict] = None  # Contains intent, structure, coverage
    
    # Response Generation
    draft_response: Optional[str] = None
    final_response: Optional[str] = None

    # Follow-up (streamed as separate message by WebSocket layer)
    followup_type: str = ""  # e.g., 'team_connection'
    followup_message: str = ""
    
    # Validation
    validation_result: Optional[Dict] = None
    improvement_suggestions: Optional[List[str]] = None
    validation_retry_count: int = 0
    
    # Post-processing
    suggestions: List[str] = field(default_factory=list)
    
    # Flags
    should_ask_for_name: bool = False
    should_offer_team_connection: bool = False
    is_complete: bool = False
    needs_info: Optional[str] = None  # name, email, phone, callback_schedule
    collecting_user_info: bool = False
    
    # Metadata
    last_activity: datetime = field(default_factory=datetime.now)
    error_count: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            'session_id': self.session_id,
            'messages': self.messages,
            'user_name': self.user_name,
            'user_email': self.user_email,
            'user_phone': self.user_phone,
            'callback_preferred_datetime': self.callback_preferred_datetime,
            'callback_timezone': self.callback_timezone,
            'step': self.step,
            'question_count': self.question_count,
            'last_team_offer_count': self.last_team_offer_count,
            'awaiting_team_connection_confirm': self.awaiting_team_connection_confirm,
            'question_type': self.question_type,
            'rag_query': self.rag_query,
            'context_analysis': self.context_analysis,
            'contact_info_detected': self.contact_info_detected,
            'next_action': self.next_action,
            'routing_reason': self.routing_reason,
            'rag_context': self.rag_context,
            'knowledge_results': self.knowledge_results,
            'used_rag': self.used_rag,
            'reasoning_output': self.reasoning_output,
            'draft_response': self.draft_response,
            'final_response': self.final_response,
            'followup_type': self.followup_type,
            'followup_message': self.followup_message,
            'validation_result': self.validation_result,
            'improvement_suggestions': self.improvement_suggestions,
            'validation_retry_count': self.validation_retry_count,
            'suggestions': self.suggestions,
            'should_ask_for_name': self.should_ask_for_name,
            'should_offer_team_connection': self.should_offer_team_connection,
            'is_complete': self.is_complete,
            'needs_info': self.needs_info,
            'collecting_user_info': self.collecting_user_info,
            'last_activity': self.last_activity.isoformat() if isinstance(self.last_activity, datetime) else self.last_activity,
            'error_count': self.error_count,
            'tool_calls': self.tool_calls,
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
            callback_preferred_datetime=data.get('callback_preferred_datetime'),
            callback_timezone=data.get('callback_timezone'),
            step=data.get('step', 'chatting'),
            question_count=data.get('question_count', 0),
            last_team_offer_count=data.get('last_team_offer_count', 0),
            awaiting_team_connection_confirm=data.get('awaiting_team_connection_confirm', False),
            question_type=data.get('question_type'),
            rag_query=data.get('rag_query'),
            context_analysis=data.get('context_analysis'),
            contact_info_detected=data.get('contact_info_detected', False),
            next_action=data.get('next_action'),
            routing_reason=data.get('routing_reason'),
            rag_context=data.get('rag_context', []),
            knowledge_results=data.get('knowledge_results', []),
            used_rag=bool(data.get('used_rag', False)),
            reasoning_output=data.get('reasoning_output'),
            draft_response=data.get('draft_response'),
            final_response=data.get('final_response'),
            followup_type=data.get('followup_type', '') or '',
            followup_message=data.get('followup_message', '') or '',
            validation_result=data.get('validation_result'),
            improvement_suggestions=data.get('improvement_suggestions'),
            validation_retry_count=data.get('validation_retry_count', 0),
            suggestions=data.get('suggestions', []),
            should_ask_for_name=data.get('should_ask_for_name', False),
            should_offer_team_connection=data.get('should_offer_team_connection', False),
            is_complete=data.get('is_complete', False),
            needs_info=data.get('needs_info'),
            collecting_user_info=data.get('collecting_user_info', False),
            last_activity=last_activity,
            error_count=data.get('error_count', 0),
            tool_calls=data.get('tool_calls', []),
        )
