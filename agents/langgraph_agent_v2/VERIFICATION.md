# How to Verify Agent V2 is Running

## Check Logs

When Agent V2 is active, you'll see these log messages:

### WebSocket API
```
[WEBSOCKET] Agent selection - V2: True, LangGraph: True
[WEBSOCKET] ===== USING LANGGRAPH AGENT V2 =====
[AGENT_V2] ===== USING LANGGRAPH AGENT V2 =====
[AGENT_V2] Processing message for session: <session_id>
[PREPROCESS] Processing message: ...
[PREPROCESS] Intent: service_discovery, Contact detected: False
[ROUTING] Service discovery detected, routing to knowledge
[KNOWLEDGE] Question type: service_discovery, Query: ...
```

### REST API
```
[REST_API] Agent selection - V2: True, LangGraph: True
[REST_API] ===== USING LANGGRAPH AGENT V2 =====
[AGENT_V2] ===== USING LANGGRAPH AGENT V2 =====
```

## Settings Check

Verify in `whipsmart_admin/settings.py`:
```python
USE_LANGGRAPH_AGENT_V2 = True  # Should be True
```

Or check environment variable:
```bash
USE_LANGGRAPH_AGENT_V2=True
```

## Expected Behavior

### Service Discovery Query ("what are my options?")
- ✅ Should classify as `service_discovery`
- ✅ Should search knowledge base for "WhipSmart services features capabilities"
- ✅ Should provide list of WhipSmart services
- ✅ Should NOT ask for contact information
- ✅ Should NOT talk about lease options

### Logs to Look For
```
[PREPROCESS] Intent: service_discovery
[ROUTING] Service discovery detected, routing to knowledge
[KNOWLEDGE] Service discovery detected - using service query
[GENERATION] Generating response for question type: service_discovery
```

## Troubleshooting

If you see:
- `[WEBSOCKET] Using LangGraph Agent V1` → V2 is NOT enabled
- `[WEBSOCKET] Using UnifiedAgent (fallback)` → V2 is NOT enabled
- No `[AGENT_V2]` logs → V2 is NOT being called

**Fix:** Set `USE_LANGGRAPH_AGENT_V2 = True` in settings.py
