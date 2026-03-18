# LangGraph Agent - Complete Implementation Plan

## Document Version
- **Version:** 1.0
- **Created:** March 17, 2026
- **Status:** Implementation Blueprint
- **Purpose:** Comprehensive plan for building a robust, improved LangGraph agent with all functionality

---

## Executive Summary

This document outlines the complete implementation plan for a next-generation LangGraph agent that:
- ✅ Answers all questions perfectly (no wrong answers)
- ✅ Makes all decisions through LLM (no manual logic)
- ✅ Uses parallel processing for speed optimization
- ✅ Implements all functionality from requirements document
- ✅ Has robust quality assurance mechanisms
- ✅ Handles edge cases gracefully

**Implementation-sync notes (current LangGraph Agent V2):**
- **Single-shot RAG per message** (one Pinecone query per user message) for predictable latency/cost.
- **Validation runs only when RAG was used** (direct/greeting flows bypass validation entirely).
- **Contact extraction is LLM-only** (no regex) and can capture name/email/phone **anytime** in chat.
- **Contact details persist on `Visitor`** (name/email/phone), so future sessions don’t re-ask them.
- **Team connection is a separate follow-up message** after the main answer (WebSocket follow-up).
- If details already exist, the team-connect flow **confirms details and allows corrections** before completing.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [LangGraph Structure](#2-langgraph-structure)
3. [Node Design & Parallel Processing](#3-node-design--parallel-processing)
4. [State Management](#4-state-management)
5. [Quality Assurance System](#5-quality-assurance-system)
6. [Intent Classification & Routing](#6-intent-classification--routing)
7. [Knowledge Retrieval System](#7-knowledge-retrieval-system)
8. [Response Generation Pipeline](#8-response-generation-pipeline)
9. [Data Collection & Lead Management](#9-data-collection--lead-management)
10. [Error Handling & Recovery](#10-error-handling--recovery)
11. [Performance Optimization](#11-performance-optimization)
12. [Implementation Phases](#12-implementation-phases)
13. [Testing Strategy](#13-testing-strategy)

---

## 1. Architecture Overview

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER MESSAGE INPUT                        │
└───────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              LANGGRAPH ORCHESTRATOR                          │
│  - Entry Point: Message Receiver                            │
│  - State Initialization                                     │
│  - Graph Execution                                          │
└───────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              PARALLEL PREPROCESSING LAYER                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Intent       │  │ Contact Info  │  │ Context       │    │
│  │ Classifier   │  │ Extractor    │  │ Analyzer      │    │
│  │ (LLM)        │  │ (Regex+LLM)  │  │ (LLM)         │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                  │              │
│         └─────────────────┼──────────────────┘              │
│                           │                                 │
└───────────────────────────┼─────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              INTELLIGENT ROUTING LAYER                      │
│  - Route based on intent + context                          │
│  - Parallel tool execution where possible                  │
└───────────────────────────┬─────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Knowledge    │   │ Vehicle      │   │ Contact      │
│ Retrieval    │   │ Search       │   │ Collection   │
│ (RAG)        │   │              │   │              │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              PARALLEL REASONING LAYER                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Intent       │  │ Structure    │  │ Coverage     │    │
│  │ Analyzer     │  │ Planner      │  │ Definer      │    │
│  │ (LLM)        │  │ (LLM)        │  │ (LLM)        │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                  │              │
│         └─────────────────┼──────────────────┘              │
│                           │                                 │
└───────────────────────────┼─────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              RESPONSE GENERATION LAYER                       │
│  - Assemble prompt from all reasoning outputs               │
│  - Generate structured response                            │
│  - Quality validation (LLM-based)                          │
│  - Tone validation (LLM-based)                              │
└───────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              POST-PROCESSING LAYER                           │
│  - Generate suggestions (parallel)                        │
│  - Format response                                          │
│  - Update state                                              │
│  - Save to database                                          │
└───────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    FINAL RESPONSE                            │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Key Design Principles

1. **LLM-First Decision Making**
   - All routing decisions made by LLM
   - All quality checks done by LLM
   - All intent classification by LLM
   - No hardcoded if/else logic

2. **Parallel Processing**
   - Independent operations run in parallel
   - Use ThreadPoolExecutor for concurrent LLM calls
   - Use asyncio for I/O-bound operations
   - Minimize sequential dependencies

3. **Quality Assurance**
   - Multi-layer validation (LLM-based)
   - Fact-checking against knowledge base
   - Context verification
   - Tone and style validation

4. **Robust Error Handling**
   - Graceful degradation at every layer
   - Fallback mechanisms
   - Error recovery
   - User-friendly error messages

---

## 2. LangGraph Structure

### 2.1 Graph Definition

```python
from langgraph.graph import StateGraph, END
from typing import Literal

# Graph Structure
graph = StateGraph(AgentState)

# Nodes (in execution order)
graph.add_node("preprocess", preprocess_node)           # Parallel preprocessing
graph.add_node("route", routing_node)                   # Intelligent routing
graph.add_node("knowledge", knowledge_retrieval_node)   # RAG search
graph.add_node("vehicle", vehicle_search_node)          # Vehicle search
graph.add_node("contact", contact_collection_node)     # Contact collection
graph.add_node("reason", reasoning_node)                # Parallel reasoning
graph.add_node("generate", response_generation_node)    # Response generation
graph.add_node("validate", validation_node)             # Quality validation
graph.add_node("postprocess", postprocess_node)         # Final processing
graph.add_node("final", final_node)                     # Response formatting

# Entry point
graph.set_entry_point("preprocess")

# Conditional edges
graph.add_conditional_edges(
    "preprocess",
    should_route_to_collection,  # LLM decision
    {
        "contact": "contact",
        "continue": "route"
    }
)

graph.add_conditional_edges(
    "route",
    route_decision,  # LLM decision
    {
        "knowledge": "knowledge",
        "vehicle": "vehicle",
        "direct": "reason"
    }
)

# Parallel execution: knowledge + vehicle can run simultaneously
graph.add_edge("knowledge", "reason")
graph.add_edge("vehicle", "reason")

# Sequential: reasoning → generation → validation (ONLY when RAG was used)
graph.add_edge("reason", "generate")
graph.add_conditional_edges(
    "generate",
    should_run_validation,  # checks state.used_rag
    {"validate": "validate", "skip": "postprocess"}
)

# Conditional: validation can loop back or continue
graph.add_conditional_edges(
    "validate",
    validation_decision,  # LLM decision
    {
        "retry": "generate",  # Regenerate if validation fails
        "continue": "postprocess"
    }
)

graph.add_edge("postprocess", "final")
graph.add_edge("final", END)
```

### 2.2 Node Execution Flow

```
START
  │
  ▼
preprocess (parallel: intent + contact + context)
  │
  ├─► contact_collection (if contact info detected)
  │   └─► END
  │
  └─► route (intelligent routing)
      │
      ├─► knowledge (RAG search)
      │   └─► reason
      │
      ├─► vehicle (vehicle search)
      │   └─► reason
      │
      └─► direct (no tools needed)
          └─► reason
              │
              ▼
          generate (response generation)
              │
              ▼
          validate (quality check)
              │
              ├─► retry (if validation fails)
              │   └─► generate
              │
              └─► postprocess (suggestions + formatting)
                  │
                  ▼
              final (response output)
                  │
                  ▼
              END
```

---

## 3. Node Design & Parallel Processing

### 3.1 Preprocess Node (Parallel Execution)

**Purpose:** Analyze user message in multiple dimensions simultaneously

**Parallel Operations:**
1. **Intent Classifier (LLM)**
   - Classify question type (domain, service_discovery, vehicle_search, contact_request, greeting, etc.)
   - Determine if RAG needed
   - Identify user intent (information_seeking, buying_intent, support_request)

2. **Contact Info Extractor (LLM-only)**
   - Extract name, email, phone from message (flexible formats, including comma-separated)
   - Strictly return only explicitly present details (no guessing)
   - Runs opportunistically when contact signals exist and is forced during contact/confirmation flows
   - Allows users to share contact details **any time** in the chat

3. **Context Analyzer (LLM)**
   - Analyze conversation history (last 3-4 messages)
   - Understand context of current message
   - Detect user corrections or clarifications
   - Identify what "yes" refers to

**Implementation:**
```python
def preprocess_node(state: AgentState) -> AgentState:
    """Parallel preprocessing of user message."""
    from concurrent.futures import ThreadPoolExecutor
    
    user_message = state.messages[-1]["content"]
    conversation_history = state.messages[-4:-1] if len(state.messages) > 1 else []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        # Parallel execution
        intent_future = executor.submit(classify_intent, user_message, conversation_history)
        contact_future = executor.submit(extract_contact_info, user_message)
        context_future = executor.submit(analyze_context, user_message, conversation_history)
        
        # Wait for all to complete
        intent_result = intent_future.result()
        contact_result = contact_future.result()
        context_result = context_future.result()
    
    # Update state
    state.question_type = intent_result["question_type"]
    state.rag_query = intent_result.get("rag_query")
    state.user_name = contact_result.get("name") or state.user_name
    state.user_email = contact_result.get("email") or state.user_email
    state.user_phone = contact_result.get("phone") or state.user_phone
    state.context_analysis = context_result
    
    return state
```

### 3.2 Routing Node (LLM Decision)

**Purpose:** Intelligently route to appropriate tools or direct response

**LLM Decision:**
- Analyze intent + context + available tools
- Decide: knowledge_search, vehicle_search, direct_response, contact_collection
- Consider conversation state and user needs

**Implementation:**
```python
def routing_node(state: AgentState) -> AgentState:
    """Intelligent routing based on LLM decision."""
    routing_prompt = f"""
    Analyze the user's message and determine the best action:
    
    User Message: {state.messages[-1]["content"]}
    Intent: {state.question_type}
    Context: {state.context_analysis}
    Available Tools: knowledge_search, vehicle_search
    
    Decide which tool to use or if direct response is appropriate.
    Return JSON: {{"action": "knowledge"|"vehicle"|"direct", "reason": "..."}}
    """
    
    decision = llm_call(routing_prompt, response_format="json_object")
    state.next_action = decision["action"]
    state.routing_reason = decision["reason"]
    
    return state
```

### 3.3 Knowledge Retrieval Node (RAG)

**Purpose:** Search knowledge base for relevant information

**Optimization (current V2):**
- **Single-shot retrieval per message** (one query per user message)
- Keep top-K chunks and pass to generation
- Track a `used_rag` flag in state so validation only runs when RAG was used

**Implementation (current V2):**
```python
def knowledge_retrieval_node(state: AgentState) -> AgentState:
    base_query = state.rag_query or state.messages[-1]["content"]
    results = search_knowledge_base(base_query, top_k=RAG_TOP_K)
    state.rag_context = results
    state.knowledge_results = results
    state.used_rag = True
    return state
```

### 3.4 Reasoning Node (Parallel Execution)

**Purpose:** Multi-agent reasoning for high-quality answers

**Parallel Agents:**
1. **Intent Analyzer (LLM)**
   - Deep analysis of user question
   - Identify required depth and scope
   - Determine answer structure needs

2. **Structure Planner (LLM)**
   - Plan answer structure (bullets, sections, lifecycle)
   - Determine optimal length
   - Order information for clarity

3. **Coverage Definer (LLM)**
   - Define what MUST be included
   - Identify financial, operational, experience dimensions
   - Ensure completeness

**Implementation:**
```python
def reasoning_node(state: AgentState) -> AgentState:
    """Parallel multi-agent reasoning."""
    from concurrent.futures import ThreadPoolExecutor
    
    user_question = state.messages[-1]["content"]
    rag_context = state.rag_context
    conversation_history = state.messages[-4:-1]
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        # Parallel reasoning
        intent_future = executor.submit(
            analyze_intent_deep, user_question, rag_context, conversation_history
        )
        structure_future = executor.submit(
            plan_structure, user_question, state.question_type
        )
        coverage_future = executor.submit(
            define_coverage, user_question, rag_context, state.question_type
        )
        
        intent_analysis = intent_future.result()
        structure_plan = structure_future.result()
        coverage_plan = coverage_future.result()
    
    # Combine reasoning outputs
    state.reasoning_output = {
        "intent": intent_analysis,
        "structure": structure_plan,
        "coverage": coverage_plan
    }
    
    return state
```

### 3.5 Response Generation Node

**Purpose:** Generate high-quality response using all reasoning outputs

**Process:**
1. Assemble comprehensive prompt from reasoning outputs
2. Include RAG context, conversation history, user info
3. Generate structured response
4. Apply formatting rules

**Implementation:**
```python
def response_generation_node(state: AgentState) -> AgentState:
    """Generate response using all reasoning outputs."""
    reasoning = state.reasoning_output
    rag_context = state.rag_context
    user_question = state.messages[-1]["content"]
    
    # Assemble comprehensive prompt
    generation_prompt = assemble_generation_prompt(
        user_question=user_question,
        rag_context=rag_context,
        intent_analysis=reasoning["intent"],
        structure_plan=reasoning["structure"],
        coverage_plan=reasoning["coverage"],
        user_name=state.user_name,
        conversation_history=state.messages[-4:-1],
        system_prompt=build_system_prompt(state)
    )
    
    # Generate response
    response = llm_call(generation_prompt, temperature=0.7, max_tokens=2000)
    
    state.draft_response = response
    state.last_assistant_message = response
    
    return state
```

### 3.6 Validation Node (LLM-Based Quality Check)

**Purpose:** Validate response quality using LLM **only for RAG-backed answers**

**Validation Checks (Parallel):**
1. **Fact Checker (LLM)**
   - Verify all facts against RAG context
   - Check for hallucinations
   - Ensure accuracy

2. **Completeness Checker (LLM)**
   - Verify all required information included
   - Check coverage against plan
   - Ensure no missing critical details

3. **Tone & Style Validator (LLM)**
   - Check Australian accent usage
   - Verify positive language
   - Ensure professional tone

**Implementation:**
```python
def validation_node(state: AgentState) -> AgentState:
    """Multi-layer LLM-based validation."""
    from concurrent.futures import ThreadPoolExecutor
    
    draft_response = state.draft_response
    rag_context = state.rag_context
    coverage_plan = state.reasoning_output["coverage"]
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        # Parallel validation
        fact_future = executor.submit(
            validate_facts, draft_response, rag_context
        )
        completeness_future = executor.submit(
            validate_completeness, draft_response, coverage_plan
        )
        tone_future = executor.submit(
            validate_tone, draft_response
        )
        
        fact_check = fact_future.result()
        completeness_check = completeness_future.result()
        tone_check = tone_future.result()
    
    # Combine validation results
    validation_result = {
        "fact_check": fact_check,
        "completeness": completeness_check,
        "tone": tone_check,
        "overall_valid": all([
            fact_check["valid"],
            completeness_check["valid"],
            tone_check["valid"]
        ])
    }
    
    state.validation_result = validation_result
    
    if not validation_result["overall_valid"]:
        # Generate improvement suggestions
        state.improvement_suggestions = generate_improvements(validation_result)
    
    return state
```

### 3.7 Postprocess Node (Parallel)

**Purpose:** Final processing and suggestion generation

**Parallel Operations:**
1. **Suggestion Generator (LLM)**
   - Generate contextual suggestions
   - Consider conversation flow
   - Include conversion actions

2. **Response Formatter**
   - Apply markdown formatting
   - Add source citations
   - Format for frontend

**Implementation:**
```python
def postprocess_node(state: AgentState) -> AgentState:
    """Final processing and formatting."""
    from concurrent.futures import ThreadPoolExecutor
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        suggestions_future = executor.submit(
            generate_suggestions,
            state.messages,
            state.last_assistant_message,
            state.question_type
        )
        formatting_future = executor.submit(
            format_response,
            state.draft_response,
            state.rag_context
        )
        
        suggestions = suggestions_future.result()
        formatted_response = formatting_future.result()
    
    state.suggestions = suggestions
    state.final_response = formatted_response
    
    return state
```

---

## 4. State Management

### 4.1 Enhanced State Definition

```python
@dataclass
class AgentState:
    """Enhanced state with all necessary fields."""
    
    # Core
    session_id: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    
    # User Information
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    step: str = "chatting"  # chatting, name, email, phone, confirmation, complete
    
    # Preprocessing Results
    question_type: Optional[str] = None
    rag_query: Optional[str] = None
    context_analysis: Optional[Dict] = None
    
    # Routing
    next_action: Optional[str] = None
    routing_reason: Optional[str] = None
    
    # Knowledge Retrieval
    rag_context: List[Dict] = field(default_factory=list)
    knowledge_results: List[Dict] = field(default_factory=list)
    
    # Reasoning
    reasoning_output: Optional[Dict] = None
    
    # Response Generation
    draft_response: Optional[str] = None
    final_response: Optional[str] = None
    
    # Validation
    validation_result: Optional[Dict] = None
    improvement_suggestions: Optional[List[str]] = None
    
    # Post-processing
    suggestions: List[str] = field(default_factory=list)
    
    # Flags
    should_ask_for_name: bool = False
    should_offer_team_connection: bool = False
    is_complete: bool = False
    needs_info: Optional[str] = None
    
    # Metadata
    last_activity: datetime = field(default_factory=datetime.now)
    error_count: int = 0
    retry_count: int = 0
```

### 4.2 State Persistence

- Save state after each node execution
- Persist to database for recovery
- Support state resumption
- Track state transitions

---

## 5. Quality Assurance System

### 5.1 Multi-Layer Validation

**Layer 1: Pre-Generation Validation**
- Validate RAG context relevance
- Check query quality
- Verify reasoning outputs

**Layer 2: Post-Generation Validation**
- Fact checking (LLM)
- Completeness checking (LLM)
- Tone validation (LLM)

**Layer 3: Final Validation**
- Overall quality assessment
- User experience check
- Compliance verification

### 5.2 Validation Prompts

**Fact Checker Prompt:**
```
You are a fact-checker. Verify the following response against the provided knowledge base context.

Response: {draft_response}
Knowledge Base Context: {rag_context}

Check:
1. Are all facts accurate according to the context?
2. Are there any hallucinations or made-up information?
3. Are all claims supported by the context?

Return JSON: {"valid": true/false, "issues": [...], "confidence": 0.0-1.0}
```

**Completeness Checker Prompt:**
```
You are a completeness checker. Verify the response covers all required information.

Response: {draft_response}
Required Coverage: {coverage_plan}
User Question: {user_question}

Check:
1. Are all required topics covered?
2. Is the answer complete for the user's question?
3. Are any critical details missing?

Return JSON: {"valid": true/false, "missing_topics": [...], "completeness_score": 0.0-1.0}
```

**Tone Validator Prompt:**
```
You are a tone validator. Check the response follows WhipSmart's tone guidelines.

Response: {draft_response}

Check:
1. Uses professional Australian accent naturally
2. Uses positive, respectful language
3. No negative phrases ("if you can't afford", etc.)
4. Professional but friendly tone

Return JSON: {"valid": true/false, "tone_issues": [...], "tone_score": 0.0-1.0}
```

### 5.3 Retry Mechanism

- If validation fails, generate improvement suggestions
- Regenerate response with improvements
- Maximum 2 retries to avoid loops
- **Current V2 guardrail:** retry only when **fact-check** fails (likely hallucination), not for generic completeness noise
- Log retry reasons for analysis

---

## 6. Intent Classification & Routing

### 6.1 Enhanced Intent Classification

**Classification Types:**
- `service_discovery` - "what are my options?", "what services do you offer?"
- `domain_question` - Questions about WhipSmart, leases, EVs, etc.
- `vehicle_search` - "find me a car", "show me EVs under $X"
- `contact_request` - User wants to connect with team
- `greeting` - Hi, hello, etc.
- `goodbye` - Thank you, goodbye, etc.
- `clarification_needed` - Unclear intent

**LLM-Based Classification:**
```python
def classify_intent(user_message: str, conversation_history: List) -> Dict:
    """LLM-based intent classification."""
    prompt = f"""
    Classify the user's message intent:
    
    Message: {user_message}
    Conversation History: {conversation_history}
    
    Classify as one of:
    - service_discovery: User asking about available services/options
    - domain_question: Questions about WhipSmart, leases, EVs, tax, etc.
    - vehicle_search: User wants to search for vehicles
    - contact_request: User wants to connect with team
    - greeting: Greetings, hello, hi
    - goodbye: Thank you, goodbye, done
    - clarification_needed: Unclear intent
    
    For service_discovery, also generate search query: "WhipSmart services features capabilities"
    For domain_question, generate optimized RAG query.
    
    Return JSON: {{
        "intent": "...",
        "rag_query": "...",
        "confidence": 0.0-1.0,
        "reasoning": "..."
    }}
    """
    
    return llm_call(prompt, response_format="json_object")
```

### 6.2 Service Discovery Handling

**Special Handling:**
- Recognize "what are my options?" as service discovery
- NOT assume lease-specific context
- Search knowledge base for services/features
- Provide structured list of available services

**Implementation:**
```python
def handle_service_discovery(state: AgentState) -> AgentState:
    """Handle service discovery queries."""
    # Force service discovery query
    service_query = "WhipSmart services features capabilities what we offer"
    
    # Search knowledge base
    results = search_knowledge_base(service_query)
    
    # Generate structured service list
    services_prompt = f"""
    Based on the knowledge base, list all WhipSmart services and features:
    
    Knowledge Base: {results}
    
    Provide a structured list of:
    - Vehicle search and browsing
    - Lease application process
    - Quote generation
    - Team consultation
    - Educational resources
    - Any other services mentioned
    
    Format as clear, structured list.
    """
    
    service_list = llm_call(services_prompt)
    state.final_response = service_list
    
    return state
```

---

## 7. Knowledge Retrieval System

### 7.1 Enhanced RAG Search

**Query Optimization:**
- Generate multiple query variations
- Search in parallel
- Combine and rank results
- Filter by relevance threshold

**Query Variations:**
```python
def generate_query_variations(base_query: str, question_type: str) -> List[str]:
    """Generate query variations for better retrieval."""
    variations = [base_query]
    
    if question_type == "service_discovery":
        variations.extend([
            "WhipSmart services",
            "WhipSmart features",
            "what does WhipSmart offer",
            "WhipSmart capabilities"
        ])
    elif question_type == "domain_question":
        # Generate focused variations
        variations.extend(generate_domain_variations(base_query))
    
    return variations
```

### 7.2 Result Ranking & Combination

- Rank by relevance score
- Remove duplicates
- Combine top results
- Ensure diversity of sources

---

## 8. Response Generation Pipeline

### 8.1 Prompt Assembly

**Comprehensive Prompt Structure:**
```
System Prompt:
- Role definition
- Tone guidelines
- Answer quality rules
- User personalization

Context:
- User question
- Conversation history
- RAG context
- User information (name, etc.)

Reasoning Outputs:
- Intent analysis
- Structure plan
- Coverage plan

Instructions:
- Generate response following structure plan
- Cover all topics in coverage plan
- Use RAG context accurately
- Apply tone guidelines
```

### 8.2 Response Formatting

- Apply markdown formatting
- Add source citations
- Structure according to plan
- Ensure proper line breaks

---

## 9. Data Collection & Lead Management

### 9.1 Contact Information Detection

**Detection Methods:**
1. **Regex Patterns** - Fast detection
2. **LLM Extraction** - Natural language parsing
3. **Context Analysis** - Understand intent

**Parallel Detection:**
```python
def extract_contact_info(user_message: str) -> Dict:
    """Extract contact info using regex + LLM."""
    from concurrent.futures import ThreadPoolExecutor
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        regex_future = executor.submit(extract_with_regex, user_message)
        llm_future = executor.submit(extract_with_llm, user_message)
        
        regex_result = regex_future.result()
        llm_result = llm_future.result()
    
    # Combine and validate
    return combine_and_validate(regex_result, llm_result)
```

### 9.2 Collection Flow

**LLM-Driven Flow:**
- LLM decides when to collect
- LLM determines what to ask next
- LLM validates collected info
- LLM handles corrections

**No Manual Logic:**
- All decisions through LLM
- Dynamic flow based on context
- Natural conversation flow

### 9.3 Submission Validation

**Pre-Submission Check:**
- Verify all fields collected
- Validate data format
- Check user confirmation
- Only submit when all validated

---

## 10. Error Handling & Recovery

### 10.1 Error Categories

1. **LLM Errors** - API failures, timeouts
2. **Tool Errors** - RAG search failures, vehicle search errors
3. **Validation Errors** - Quality check failures
4. **State Errors** - Invalid state transitions

### 10.2 Error Recovery

**Graceful Degradation:**
- Fallback to simpler flow
- Use cached results if available
- Provide helpful error messages
- Log errors for analysis

**Retry Logic:**
- Retry transient failures
- Exponential backoff
- Maximum retry limits
- User notification on persistent failures

---

## 11. Performance Optimization

### 11.1 Parallel Processing Opportunities

**Phase 1: Preprocessing (Parallel)**
- Intent classification
- Contact extraction
- Context analysis

**Phase 2: Knowledge Retrieval (Parallel)**
- Multiple query variations
- Multiple search strategies

**Phase 3: Reasoning (Parallel)**
- Intent analysis
- Structure planning
- Coverage definition

**Phase 4: Validation (Parallel)**
- Fact checking
- Completeness checking
- Tone validation

**Phase 5: Postprocessing (Parallel)**
- Suggestion generation
- Response formatting

### 11.2 Caching Strategy

- Cache RAG results for common queries
- Cache intent classifications
- Cache reasoning outputs
- Invalidate on knowledge base updates

### 11.3 Response Time Targets

- Preprocessing: < 2 seconds
- Knowledge retrieval: < 3 seconds
- Reasoning: < 4 seconds (parallel)
- Generation: < 3 seconds
- Validation: < 2 seconds (parallel)
- **Total: < 10-12 seconds**

---

## 12. Implementation Phases

### Phase 1: Foundation (Week 1-2)
- ✅ Enhanced state definition
- ✅ Basic graph structure
- ✅ Preprocess node with parallel execution
- ✅ Routing node with LLM decisions

### Phase 2: Core Functionality (Week 3-4)
- ✅ Knowledge retrieval with parallel queries
- ✅ Reasoning node with parallel agents
- ✅ Response generation
- ✅ Basic validation

### Phase 3: Quality Assurance (Week 5-6)
- ✅ Multi-layer validation system
- ✅ Retry mechanism
- ✅ Error handling
- ✅ Service discovery handling

### Phase 4: Advanced Features (Week 7-8)
- ✅ Contact collection flow
- ✅ Suggestion generation
- ✅ Performance optimization
- ✅ Caching implementation

### Phase 5: Testing & Refinement (Week 9-10)
- ✅ Comprehensive testing
- ✅ Performance tuning
- ✅ Bug fixes
- ✅ Documentation

---

## 13. Testing Strategy

### 13.1 Unit Tests
- Test each node independently
- Test parallel execution
- Test error handling
- Test state transitions

### 13.2 Integration Tests
- Test full graph execution
- Test tool integrations
- Test database operations
- Test HubSpot integration

### 13.3 Quality Tests
- Test answer accuracy
- Test service discovery
- Test contact collection
- Test validation system

### 13.4 Performance Tests
- Test response times
- Test parallel execution speedup
- Test concurrent requests
- Test caching effectiveness

### 13.5 Edge Case Tests
- Test ambiguous inputs
- Test error recovery
- Test state corruption
- Test concurrent modifications

---

## Implementation Checklist

### Core Infrastructure
- [x] Enhanced AgentState definition (incl. follow-up + counters + `used_rag`)
- [x] LangGraph structure setup (conditional validation; follow-up support)
- [x] Parallel execution framework
- [x] State persistence (Session conversation_data + Visitor contact fields)

### Nodes Implementation
- [x] Preprocess node (parallel + greeting bypass + contact capture anytime)
- [x] Routing node (LLM-based + greeting/direct guardrails)
- [x] Knowledge retrieval node (single-shot RAG)
- [x] Vehicle search node
- [x] Contact collection node (collect OR confirm/correct + complete)
- [x] Reasoning node (parallel)
- [x] Response generation node
- [x] Validation node (parallel; RAG-only; fact-check-based retries)
- [x] Postprocess node (formatting + suggestion bypass during follow-ups + team-connect follow-up)
- [x] Final node

### Quality Assurance
- [x] Fact checking validation
- [x] Completeness validation
- [x] Tone validation
- [x] Retry mechanism (max 2; fact-check driven)
- [x] Error recovery (guardrails + fallbacks)

### Features
- [x] Service discovery handling
- [x] Intent classification (incl. greetings/small-talk direct)
- [x] Contact extraction (LLM-only; capture anytime; Visitor persistence)
- [x] Suggestion generation (bypassed during follow-ups / info collection)
- [x] Response formatting

### Performance
- [ ] Parallel execution optimization
- [ ] Caching implementation
- [ ] Response time optimization
- [ ] Resource management

### Testing
- [ ] Unit tests
- [ ] Integration tests
- [ ] Quality tests
- [ ] Performance tests
- [ ] Edge case tests

---

## Success Metrics

1. **Accuracy**: > 95% correct answers (validated by LLM)
2. **Response Time**: < 12 seconds average
3. **Service Discovery**: 100% correct handling
4. **Contact Collection**: 100% accurate extraction
5. **Error Rate**: < 1% unhandled errors
6. **User Satisfaction**: High quality responses

---

## Next Steps

1. **Review and Approve Plan**
2. **Set Up Development Environment**
3. **Implement Phase 1 (Foundation)**
4. **Iterate Based on Testing**
5. **Deploy and Monitor**

---

## Conclusion

This implementation plan provides a comprehensive blueprint for building a robust, high-quality LangGraph agent that:
- Makes all decisions through LLM
- Uses parallel processing for speed
- Implements all required functionality
- Ensures answer quality through multi-layer validation
- Handles edge cases gracefully

The agent will be production-ready, scalable, and maintainable.
