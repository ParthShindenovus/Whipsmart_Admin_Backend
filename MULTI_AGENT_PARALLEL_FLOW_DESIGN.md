# Multi-Agent Parallel Execution Flow Design

## Overview
The Multi-Agent Reasoning System uses parallel execution to optimize response time by running independent agents concurrently. This document describes the complete flow from user question to final answer.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    UNIFIED AGENT (Entry Point)                  │
│  - Receives user message                                        │
│  - Classifies question (needs RAG or not)                       │
│  - Fetches RAG context if needed                                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              MULTI-AGENT REASONING ORCHESTRATOR                 │
│  Coordinates parallel agent execution                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │   Agent 1      │
                    │  (Classifier)  │
                    │   Sequential   │
                    └────────┬───────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                ▼                         ▼
        ┌───────────────┐         ┌───────────────┐
        │   Agent 3    │         │   Agent 4     │
        │  (Structure  │         │  (Coverage    │
        │   Planner)   │         │   Definer)    │
        │   PARALLEL   │         │   PARALLEL    │
        └───────┬───────┘         └───────┬───────┘
                │                         │
                └────────────┬─────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Prompt Assembly│
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Response Gen    │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │   Agent 5      │
                    │  (Validator)   │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Final Answer  │
                    └────────────────┘
```

---

## Detailed Execution Flow

### Phase 1: Question Classification & RAG Retrieval (Unified Agent)

```
User Message: "How do novated leases affect tax and superannuation?"
    │
    ▼
┌─────────────────────────────────────┐
│ 1. Classify Question                │
│    - Domain question? → Yes          │
│    - Needs RAG? → Yes               │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ 2. Fetch RAG Context                │
│    - Query Pinecone                 │
│    - Retrieve top 3-4 chunks        │
│    - Format context                 │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ 3. Invoke Multi-Agent Orchestrator │
│    - Pass: question, RAG context,   │
│            conversation history      │
└──────────────┬──────────────────────┘
               │
               ▼
```

### Phase 2: Multi-Agent Orchestration (Parallel Execution)

#### Step 1: Agent 1 - Classifier (Sequential - Required First)

```
┌─────────────────────────────────────────────┐
│ AGENT 1: Question Classifier                │
│ ─────────────────────────────────────────── │
│ Input:                                       │
│   - User question                            │
│   - Conversation history                     │
│                                              │
│ Process:                                     │
│   - Analyze question type                    │
│   - Determine domain (EV/leasing/finance)   │
│   - Assess complexity level                  │
│   - Extract intent & key topics              │
│                                              │
│ Output:                                      │
│   {                                          │
│     "question_type": "informational",        │
│     "domain": "leasing",                     │
│     "complexity": "medium",                  │
│     "intent": "...",                         │
│     "key_topics": ["tax", "superannuation"]  │
│   }                                          │
│                                              │
│ Time: ~1-2 seconds                           │
└──────────────────┬──────────────────────────┘
                    │
                    │ (Output required by Agent 3 & 4)
                    │
```

#### Step 2: Agent 3 & Agent 4 - Parallel Execution

```
                    ┌─────────────────────────────┐
                    │   Agent 1 Output Ready      │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
    ┌───────────────────────────┐  ┌───────────────────────────┐
    │ AGENT 3: Structure Planner │  │ AGENT 4: Coverage Definer │
    │ ───────────────────────── │  │ ──────────────────────── │
    │ Input:                     │  │ Input:                    │
    │   - User question          │  │   - User question         │
    │   - Agent 1 output         │  │   - Agent 1 output        │
    │                            │  │   - RAG context          │
    │ Process:                   │  │                          │
    │   - Plan answer structure  │  │ Process:                 │
    │   - Determine length       │  │   - Define must-include   │
    │   - Plan ordering          │  │   - Identify optional    │
    │   - Break down sections    │  │   - List exclusions      │
    │                            │  │   - Apply strict mode     │
    │ Output:                    │  │                          │
    │   {                         │  │ Output:                  │
    │     "length": "short",     │  │   {                      │
    │     "structure": "bullets", │  │     "must_include": [...],│
    │     "ordering": "...",     │  │     "optional": [...],   │
    │     "sections": [...]      │  │     "exclude": [...]      │
    │   }                         │  │   }                      │
    │                            │  │                          │
    │ Time: ~2-3 seconds          │  │ Time: ~2-3 seconds       │
    └──────────────┬──────────────┘  └──────────────┬───────────┘
                   │                                │
                   │     PARALLEL EXECUTION        │
                   │     (Both run simultaneously) │
                   │                                │
                   └────────────┬───────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │  Both Results Ready    │
                    │  Total Time: ~2-3s     │
                    │  (Not 4-6s sequential) │
                    └───────────┬────────────┘
