"""
Validation prompts for LangGraph Agent V2.
"""
VALIDATION_PROMPTS = {
    "fact_check": """You are a fact-checker. Verify the following response against the provided knowledge base context.

Response: {draft_response}
Knowledge Base Context: {rag_context}

Check:
1. Are all facts accurate according to the context?
2. Are there any hallucinations or made-up information?
3. Are all claims supported by the context?

Return JSON: {{"valid": true/false, "issues": [...], "confidence": 0.0-1.0}}""",

    "completeness": """You are a completeness checker. Verify the response covers all required information.

Response: {draft_response}
Required Coverage: {coverage_plan}
User Question: {user_question}

Check:
1. Are all required topics covered?
2. Is the answer complete for the user's question?
3. Are any critical details missing?

Return JSON: {{"valid": true/false, "missing_topics": [...], "completeness_score": 0.0-1.0}}""",

    "tone": """You are a tone validator. Check the response follows WhipSmart's tone guidelines.

Response: {draft_response}

Check:
1. Uses professional Australian accent naturally
2. Uses positive, respectful language
3. No negative phrases ("if you can't afford", etc.)
4. Professional but friendly tone

Return JSON: {{"valid": true/false, "tone_issues": [...], "tone_score": 0.0-1.0}}"""
}
