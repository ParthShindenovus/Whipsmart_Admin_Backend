"""
Multi-Agent Reasoning Flow for Unified Agent
Implements parallel agent execution with orchestrator pattern for structured answer generation.
"""
import logging
from typing import Dict, List, Optional, Tuple
from openai import AzureOpenAI
from django.conf import settings

logger = logging.getLogger(__name__)


class MultiAgentReasoning:
    """
    Multi-Agent Reasoning System that orchestrates parallel agent execution
    to generate structured, comprehensive answers.
    
    Flow:
    1. Orchestrator receives user question
    2. Runs 4 agents in parallel:
       - Agent 1: Question Classifier
       - Agent 2: Context/RAG Retriever (already done by unified agent)
       - Agent 3: Structure & Length Planner
       - Agent 4: Must-Have Coverage Definer
    3. Prompt Assembler combines outputs
    4. Structured Response Agent generates final answer
    """
    
    def __init__(self, client: AzureOpenAI, model: str):
        self.client = client
        self.model = model
    
    def orchestrate(
        self,
        user_question: str,
        rag_context: List[Dict],
        conversation_history: List[Dict]
    ) -> str:
        """
        Main orchestrator that coordinates all agents and generates final answer.
        
        Args:
            user_question: The user's question
            rag_context: RAG context retrieved from knowledge base
            conversation_history: Last 3-4 messages for context
            
        Returns:
            Final structured answer
        """
        try:
            # Step 1: Run parallel agents (Agent 2 already has RAG context)
            logger.info("[MULTI-AGENT] Starting parallel agent execution...")
            
            agent1_result = self._agent1_classifier(user_question, conversation_history)
            agent3_result = self._agent3_structure_planner(user_question, agent1_result)
            agent4_result = self._agent4_coverage_definer(user_question, agent1_result, rag_context)
            
            logger.info("[MULTI-AGENT] Parallel agents completed")
            
            # Step 2: Assemble prompt with all agent outputs
            assembled_prompt = self._assemble_prompt(
                user_question=user_question,
                rag_context=rag_context,
                classifier_output=agent1_result,
                structure_output=agent3_result,
                coverage_output=agent4_result,
                conversation_history=conversation_history
            )
            
            # Step 3: Generate structured response (draft)
            draft_answer = self._generate_structured_response(assembled_prompt)
            
            # Step 4: Validate coverage (quality gate)
            logger.info("[MULTI-AGENT] Validating draft answer...")
            validation_result = self._agent5_coverage_validator(
                user_question=user_question,
                draft_answer=draft_answer,
                coverage_output=agent4_result,
                rag_context=rag_context
            )
            
            # Step 5: Apply fixes if needed
            if validation_result.get('status') == 'APPROVED':
                logger.info("[MULTI-AGENT] Draft answer approved")
                final_answer = draft_answer
            else:
                logger.info("[MULTI-AGENT] Fixes required, regenerating answer...")
                # Regenerate with fixes
                fix_instructions = validation_result.get('fix_required', '')
                final_answer = self._apply_fixes(
                    draft_answer=draft_answer,
                    fix_instructions=fix_instructions,
                    assembled_prompt=assembled_prompt
                )
            
            logger.info("[MULTI-AGENT] Final answer generated")
            return final_answer
            
        except Exception as e:
            logger.error(f"[MULTI-AGENT] Error in orchestration: {str(e)}", exc_info=True)
            # Fallback to simple answer
            return self._fallback_answer(user_question, rag_context)
    
    def _agent1_classifier(
        self,
        user_question: str,
        conversation_history: List[Dict]
    ) -> Dict:
        """
        Agent 1: Question Classifier
        Determines question type, domain, and complexity level.
        """
        prompt = f"""Analyze the following user question and classify it.

USER QUESTION: {user_question}

CONVERSATION CONTEXT (last 3-4 messages):
{self._format_conversation_history(conversation_history)}

TASK: Classify this question and provide structured metadata.

Provide your analysis in this exact format:
QUESTION_TYPE: [informational|risk|decision-support|operational|marketing]
PRIMARY_DOMAIN: [EV|leasing|finance|general|other]
COMPLEXITY_LEVEL: [low|medium|high]
INTENT: [Brief description of what the user is really asking]
KEY_TOPICS: [List 3-5 key topics this question touches on]

Be concise and accurate."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a question classification agent. Analyze questions and provide structured metadata."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=300
            )
            
            result_text = response.choices[0].message.content.strip()
            return self._parse_classifier_output(result_text)
            
        except Exception as e:
            logger.error(f"[MULTI-AGENT] Agent 1 error: {str(e)}")
            return {
                "question_type": "informational",
                "domain": "general",
                "complexity": "medium",
                "intent": user_question,
                "key_topics": []
            }
    
    def _agent3_structure_planner(
        self,
        user_question: str,
        classifier_output: Dict
    ) -> Dict:
        """
        Agent 3: Structure & Length Planner
        Decides answer structure, length, and ordering.
        """
        question_type = classifier_output.get("question_type", "informational")
        complexity = classifier_output.get("complexity", "medium")
        
        prompt = f"""Plan the structure and length for answering this question.