```

**Parallel Execution Details:**

```python
ThreadPoolExecutor(max_workers=2)
    │
    ├─► Future 1: Agent 3 (Structure Planner)
    │   └─► API Call to OpenAI
    │       └─► Returns structure plan
    │
    └─► Future 2: Agent 4 (Coverage Definer)
        └─► API Call to OpenAI
            └─► Returns coverage requirements

as_completed([Future1, Future2])
    │
    ├─► Agent 3 completes → Log: "Agent 3 completed"
    └─► Agent 4 completes → Log: "Agent 4 completed"
```

**Performance Gain:**
- **Sequential**: Agent 3 (2s) + Agent 4 (2s) = **4 seconds**
- **Parallel**: max(Agent 3, Agent 4) = **2 seconds**
- **Savings**: ~50% time reduction

#### Step 3: Prompt Assembly

```
┌─────────────────────────────────────────────┐
│ Prompt Assembler                            │
│ ─────────────────────────────────────────── │
│ Combines:                                    │
│   - User question                            │
│   - Agent 1: Classification                  │
│   - Agent 3: Structure plan                  │
│   - Agent 4: Coverage requirements           │
│   - RAG context                              │
│   - Conversation history                     │
│                                              │
│ Output: Comprehensive prompt for response    │
│         generation                           │
└──────────────────┬──────────────────────────┘
```

#### Step 4: Structured Response Generation

```
┌─────────────────────────────────────────────┐
│ Response Generator                           │
│ ─────────────────────────────────────────── │
│ Input: Assembled prompt                      │
│                                              │
│ Process:                                     │
│   - Generate draft answer                    │
│   - Follow structure plan (Agent 3)          │
│   - Include must-have items (Agent 4)        │
│   - Apply GOLD Standard style           │
│   - Keep concise (2-4 key points)            │
│                                              │
│ Output: Draft answer                         │
│ Time: ~1-2 seconds                           │
└──────────────────┬──────────────────────────┘
```

#### Step 5: Coverage Validation (Agent 5)

```
┌─────────────────────────────────────────────┐
│ AGENT 5: Coverage Validator                  │
│ ─────────────────────────────────────────── │
│ Input:                                       │
│   - Draft answer                             │
│   - Agent 4 coverage requirements             │
│   - RAG context                              │
│                                              │
│ Process:                                     │
│   - Check if all must-include items present  │
│   - Verify no unsupported features           │
│   - Check for repetition/filler              │
│   - Validate length/structure                │
│                                              │
│ Output:                                      │
│   {                                          │
│     "status": "APPROVED" | "FIX_REQUIRED",   │
│     "fix_required": "..."                    │
│   }                                          │
│                                              │
│ Time: ~1 second                              │
└──────────────────┬──────────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Status Check          │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌───────────────┐      ┌──────────────────┐
│   APPROVED    │      │  FIX_REQUIRED    │
│               │      │                  │
│ Use draft     │      │ Apply fixes      │
│ answer        │      │ Regenerate       │
└───────┬───────┘      └────────┬─────────┘
        │                       │
        └───────────┬───────────┘
                    │
                    ▼
            ┌───────────────┐
            │  Final Answer │
            └───────────────┘
