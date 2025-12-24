"""
Knowledge Graph Query Layer
Provides simple read APIs for querying the knowledge graph.
"""
import logging
from typing import Dict, List, Optional
from .kg_storage import KGStorage

logger = logging.getLogger(__name__)


def get_entity(name: str) -> List[Dict]:
    """
    Get entity by name (case-insensitive partial match).
    
    Args:
        name: Entity name to search for
        
    Returns:
        List of matching entities
    """
    try:
        storage = KGStorage()
        return storage.get_entity_by_name(name)
    except Exception as e:
        logger.error(f"Error querying entity '{name}': {str(e)}", exc_info=True)
        return []


def get_relationships(entity_id: str) -> List[Dict]:
    """
    Get all relationships for an entity.
    
    Args:
        entity_id: Node ID (entity_id-document_id format) or entity name
        
    Returns:
        List of relationships
    """
    try:
        storage = KGStorage()
        
        # If entity_id doesn't contain '-', it might be just an entity name
        # Try to find the node first
        if '-' not in entity_id:
            entities = storage.get_entity_by_name(entity_id)
            if entities:
                entity_id = entities[0]['id']
            else:
                return []
        
        return storage.get_relationships(entity_id)
    except Exception as e:
        logger.error(f"Error querying relationships for '{entity_id}': {str(e)}", exc_info=True)
        return []


def get_facts_by_type(node_type: str = None, rel_type: str = None) -> List[Dict]:
    """
    Get facts filtered by node type or relationship type.
    
    Args:
        node_type: Filter by node type (e.g., "Organisation", "Regulation")
        rel_type: Filter by relationship type (e.g., "GOVERNED_BY", "DEPENDS_ON")
        
    Returns:
        List of facts (nodes and/or relationships)
    """
    try:
        storage = KGStorage()
        return storage.get_facts_by_type(node_type, rel_type)
    except Exception as e:
        logger.error(f"Error querying facts by type: {str(e)}", exc_info=True)
        return []


def get_document_graph(document_id: str) -> Dict:
    """
    Get complete knowledge graph for a document.
    
    Args:
        document_id: Document UUID
        
    Returns:
        Dictionary with 'nodes' and 'edges' lists
    """
    try:
        storage = KGStorage()
        return storage.get_document_graph(str(document_id))
    except Exception as e:
        logger.error(f"Error querying document graph for '{document_id}': {str(e)}", exc_info=True)
        return {"nodes": [], "edges": []}