USER QUESTION: {user_question}

QUESTION CLASSIFICATION:
- Type: {question_type}
- Complexity: {complexity}
- Domain: {classifier_output.get('domain', 'general')}

TASK: Determine the optimal answer structure and length.

CRITICAL: Prefer SHORT or MEDIUM length answers. Only use "detailed" for highly complex questions.
- Most questions should be "short" (2-4 key points, concise)
- Complex questions can be "medium" (4-6 key points, structured)
- Only use "detailed" for very complex multi-part questions

Provide your plan in this exact format:
REQUIRED_LENGTH: [short|medium|detailed] (prefer short, use medium sparingly, detailed rarely)
BEST_STRUCTURE: [bullets|sections|lifecycle-stages|mixed]
ORDERING: [Describe the logical order of ideas for clarity and impact]
SECTION_BREAKDOWN: [List 2-4 main sections/points that should be covered - keep it concise]

Ensure structure matches question type and complexity. Keep answers concise and focused."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a structure planning agent. Plan answer structure and length."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=400
            )
            
            result_text = response.choices[0].message.content.strip()
            return self._parse_structure_output(result_text)
            
        except Exception as e:
            logger.error(f"[MULTI-AGENT] Agent 3 error: {str(e)}")
            return {
                "length": "medium",
                "structure": "bullets",
                "ordering": "logical flow",
                "sections": []
            }
    
    def _agent4_coverage_definer(
        self,
        user_question: str,
        classifier_output: Dict,
        rag_context: List[Dict]
    ) -> Dict:
        """
        Agent 4: Must-Have Coverage Definer (STRICT MODE)
        Identifies mandatory topics, risks, and coverage requirements.
        Does NOT write prose - only defines required coverage.
        """
        context_summary = self._summarize_rag_context(rag_context)
        domain = classifier_output.get('domain', 'general')
        is_ev_related = 'ev' in user_question.lower() or 'electric' in user_question.lower() or domain == 'ev'
        
        ev_checklist_section = ""
        if is_ev_related:
            ev_checklist_section = """
EV OWNERSHIP — CORE COVERAGE CHECKLIST:
When the question relates to EV ownership, ensure coverage includes **as many of the following as are supported by context**:
1. Charging support (e.g. home charging)
2. Incentives, rebates, or cost benefits
3. Maintenance or running cost support
4. Pricing transparency or simplicity (e.g. bundled fees)
5. Digital tools or ease of management (if mentioned in context)
6. Upgrade, resale, or exit flexibility (if mentioned)
7. Customer support or guidance model
8. Sustainability or tax advantages (ONLY if explicitly supported)

Only include items that are explicitly supported by the provided context."""
        
        prompt = f"""You are Agent 4 — MUST-HAVE COVERAGE DEFINER (STRICT MODE).

You are responsible for defining what MUST appear in the final answer.
You do NOT write prose.
You only define required coverage based on the question and provided context.

USER QUESTION: {user_question}

QUESTION CLASSIFICATION:
- Type: {classifier_output.get('question_type', 'informational')}
- Domain: {classifier_output.get('domain', 'general')}
- Complexity: {classifier_output.get('complexity', 'medium')}

AVAILABLE CONTEXT:
{context_summary}

HARD REALITY CONSTRAINT (MANDATORY):
Only include:
- Capabilities explicitly supported by the provided context
- Services that exist today
- Benefits that can be delivered immediately

Do NOT:
- Invent features
- Add future plans or innovations
- Add speculative capabilities
- Add "nice-to-have" items not present in context

If unsure, EXCLUDE it.
{ev_checklist_section}

TASK: Define what MUST be covered in the answer based on the question and context.

Provide your coverage plan in this exact format:
MUST_INCLUDE: [List 2-4 core topics/items that MUST be included - only what's explicitly in context]
OPTIONAL: [List items that are optional - only if context supports them]
EXCLUDE: [List items to exclude: fluff, repetition, future features, invented capabilities, speculation]

Be strict and focused - only what exists today and is explicitly in the provided context."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are Agent 4 — MUST-HAVE COVERAGE DEFINER (STRICT MODE). You do NOT write prose. You only define required coverage based on the question and provided context. Be strict and focused - only what exists today and is explicitly in the provided context."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            return self._parse_coverage_output(result_text)
            
        except Exception as e:
            logger.error(f"[MULTI-AGENT] Agent 4 error: {str(e)}")
            return {
                "must_include": [],
                "optional": [],
                "exclude": []
            }
    
    def _assemble_prompt(
        self,
        user_question: str,
        rag_context: List[Dict],
        classifier_output: Dict,
        structure_output: Dict,
        coverage_output: Dict,
        conversation_history: List[Dict]
    ) -> str:
        """
        Prompt Assembler: Combines all agent outputs into a comprehensive prompt.
        """
        context_text = self._format_rag_context(rag_context)
        
        prompt = f"""You are Alex AI, WhipSmart's expert assistant. Generate a structured, comprehensive answer.