```

---

## Complete Timeline Example

```
Time    │ Activity
────────┼─────────────────────────────────────────────────────
0.0s    │ User sends: "How do novated leases affect tax?"
        │
0.1s    │ Unified Agent: Classify question → Needs RAG
        │
0.2s    │ Unified Agent: Fetch RAG context from Pinecone
        │
1.5s    │ RAG context retrieved (3 chunks)
        │
1.6s    │ ┌─► Multi-Agent Orchestrator starts
        │ │
1.7s    │ ├─► Agent 1 (Classifier) starts
        │ │   └─► API call to OpenAI
        │ │
2.5s    │ ├─► Agent 1 completes
        │ │   └─► Output: {type: "informational", domain: "leasing"}
        │ │
2.6s    │ ├─► ThreadPoolExecutor starts (2 workers)
        │ │   ├─► Agent 3 (Structure) ──┐
        │ │   │   └─► API call          │
        │ │   │                         │ PARALLEL
        │ │   └─► Agent 4 (Coverage) ──┤
        │ │       └─► API call          │
        │ │                             │
4.0s    │ ├─► Agent 3 completes ────────┘
        │ │   └─► Output: {length: "short", structure: "bullets"}
        │ │
4.2s    │ ├─► Agent 4 completes ────────┘
        │ │   └─► Output: {must_include: ["tax", "super"], ...}
        │ │
4.3s    │ ├─► Parallel execution complete (1.7s total, not 3.4s)
        │ │
4.4s    │ ├─► Assemble prompt with all outputs
        │ │
4.5s    │ ├─► Generate structured response
        │ │   └─► API call to OpenAI
        │ │
5.8s    │ ├─► Draft answer generated
        │ │
5.9s    │ ├─► Agent 5 (Validator) starts
        │ │   └─► API call to OpenAI
        │ │
6.5s    │ ├─► Agent 5 completes → APPROVED
        │ │
6.6s    │ └─► Final answer ready
        │
6.7s    │ Return to Unified Agent → Send to user
```

**Total Time: ~6.7 seconds**
- Without parallel: ~8.4 seconds (Agent 3 + Agent 4 sequential)
- **Time Saved: ~1.7 seconds (20% improvement)**

---

## Data Flow Diagram

```
┌──────────────┐
│ User Question│
└──────┬───────┘
       │
       ▼
┌──────────────────┐      ┌──────────────┐
│ Unified Agent    │─────►│ RAG Context │
│ (Classification) │      │ (Pinecone)  │
└──────┬───────────┘      └──────────────┘
       │
       │ question, rag_context, conversation_history
       ▼
┌─────────────────────────────────────┐
│ Multi-Agent Orchestrator             │
│                                      │
│  ┌──────────────┐                   │
│  │ Agent 1      │                   │
│  │ (Classifier) │                   │
│  └──────┬───────┘                   │
│         │                            │
│         │ classification_output      │
│         │                            │
│    ┌────┴────┐                      │
│    │         │                      │
│    ▼         ▼                      │
│  ┌──────┐ ┌──────┐                 │
│  │Agent3│ │Agent4│  PARALLEL       │
│  │Struct│ │Cover │  EXECUTION      │
│  └───┬──┘ └───┬──┘                 │
│      │        │                    │
│      │        │                    │
│      └───┬────┘                    │
│          │                          │
│          │ structure + coverage     │
│          ▼                          │
│  ┌──────────────┐                  │
│  │   Assemble   │                  │
│  │    Prompt    │                  │
│  └──────┬───────┘                  │
│         │                           │
│         ▼                           │
│  ┌──────────────┐                  │
│  │   Generate   │                  │
│  │   Response   │                  │
│  └──────┬───────┘                  │
│         │                           │
│         ▼                           │
│  ┌──────────────┐                  │
│  │   Agent 5    │                  │
│  │ (Validator)  │                  │
│  └──────┬───────┘                  │
│         │                           │
│         │ final_answer              │
│         ▼                           │
└─────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ Final Answer │
└──────────────┘
```

---

## Error Handling Flow

```
┌─────────────────────────────────────────────┐
│ Parallel Execution Error Handling            │
└─────────────────────────────────────────────┘

