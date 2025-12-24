"""
Knowledge Graph Extractor
Uses LLM to extract entities and relationships from document text.
Follows strict extraction rules: only explicit facts, no inference.
"""
import json
import logging
from typing import Dict, List, Optional
from openai import AzureOpenAI
from django.conf import settings

from .kg_schema import ALLOWED_NODE_TYPES, ALLOWED_RELATIONSHIP_TYPES

logger = logging.getLogger(__name__)


# CRITICAL: This prompt must be embedded EXACTLY as specified
# Note: Curly braces in JSON example are escaped to prevent format() errors
EXTRACTION_PROMPT = """You are a knowledge extraction engine.

Your task is to extract factual entities and relationships
from the provided document text and represent them as a knowledge graph.

MANDATORY RULES:
- Extract ONLY what is explicitly stated
- DO NOT infer, guess, or add external knowledge
- DO NOT generalise rules
- DO NOT paraphrase constraints
- If a relationship is unclear, EXCLUDE it

OUTPUT FORMAT (STRICT JSON ONLY):

{{
  "entities": [
    {{
      "id": "unique_id",
      "type": "NodeType",
      "name": "Exact phrase from text"
    }}
  ],
  "relationships": [
    {{
      "source": "entity_id",
      "target": "entity_id",
      "type": "RELATIONSHIP_TYPE",
      "evidence": "Exact sentence from document"
    }}
  ]
}}

ALLOWED NODE TYPES:
- Organisation
- Regulation
- FinancialConcept
- Product
- Process

ALLOWED RELATIONSHIP TYPES:
- GOVERNED_BY
- DEPENDS_ON
- INFLUENCED_BY
- CANNOT_BE_CHANGED
- APPLIES_TO
- MENTIONS

DOCUMENT TEXT:
{document_text}"""


def _get_openai_client() -> Optional[AzureOpenAI]:
    """Get Azure OpenAI client from settings."""
    try:
        endpoint = settings.AZURE_OPENAI_ENDPOINT
        api_key = settings.AZURE_OPENAI_API_KEY
        api_version = getattr(settings, 'AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
        
        if not endpoint or not api_key:
            logger.warning("Azure OpenAI credentials not configured")
            return None
        
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version
        )
    except Exception as e:
        logger.error(f"Error creating OpenAI client: {str(e)}")
        return None


def extract_kg_from_text(document_text: str, model: str = None) -> Dict[str, List]:
    """
    Extract knowledge graph entities and relationships from document text.
    
    Args:
        document_text: The text content to extract from
        model: Optional model name (defaults to settings)
        
    Returns:
        Dictionary with 'entities' and 'relationships' lists
        Returns empty lists on failure
    """
    if not document_text or not document_text.strip():
        logger.warning("Empty document text provided for KG extraction")
        return {"entities": [], "relationships": []}
    
    try:
        client = _get_openai_client()
        if not client:
            logger.error("OpenAI client not available for KG extraction")
            return {"entities": [], "relationships": []}
        
        # Use model from settings if not provided
        if not model:
            model = getattr(settings, 'AZURE_OPENAI_DEPLOYMENT_NAME', 'gpt-4')
        
        # Format prompt with document text
        prompt = EXTRACTION_PROMPT.format(document_text=document_text[:50000])  # Limit to 50k chars
        
        logger.info(f"Extracting KG from text (length: {len(document_text)}) using model: {model}")
        
        # Call LLM
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a knowledge extraction engine. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # Low temperature for factual extraction
            response_format={"type": "json_object"}  # Force JSON response
        )
        
        # Parse response
        content = response.choices[0].message.content
        result = json.loads(content)
        
        # Validate structure
        entities = result.get("entities", [])
        relationships = result.get("relationships", [])
        
        # Validate node types and relationship types
        validated_entities = []
        for entity in entities:
            if entity.get("type") in ALLOWED_NODE_TYPES:
                validated_entities.append(entity)
            else:
                logger.warning(f"Invalid node type: {entity.get('type')}, skipping")
        
        validated_relationships = []
        for rel in relationships:
            if rel.get("type") in ALLOWED_RELATIONSHIP_TYPES:
                validated_relationships.append(rel)
            else:
                logger.warning(f"Invalid relationship type: {rel.get('type')}, skipping")
        
        logger.info(f"Extracted {len(validated_entities)} entities and {len(validated_relationships)} relationships")
        
        return {
            "entities": validated_entities,
            "relationships": validated_relationships
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response from LLM: {str(e)}")
        return {"entities": [], "relationships": []}
    except Exception as e:
        logger.error(f"Error extracting KG from text: {str(e)}", exc_info=True)
        return {"entities": [], "relationships": []}

