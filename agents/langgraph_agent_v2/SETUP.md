# LangGraph Agent V2 - Setup Guide

## Overview

LangGraph Agent V2 is an enhanced, modular agent with:
- ✅ Parallel processing for speed
- ✅ LLM-first decision making
- ✅ Multi-layer validation
- ✅ Proper service discovery handling
- ✅ Modular, maintainable code structure

## Enabling the Agent

To enable Agent V2, add to your Django settings:

```python
# settings.py
USE_LANGGRAPH_AGENT_V2 = True  # Enable Agent V2
USE_LANGGRAPH_AGENT = True      # Keep V1 as fallback
```

**Note:** Agent V2 is disabled by default. Set `USE_LANGGRAPH_AGENT_V2 = True` to enable it.

## Architecture

### Graph Flow

```
preprocess (parallel: intent + contact + context)
    ↓
route (LLM decision)
    ↓
knowledge/vehicle/direct
    ↓
reasoning (parallel: intent + structure + coverage)
    ↓
generation
    ↓
validation (parallel: fact + completeness + tone)
    ↓
postprocess (parallel: suggestions + formatting)
    ↓
final → END
```

### Parallel Processing

The agent uses parallel processing in multiple stages:

1. **Preprocessing**: Intent classification, contact extraction, context analysis (3 parallel)
2. **Knowledge Retrieval**: Multiple query variations (parallel)
3. **Reasoning**: Intent analysis, structure planning, coverage definition (3 parallel)
4. **Validation**: Fact checking, completeness, tone validation (3 parallel)
5. **Postprocessing**: Suggestions generation, response formatting (2 parallel)

## File Structure

```
langgraph_agent_v2/
├── nodes/          # All graph nodes (modular)
├── tools/          # Utility tools (LLM, RAG, etc.)
├── prompts/        # Prompt templates
├── graph.py        # Graph structure
├── integration.py # API integration
└── state.py        # State definition
```

## Integration

The agent integrates seamlessly with:
- ✅ WebSocket API (`ws/chat`)
- ✅ REST API (`/api/chats/messages/chat`)
- ✅ SSE Streaming (`/api/chats/messages/chat/stream`)

No changes needed to frontend - same API contract.

## Configuration

Edit `config.py` to adjust:
- LLM parameters
- Parallel workers
- Validation thresholds
- RAG parameters

## Testing

To test the agent:

1. Set `USE_LANGGRAPH_AGENT_V2 = True` in settings
2. Send a message via WebSocket or REST API
3. Check logs for `[AGENT_V2]` prefix

## Troubleshooting

- **Import errors**: Ensure all dependencies are installed
- **Graph compilation errors**: Check LangGraph version compatibility
- **Performance issues**: Adjust `MAX_PARALLEL_WORKERS` in config.py