Agent 3 Execution:
    │
    ├─► Success → Use result
    │
    └─► Failure → Log error
        └─► Use fallback:
            {
              "length": "medium",
              "structure": "bullets",
              "ordering": "logical flow",
              "sections": []
            }

Agent 4 Execution:
    │
    ├─► Success → Use result
    │
    └─► Failure → Log error
        └─► Use fallback:
            {
              "must_include": [],
              "optional": [],
              "exclude": []
            }

Critical: If both fail, system continues with fallbacks
          (graceful degradation)
```

---

## Log Output Example

```
INFO [MULTI-AGENT] Starting agent execution...
INFO [MULTI-AGENT] Step 1: Running Agent 1 (Classifier)...
INFO [MULTI-AGENT] Agent 1 completed in 1.23s
INFO [MULTI-AGENT] Step 2: Running Agent 3 and Agent 4 in parallel...
INFO [MULTI-AGENT] Agent 3 (Structure Planner) completed
INFO [MULTI-AGENT] Agent 4 (Coverage Definer) completed
INFO [MULTI-AGENT] Parallel agents (Agent 3 & 4) completed in 2.15s (parallel execution)
INFO [MULTI-AGENT] Step 3: Assembling prompt with all agent outputs...
INFO [MULTI-AGENT] Step 4: Generating structured response...
INFO [MULTI-AGENT] Step 5: Validating draft answer...
INFO [MULTI-AGENT] Draft answer approved
INFO [MULTI-AGENT] Final answer generated in 6.78s total
INFO [MULTI-AGENT] Performance breakdown: Agent1=1.23s, Parallel(Agent3+4)=2.15s
```

---

## Key Benefits of Parallel Execution

1. **Performance**: 40-50% faster when Agent 3 and Agent 4 run concurrently
2. **Scalability**: Can handle more requests per second
3. **User Experience**: Faster response times
4. **Resource Efficiency**: Better utilization of I/O wait time during API calls
5. **Resilience**: Independent error handling per agent

---

## Dependencies Graph

```
Agent 1 (Classifier)
    │
    ├─► Required by: Agent 3, Agent 4
    │
    └─► Independent: Can run first

Agent 3 (Structure Planner)
    │
    ├─► Depends on: Agent 1 output
    │
    └─► Independent of: Agent 4 (can run in parallel)

Agent 4 (Coverage Definer)
    │
    ├─► Depends on: Agent 1 output, RAG context
    │
    └─► Independent of: Agent 3 (can run in parallel)

Agent 5 (Validator)
    │
    ├─► Depends on: Agent 4 output, Draft answer
    │
    └─► Must run after: Response generation
```

---

## Configuration

```python
# ThreadPoolExecutor Settings
max_workers = 2  # For Agent 3 & Agent 4 parallel execution

# Timing
Agent 1: ~1-2 seconds
Agent 3: ~2-3 seconds (parallel)
Agent 4: ~2-3 seconds (parallel)
Response Gen: ~1-2 seconds
Agent 5: ~1 second

Total: ~6-8 seconds (with parallel)
Total: ~8-10 seconds (without parallel)
```

---

## Future Enhancements

1. **More Parallelism**: Could run Agent 5 validation in parallel with response generation (if architecture allows)
2. **Caching**: Cache Agent 1 results for similar questions
3. **Async/Await**: Migrate to async/await for better I/O handling
4. **Batch Processing**: Process multiple questions in parallel batches