USER QUESTION: {user_question}

QUESTION CLASSIFICATION:
- Type: {classifier_output.get('question_type', 'informational')}
- Domain: {classifier_output.get('domain', 'general')}
- Complexity: {classifier_output.get('complexity', 'medium')}
- Intent: {classifier_output.get('intent', '')}
- Key Topics: {', '.join(classifier_output.get('key_topics', []))}

ANSWER STRUCTURE PLAN:
- Required Length: {structure_output.get('length', 'medium')}
- Best Structure: {structure_output.get('structure', 'bullets')}
- Ordering: {structure_output.get('ordering', 'logical flow')}
- Sections: {', '.join(structure_output.get('sections', []))}

MANDATORY COVERAGE REQUIREMENTS (STRICT MODE):
- MUST INCLUDE: {', '.join(coverage_output.get('must_include', [])) if coverage_output.get('must_include') else 'None specified'}
- OPTIONAL (only if context supports): {', '.join(coverage_output.get('optional', [])) if coverage_output.get('optional') else 'None'}
- EXCLUDE: {', '.join(coverage_output.get('exclude', [])) if coverage_output.get('exclude') else 'None'}

RELEVANT CONTEXT FROM KNOWLEDGE BASE:
{context_text}

CONVERSATION HISTORY (for context):
{self._format_conversation_history(conversation_history)}

TASK: Generate a single, polished, CONCISE answer that:
1. Follows the planned structure and length exactly (prefer short, use medium sparingly)
2. Includes ONLY mandatory coverage items that are explicitly in the provided context
3. Uses professional, clear, and concise language
4. Focuses on capabilities and outcomes that exist TODAY
5. Avoids repetition and filler
6. Applies Answer Density & Discipline: prefer concise high-value statements, avoid repetition, remove filler, each paragraph/bullet introduces distinct capability/outcome
7. Keeps the answer SHORT - aim for 2-4 key points for most questions, 4-6 for complex ones

ZIX GOLD STANDARD — STYLE & DISCIPLINE (MANDATORY):

STYLE PRINCIPLES:
- Concise and high-signal
- Each bullet or sentence introduces a DISTINCT capability or benefit
- No internal process explanations
- No roadmap or future vision unless explicitly asked
- Present-tense, confident delivery

