# LangGraph Agent - Refactored Unified Agent

A modular, production-ready agent implementation using LangGraph and LangChain with properly separated concerns.

## Architecture Overview

```
agents/langgraph_agent/
├── __init__.py           # Package exports
├── config.py             # Configuration and constants
├── state.py              # Agent state definition (dataclass)
├── classifier.py         # Question classification logic
├── prompts.py            # LLM prompts
├── tools.py              # LangChain tools
├── agent.py              # Main agent orchestrator
└── README.md             # This file
```

## Key Features

### 1. **Modular Architecture**
- **Separation of Concerns**: Each module has a single responsibility
- **Easy to Test**: Each component can be tested independently
- **Easy to Extend**: Add new tools or prompts without modifying core logic
- **Easy to Maintain**: Clear structure makes debugging and updates straightforward

### 2. **LangChain Integration**
- All tools are LangChain `@tool` decorated functions
- Proper tool signatures with type hints and docstrings
- Easy integration with LangChain agents and chains

### 3. **LangGraph Ready**
- State is defined as a dataclass for LangGraph compatibility
- State can be easily serialized/deserialized
- Ready for graph-based conversation flows

### 4. **Configuration Management**
- All constants in one place (`config.py`)
- Easy to adjust thresholds, keywords, and parameters
- Environment-based configuration support

## Module Descriptions

### `config.py`
Centralized configuration for the agent:
- Conversation steps and question types
- Domain and user action keywords
- Connection intent patterns
- LLM parameters (temperature, max tokens)
- Thresholds for name collection and team connection

**Key Classes:**
- `ConversationStep`: Enum for conversation states
- `QuestionType`: Enum for question classification

### `state.py`
Agent state definition using dataclass:
- Session and conversation tracking
- User information storage
- Tool results and routing
- RAG context management
- Conversation flow flags

**Key Class:**
- `AgentState`: Main state dataclass with serialization methods

### `classifier.py`
Question classification logic:
- Determines if RAG context is needed
- Classifies questions as domain, user_action, or unclear
- Heuristic-based classification using keywords and patterns

**Key Class:**
- `QuestionClassifier`: Static methods for question analysis

### `prompts.py`
LLM prompts for different scenarios:
- System prompt template with personalization
- Domain question prompt with RAG context
- Classification prompt
- Follow-up generation prompt

**Key Templates:**
- `SYSTEM_PROMPT_TEMPLATE`: Main system prompt
- `DOMAIN_QUESTION_PROMPT_TEMPLATE`: Enhanced prompt for domain questions
- `CLASSIFICATION_PROMPT`: For question classification
- `FOLLOWUP_GENERATION_PROMPT`: For follow-up message generation

### `tools.py`
LangChain tools for agent actions:
- `search_knowledge_base`: Search RAG system
- `search_vehicles`: Search available vehicles
- `collect_user_info`: Extract and store user information
- `update_user_info`: Update specific user fields
- `submit_lead`: Submit lead to HubSpot
- `end_conversation`: End conversation gracefully

**Key Function:**
- `get_tools()`: Returns list of all available tools

### `agent.py`
Main agent orchestrator:
- Handles message processing
- Manages conversation flow
- Integrates all components
- Handles LLM calls and response generation

**Key Class:**
- `LangGraphAgent`: Main orchestrator with `handle_message()` entry point

## Usage

### Basic Usage

```python
from agents.langgraph_agent.agent import LangGraphAgent
from chats.models import Session

# Get or create session
session = Session.objects.get(id=session_id)

# Initialize agent
agent = LangGraphAgent(session)

# Handle user message
response = agent.handle_message("What is a novated lease?")

# Response structure
{
    'message': 'The assistant response...',
    'suggestions': ['Suggestion 1', 'Suggestion 2'],
    'complete': False,
    'needs_info': 'name',  # or 'email', 'phone', None
    'escalate_to': None,
    'knowledge_results': [...],
    'metadata': {...}
}
```

### Adding a New Tool

1. Create a new function in `tools.py` with `@tool` decorator:

```python
@tool
def my_new_tool(param1: str, param2: int) -> Dict[str, Any]:
    """
    Description of what the tool does.
    
    Args:
        param1: Description
        param2: Description
        
    Returns:
        Dictionary with results
    """
    # Implementation
    return {"success": True, "result": "..."}
```

2. Add to `get_tools()` function:

```python
def get_tools() -> List:
    return [
        search_knowledge_base,
        search_vehicles,
        my_new_tool,  # Add here
        # ... other tools
    ]
```

### Customizing Prompts

Edit `prompts.py` to customize LLM prompts:

```python
SYSTEM_PROMPT_TEMPLATE = """Your custom system prompt..."""
```

### Adjusting Configuration

Edit `config.py` to adjust behavior:

```python
# Adjust when to ask for name
NAME_COLLECTION_THRESHOLD = 2  # Ask after 2-3 questions

# Add new domain keywords
DOMAIN_KEYWORDS = [
    'existing keywords...',
    'new keyword',
]

# Adjust LLM parameters
LLM_TEMPERATURE_RESPONSE = 0.7
LLM_MAX_TOKENS_RESPONSE = 512
```

## Integration with Existing Code

### Replacing Old UnifiedAgent

The old `agents/unified_agent.py` can be replaced with:

```python
# Old way
from agents.unified_agent import UnifiedAgent
agent = UnifiedAgent(session)
response = agent.handle_message(user_message)

# New way
from agents.langgraph_agent.agent import LangGraphAgent
agent = LangGraphAgent(session)
response = agent.handle_message(user_message)
```

### Backward Compatibility

The new agent maintains the same response structure as the old one, so frontend code doesn't need changes.

## Testing

### Unit Tests

```python
from agents.langgraph_agent.classifier import QuestionClassifier

# Test classification
question_type, rag_query = QuestionClassifier.classify(
    "What is a novated lease?",
    []
)
assert question_type == "domain"
assert rag_query == "What is a novated lease?"
```

### Integration Tests

```python
from agents.langgraph_agent.agent import LangGraphAgent
from chats.models import Session

session = Session.objects.create(visitor=visitor)
agent = LangGraphAgent(session)
response = agent.handle_message("Hello!")

assert response['message']
assert 'suggestions' in response
```

## Performance Considerations

1. **RAG Context Fetching**: Only fetches when needed (domain questions)
2. **Conversation History**: Limited to last 4 messages by default
3. **LLM Calls**: Single call per message (no multi-step reasoning in basic version)
4. **Database Queries**: Minimal queries, cached where possible

## Future Enhancements

1. **Multi-Agent Reasoning**: Integrate `MultiAgentReasoning` for complex questions
2. **Graph-Based Flows**: Implement full LangGraph workflow
3. **Streaming Responses**: Add streaming support for real-time responses
4. **Caching**: Add response caching for common questions
5. **Analytics**: Track question types, response quality, user satisfaction
6. **A/B Testing**: Support multiple prompt versions

## Troubleshooting

### Agent not responding
- Check Azure OpenAI credentials in settings
- Verify RAG system is working
- Check logs for error messages

### RAG context not being fetched
- Verify question classification is working
- Check if keywords are in `config.py`
- Ensure RAG tool is properly configured

### User information not being collected
- Check if `collect_user_info` tool is being called
- Verify HubSpot integration is working
- Check database for saved information

## Contributing

When adding new features:
1. Keep modules focused and single-responsibility
2. Add type hints to all functions
3. Add docstrings to all public methods
4. Update this README with new features
5. Add tests for new functionality
6. Follow existing code style and patterns

## License

Same as parent project.
