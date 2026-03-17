# LangGraph Agent V2

Enhanced, modular LangGraph agent with parallel processing and comprehensive quality assurance.

## Structure

```
langgraph_agent_v2/
├── __init__.py              # Package initialization
├── config.py                # Configuration constants
├── state.py                 # Enhanced AgentState definition
├── graph.py                 # LangGraph structure and compilation
├── integration.py           # WebSocket/REST API integration
├── nodes/                   # All graph nodes
│   ├── __init__.py
│   ├── preprocess.py        # Parallel preprocessing (intent, contact, context)
│   ├── routing.py           # Intelligent routing decisions
│   ├── knowledge.py         # RAG knowledge retrieval
│   ├── vehicle.py           # Vehicle search
│   ├── contact.py           # Contact collection
│   ├── reasoning.py         # Parallel multi-agent reasoning
│   ├── generation.py        # Response generation
│   ├── validation.py        # Multi-layer validation
│   ├── postprocess.py       # Suggestions and formatting
│   └── final.py             # Final response preparation
├── tools/                   # Utility tools
│   ├── __init__.py
│   ├── llm.py               # LLM client and utilities
│   ├── rag.py                # RAG search with variations
│   ├── vehicle_search.py     # Vehicle search wrapper
│   └── contact_extraction.py # Contact info extraction
└── prompts/                 # Prompt templates
    ├── __init__.py
    ├── system.py            # System prompt builder
    └── validation.py        # Validation prompts
```

## Features

- **Parallel Processing**: Multiple operations run concurrently for speed
- **LLM-First Decisions**: All routing and validation decisions made by LLM
- **Multi-Layer Validation**: Fact checking, completeness, and tone validation
- **Service Discovery**: Proper handling of "what are my options?" queries
- **Modular Design**: Code divided into logical, maintainable modules

## Usage

The agent integrates seamlessly with existing WebSocket API:

```python
from agents.langgraph_agent_v2 import ChatAPIIntegration

result = ChatAPIIntegration.process_message(session_id, user_message)
```

## Graph Flow

```
preprocess (parallel) → route → knowledge/vehicle/direct
    ↓
reasoning (parallel) → generation → validation
    ↓
postprocess (parallel) → final → END
```

## Configuration

Edit `config.py` to adjust:
- LLM parameters (temperature, max_tokens)
- Parallel processing workers
- Validation thresholds
- RAG parameters