STRUCTURE PRINCIPLES:
- Prefer bullets over long paragraphs
- Group related capabilities
- Avoid more than 6–8 bullets unless complexity requires it

LANGUAGE RULES:
- Customer-centric ("what this does for you")
- No hype
- No filler intros ("Great question!", "Let me explain")
- Strong, clean closing if appropriate

COMPRESSION RULE:
- If two sentences communicate similar value → Keep the stronger one → Remove the other

CRITICAL CONSTRAINTS:
- REALITY & SCOPE CONSTRAINT (MANDATORY):
  * Only include capabilities explicitly supported by provided context
  * Only include services that exist today
  * Only include benefits that can be delivered immediately
  * Do NOT invent future features, speculative innovations, roadmap items
  * Do NOT expand beyond the given context
  * Do NOT add "nice-to-have" services unless explicitly stated
  * If unsure, exclude it
- Do NOT mention internal agents or reasoning steps
- Do NOT reference this prompt or the multi-agent flow
- Output ONLY the final answer
- Keep answers SHORT and focused - most answers should be 2-4 bullet points or 2-3 short paragraphs
- Use markdown formatting: **bold** for emphasis, headings for sections, single \n for line breaks
- Use exactly 4 spaces for nested list indentation per CommonMark specification
- Use \n\n only when concluding/leaving a list
- Use positive, respectful language - reframe negative statements positively
- Professional Australian accent naturally (e.g., "no worries", "fair enough")

FINAL QUALITY CHECK:
- Does this fully answer the question concisely?
- Have I only included what's explicitly in the context?
- Have I avoided inventing features or future capabilities?
- Have I removed all redundancy and filler?
- Is every sentence/bullet adding distinct value?
- Is the answer appropriately short (2-4 points for most questions)?

Generate the answer now:"""

        return prompt
    
    def _generate_structured_response(self, assembled_prompt: str) -> str:
        """
        Structured Response Generator: Generates final answer using assembled prompt.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are Alex AI, WhipSmart's expert assistant with a professional Australian accent.
You generate clear, structured, CONCISE answers that fully address user questions.
You follow Answer Quality Layer guidelines: lifecycle coverage, concrete details, but keep answers SHORT.
You apply Answer Density & Discipline: concise high-value statements, no repetition, no filler.

ZIX GOLD STANDARD — STYLE & DISCIPLINE:
- Concise and high-signal; each bullet/sentence introduces DISTINCT capability or benefit
- No internal process explanations, no roadmap/future vision unless explicitly asked
- Present-tense, confident delivery
- Prefer bullets over paragraphs; group related capabilities; max 6-8 bullets unless complexity requires more
- Customer-centric language ("what this does for you"); no hype; no filler intros
- COMPRESSION RULE: If two sentences communicate similar value, keep the stronger one, remove the other

CRITICAL: REALITY & SCOPE CONSTRAINT - Only include capabilities/services/benefits explicitly in the provided context that exist today. Do NOT invent future features or expand beyond context."""
                    },
                    {"role": "user", "content": assembled_prompt}
                ],
                temperature=0.7,
                max_tokens=600  # Reduced for shorter, more concise answers
            )
            
            answer = response.choices[0].message.content.strip()
            return self._normalize_newlines(answer)
            
        except Exception as e:
            logger.error(f"[MULTI-AGENT] Response generation error: {str(e)}")
            raise
    
    def _agent5_coverage_validator(
        self,
        user_question: str,
        draft_answer: str,
        coverage_output: Dict,
        rag_context: List[Dict]
    ) -> Dict:
        """
        Agent 5: Coverage Validator (Quality Gate)
        Validates the drafted answer - does NOT rewrite, only checks for gaps.
        """
        must_include = coverage_output.get('must_include', [])
        exclude = coverage_output.get('exclude', [])
        context_summary = self._summarize_rag_context(rag_context)
        
        prompt = f"""You are the COVERAGE VALIDATOR AGENT (QUALITY GATE).

You are validating a drafted answer.
Your job is NOT to rewrite — only to check for gaps.

USER QUESTION: {user_question}

DRAFT ANSWER:
{draft_answer}

MUST INCLUDE ITEMS (from Agent 4):
{chr(10).join(f"- {item}" for item in must_include) if must_include else "- None specified"}

