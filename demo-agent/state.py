from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from datetime import datetime

class AgentState(BaseModel):
    """Agent state that maintains conversation context and tool results"""
    # Session ID for conversation tracking
    session_id: str
    # Messages is a list of dicts like {"role":"user"/"assistant"/"system", "content": "..."}
    messages: List[Dict[str, Any]] = []
    # Tool result stores last tool output (any serializable obj)
    tool_result: Optional[Dict[str, Any]] = None
    # Next action will be a string: 'rag' | 'car' | 'final'
    next_action: Optional[str] = None
    # Track tool calls for context
    tool_calls: List[Dict[str, Any]] = []
    # Timestamp for session management
    last_activity: datetime = datetime.now()
    
    class Config:
        arbitrary_types_allowed = True