EXCLUDE ITEMS (from Agent 4):
{chr(10).join(f"- {item}" for item in exclude) if exclude else "- None specified"}

AVAILABLE CONTEXT:
{context_summary}

VALIDATION RULES:
Check whether the answer:
1. Fully addresses the user's question
2. Covers all MUST INCLUDE items defined by Agent 4
3. Avoids speculative or unsupported features
4. Avoids repetition or filler
5. Matches the intended length and structure (should be SHORT - 2-4 key points)

ACTION RULES:
- If ALL checks pass → approve silently
- If something is missing → instruct the final agent to ADD ONLY the missing item
- If something unsupported exists → instruct the final agent to REMOVE it

Do NOT introduce new ideas.
Do NOT expand scope.

Provide your validation result in this exact format:
STATUS: [APPROVED|FIX_REQUIRED]
FIX_REQUIRED: [If STATUS is FIX_REQUIRED, list specific missing items to ADD or unsupported items to REMOVE. Be specific and concise. If APPROVED, leave empty]"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are Agent 5 — COVERAGE VALIDATOR (QUALITY GATE). You validate drafted answers. You do NOT rewrite — only check for gaps. If fixes are needed, provide specific instructions."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=300
            )
            
            result_text = response.choices[0].message.content.strip()
            return self._parse_validation_output(result_text)
            
        except Exception as e:
            logger.error(f"[MULTI-AGENT] Agent 5 error: {str(e)}")
            # On error, approve the draft to avoid blocking
            return {"status": "APPROVED", "fix_required": ""}
    
    def _parse_validation_output(self, text: str) -> Dict:
        """Parse Agent 5 validation output."""
        result = {
            "status": "APPROVED",
            "fix_required": ""
        }
        
        lines = text.split('\n')
        for line in lines:
            line_upper = line.upper()
            if 'STATUS:' in line_upper:
                status = line.split(':', 1)[1].strip() if ':' in line else ''
                if 'APPROVED' in status.upper():
                    result["status"] = "APPROVED"
                elif 'FIX_REQUIRED' in status.upper() or 'FIX REQUIRED' in status.upper():
                    result["status"] = "FIX_REQUIRED"
            elif 'FIX_REQUIRED:' in line_upper or 'FIX REQUIRED:' in line_upper:
                fix_content = line.split(':', 1)[1].strip() if ':' in line else ''
                if fix_content:
                    result["fix_required"] = fix_content
        
        return result
    
    def _apply_fixes(
        self,
        draft_answer: str,
        fix_instructions: str,
        assembled_prompt: str
    ) -> str:
        """Apply fixes to the draft answer based on validation feedback."""
        fix_prompt = f"""You are Alex AI, WhipSmart's expert assistant.

DRAFT ANSWER:
{draft_answer}

VALIDATION FEEDBACK - FIXES REQUIRED:
{fix_instructions}

TASK: Apply ONLY the requested fixes to the draft answer:
- ADD only the missing items specified
- REMOVE only the unsupported items specified
- Do NOT introduce new ideas
- Do NOT expand scope
- Keep the answer SHORT and concise (2-4 key points)
- Maintain professional Australian accent
- Use markdown formatting: **bold** for emphasis, single \n for line breaks
- Use exactly 4 spaces for nested list indentation per CommonMark specification
- Use \n\n only when concluding/leaving a list

ZIX GOLD STANDARD — STYLE & DISCIPLINE (MANDATORY):
- Concise and high-signal; each bullet/sentence introduces DISTINCT capability or benefit
- No internal process explanations, no roadmap/future vision unless explicitly asked
- Present-tense, confident delivery
- Prefer bullets over paragraphs; group related capabilities; max 6-8 bullets unless complexity requires more
- Customer-centric language ("what this does for you"); no hype; no filler intros ("Great question!", "Let me explain")
- COMPRESSION RULE: If two sentences communicate similar value, keep the stronger one, remove the other

CRITICAL: REALITY & SCOPE CONSTRAINT
- Only include capabilities explicitly supported by provided context
- Only include services that exist today
- Only include benefits that can be delivered immediately
- Do NOT invent future features or expand beyond context

Generate the fixed answer now:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are Alex AI, WhipSmart's expert assistant with a professional Australian accent.
You apply fixes to answers based on validation feedback.
You ONLY add missing items or remove unsupported items - do NOT introduce new ideas or expand scope.
Keep answers SHORT and concise.

ZIX GOLD STANDARD — STYLE & DISCIPLINE:
- Concise and high-signal; each bullet/sentence introduces DISTINCT capability or benefit
- No internal process explanations, no roadmap/future vision unless explicitly asked
- Present-tense, confident delivery
- Prefer bullets over paragraphs; group related capabilities; max 6-8 bullets unless complexity requires more
- Customer-centric language ("what this does for you"); no hype; no filler intros
- COMPRESSION RULE: If two sentences communicate similar value, keep the stronger one, remove the other"""
                    },
                    {"role": "user", "content": fix_prompt}
                ],
                temperature=0.5,
                max_tokens=600
            )
            
            fixed_answer = response.choices[0].message.content.strip()
            return self._normalize_newlines(fixed_answer)
            
        except Exception as e:
            logger.error(f"[MULTI-AGENT] Error applying fixes: {str(e)}")
            # Return original draft if fix fails
            return draft_answer
    
    def _fallback_answer(self, user_question: str, rag_context: List[Dict]) -> str:
        """Fallback answer if multi-agent flow fails."""
        context_text = self._format_rag_context(rag_context)
        return f"""Based on the available information: {context_text[:500]}...

I apologize, but I encountered an issue processing your question. Please try rephrasing it, or I can connect you with our team for assistance."""
    
    # Helper methods for parsing and formatting
    
    def _parse_classifier_output(self, text: str) -> Dict:
        """Parse Agent 1 classifier output."""
        result = {
            "question_type": "informational",
            "domain": "general",
            "complexity": "medium",
            "intent": "",
            "key_topics": []
        }
        
        lines = text.split('\n')
        for line in lines:
            if 'QUESTION_TYPE:' in line:
                result["question_type"] = line.split(':', 1)[1].strip().lower()
            elif 'PRIMARY_DOMAIN:' in line:
                result["domain"] = line.split(':', 1)[1].strip().lower()
            elif 'COMPLEXITY_LEVEL:' in line:
                result["complexity"] = line.split(':', 1)[1].strip().lower()
            elif 'INTENT:' in line:
                result["intent"] = line.split(':', 1)[1].strip()
            elif 'KEY_TOPICS:' in line:
                topics = line.split(':', 1)[1].strip()
                result["key_topics"] = [t.strip() for t in topics.split(',') if t.strip()]
        
        return result
    
    def _parse_structure_output(self, text: str) -> Dict:
        """Parse Agent 3 structure planner output."""
        result = {
            "length": "medium",
            "structure": "bullets",
            "ordering": "logical flow",
            "sections": []
        }
        
        lines = text.split('\n')
        for line in lines:
            if 'REQUIRED_LENGTH:' in line:
                result["length"] = line.split(':', 1)[1].strip().lower()
            elif 'BEST_STRUCTURE:' in line:
                result["structure"] = line.split(':', 1)[1].strip().lower()
            elif 'ORDERING:' in line:
                result["ordering"] = line.split(':', 1)[1].strip()
            elif 'SECTION_BREAKDOWN:' in line:
                sections = line.split(':', 1)[1].strip()
                result["sections"] = [s.strip() for s in sections.split(',') if s.strip()]
        
        return result
    
    def _parse_coverage_output(self, text: str) -> Dict:
        """Parse Agent 4 coverage definer output (strict mode format)."""
        result = {
            "must_include": [],
            "optional": [],
            "exclude": []
        }
        
        lines = text.split('\n')
        current_section = None
        
        for line in lines:
            line_upper = line.upper()
            if 'MUST_INCLUDE:' in line_upper or 'MUST INCLUDE:' in line_upper:
                current_section = 'must_include'
                # Extract items after the colon
                content = line.split(':', 1)[1].strip() if ':' in line else ''
                if content:
                    # Handle both comma-separated and dash/bullet formats
                    items = [item.strip().lstrip('-').strip() for item in content.split(',') if item.strip()]
                    result["must_include"].extend(items)
            elif 'OPTIONAL:' in line_upper:
                current_section = 'optional'
                content = line.split(':', 1)[1].strip() if ':' in line else ''
                if content:
                    items = [item.strip().lstrip('-').strip() for item in content.split(',') if item.strip()]
                    result["optional"].extend(items)
            elif 'EXCLUDE:' in line_upper:
                current_section = 'exclude'
                content = line.split(':', 1)[1].strip() if ':' in line else ''
                if content:
                    items = [item.strip().lstrip('-').strip() for item in content.split(',') if item.strip()]
                    result["exclude"].extend(items)
            elif current_section and line.strip():
                # Continue parsing items in the current section (handle multi-line lists)
                if line.strip().startswith('-') or line.strip().startswith('*'):
                    item = line.strip().lstrip('-*').strip()
                    if item:
                        result[current_section].append(item)
        
        # Fallback: if old format detected, convert it
        if not result["must_include"] and ('MANDATORY_TOPICS:' in text.upper() or 'MANDATORY TOPICS:' in text.upper()):
            # Try to parse old format for backward compatibility
            for line in lines:
                if 'MANDATORY_TOPICS:' in line.upper() or 'MANDATORY TOPICS:' in line.upper():
                    topics = line.split(':', 1)[1].strip() if ':' in line else ''
                    result["must_include"] = [t.strip() for t in topics.split(',') if t.strip()]
                elif 'RISKS_EDGE_CASES:' in line.upper():
                    risks = line.split(':', 1)[1].strip() if ':' in line else ''
                    result["must_include"].extend([f"Risk: {r.strip()}" for r in risks.split(',') if r.strip()])
                elif 'FINANCIAL_CONSIDERATIONS:' in line.upper():
                    financial = line.split(':', 1)[1].strip() if ':' in line else ''
                    result["must_include"].extend([f"Financial: {f.strip()}" for f in financial.split(',') if f.strip()])
                elif 'OPERATIONAL_CONSIDERATIONS:' in line.upper():
                    operational = line.split(':', 1)[1].strip() if ':' in line else ''
                    result["must_include"].extend([f"Operational: {o.strip()}" for o in operational.split(',') if o.strip()])
                elif 'AVOID:' in line.upper():
                    avoid = line.split(':', 1)[1].strip() if ':' in line else ''
                    result["exclude"] = [a.strip() for a in avoid.split(',') if a.strip()]
        
        return result
    
    def _format_rag_context(self, rag_context: List[Dict]) -> str:
        """Format RAG context for prompts."""
        if not rag_context:
            return "No relevant context found."
        
        formatted = []
        for i, chunk in enumerate(rag_context[:4], 1):
            text = chunk.get('text', '')
            source = chunk.get('reference_url') or chunk.get('url') or chunk.get('document_title', '')
            score = chunk.get('score', 0.0)
            
            chunk_text = f"[Context {i}] (Relevance: {score:.2f})\n{text}"
            if source:
                chunk_text += f"\nSource: {source}"
            formatted.append(chunk_text)
        
        return "\n\n".join(formatted)
    
    def _summarize_rag_context(self, rag_context: List[Dict]) -> str:
        """Create a brief summary of RAG context for Agent 4."""
        if not rag_context:
            return "No context available."
        
        summaries = []
        for chunk in rag_context[:3]:
            text = chunk.get('text', '')[:200]
            summaries.append(f"- {text}...")
        
        return "\n".join(summaries)
    
    def _format_conversation_history(self, conversation_history: List[Dict]) -> str:
        """Format conversation history for prompts."""
        if not conversation_history:
            return "No previous conversation."
        
        formatted = []
        for msg in conversation_history[-3:]:  # Last 3 messages
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            formatted.append(f"{role.upper()}: {content}")
        
        return "\n".join(formatted)
    
    def _normalize_newlines(self, text: str) -> str:
        """Normalize newlines: preserve \n\n for list conclusions, normalize excessive ones."""
        import re
        # Normalize excessive newlines (3+ consecutive) to \n\n
        return re.sub(r'\n{3,}', '\n\n', text)

