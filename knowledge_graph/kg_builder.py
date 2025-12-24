"""
Knowledge Graph Builder
Builds knowledge graph from documents by extracting text, running extraction, and storing results.
"""
import logging
from typing import Dict, List, Optional
from pathlib import Path
from django.conf import settings

from knowledgebase.services.document_processor import (
    get_file_path_from_url,
    extract_text_from_file
)
from .kg_extractor import extract_kg_from_text
from .kg_storage import KGStorage

logger = logging.getLogger(__name__)


def split_text_by_sections(text: str, max_section_size: int = 10000) -> List[str]:
    """
    Split text into logical sections for KG extraction.
    Uses paragraph breaks and size limits.
    
    Args:
        text: Full document text
        max_section_size: Maximum characters per section
        
    Returns:
        List of text sections
    """
    if not text or len(text) <= max_section_size:
        return [text] if text else []
    
    sections = []
    paragraphs = text.split('\n\n')  # Split by double newlines (paragraphs)
    
    current_section = ""
    for para in paragraphs:
        if len(current_section) + len(para) + 2 <= max_section_size:
            current_section += (para + "\n\n" if current_section else para)
        else:
            if current_section:
                sections.append(current_section.strip())
            current_section = para
    
    if current_section:
        sections.append(current_section.strip())
    
    return sections if sections else [text]


def deduplicate_entities(entities_list: List[List[Dict]]) -> List[Dict]:
    """
    Deduplicate entities across sections by name and type.
    
    Args:
        entities_list: List of entity lists from different sections
        
    Returns:
        Deduplicated list of entities
    """
    seen = {}
    deduplicated = []
    
    for entities in entities_list:
        for entity in entities:
            key = (entity.get("name", "").lower(), entity.get("type", ""))
            if key not in seen:
                seen[key] = entity
                deduplicated.append(entity)
    
    return deduplicated


def build_kg_for_document(document_id: str) -> Dict[str, int]:
    """
    Build knowledge graph for a document.
    
    Args:
        document_id: UUID of the document
        
    Returns:
        Dictionary with 'nodes_created' and 'edges_created' counts
        Returns zeros on failure
    """
    try:
        from knowledgebase.models import Document
        
        # Get document
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            logger.error(f"Document {document_id} not found")
            return {"nodes_created": 0, "edges_created": 0}
        
        # Get document text
        # PRIMARY: Use original source file (PDF, DOCX, TXT, HTML) - preferred for KG extraction
        # FALLBACK: Use structured_text_qa_url if original file not available
        text = None
        text_source = None
        
        # Try original file first (preferred method)
        if document.file_url:
            try:
                file_path = get_file_path_from_url(document.file_url)
                if file_path.exists():
                    text = extract_text_from_file(file_path, document.file_type)
                    if text:
                        text_source = "original_file"
                        logger.info(f"Using original file for document {document_id} - {len(text)} characters from {file_path}")
                    else:
                        logger.warning(f"No text extracted from original file for document {document_id}, will try structured Q&A file")
                else:
                    logger.warning(f"Original file not found for document {document_id}: {file_path}, will try structured Q&A file")
            except Exception as e:
                logger.warning(f"Could not extract text from original file for document {document_id}: {str(e)}, will try structured Q&A file", exc_info=True)
        
        # Fallback to structured_text_qa_url if original file not available or failed
        if not text and document.structured_text_qa_url:
            try:
                file_path = get_file_path_from_url(document.structured_text_qa_url)
                
                # If path doesn't exist, try alternative resolution for /docs/ paths
                if not file_path.exists():
                    from urllib.parse import urlparse, unquote
                    parsed_url = urlparse(document.structured_text_qa_url)
                    # Check if it's a /docs/ path (not in MEDIA_ROOT)
                    if parsed_url.path.startswith('/docs/'):
                        # Try resolving as absolute path from project root or docs folder
                        base_dir = Path(settings.BASE_DIR).parent  # Go up one level from project root
                        # Try both project root/docs and just /docs/ as absolute
                        alt_paths = [
                            base_dir / parsed_url.path.lstrip('/'),  # D:\Python\docs\extracted-docs\...
                            Path(parsed_url.path),  # /docs/extracted-docs/... (absolute)
                            Path(settings.BASE_DIR) / parsed_url.path.lstrip('/'),  # Project root/docs/...
                        ]
                        for alt_path in alt_paths:
                            if alt_path.exists():
                                file_path = alt_path
                                logger.info(f"Found structured_text_qa_url at alternative path: {file_path}")
                                break
                
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        text = f.read().strip()
                    if text:
                        text_source = "structured_text_qa_url"
                        logger.info(f"Using structured_text_qa_url (fallback) for document {document_id} - {len(text)} characters from {file_path}")
                    else:
                        logger.warning(f"structured_text_qa_url file exists but is empty for document {document_id}")
                else:
                    logger.warning(f"structured_text_qa_url file not found at {file_path} (or alternatives) for document {document_id}")
            except Exception as e:
                logger.warning(f"Could not load structured_text_qa_url for document {document_id}: {str(e)}", exc_info=True)
        
        # If still no text, return error
        if not text or not text.strip():
            logger.error(f"No text content found for document {document_id} (tried original file and structured Q&A file)")
            return {"nodes_created": 0, "edges_created": 0}
        
        # Split text into sections for processing
        sections = split_text_by_sections(text)
        logger.info(f"Split document {document_id} ({text_source}) into {len(sections)} sections for KG extraction")
        
        # Extract KG from each section
        all_entities = []
        all_relationships = []
        
        for idx, section in enumerate(sections):
            logger.info(f"Extracting KG from section {idx + 1}/{len(sections)} for document {document_id}")
            result = extract_kg_from_text(section)
            
            if result:
                all_entities.append(result.get("entities", []))
                all_relationships.extend(result.get("relationships", []))
        
        # Deduplicate entities
        entities = deduplicate_entities(all_entities)
        logger.info(f"Extracted {len(entities)} unique entities and {len(all_relationships)} relationships")
        
        # Store in KG database
        storage = KGStorage()
        
        # Insert nodes
        nodes_created = storage.insert_nodes(entities, str(document_id))
        
        # Create node map for edges (entity_id -> node_id)
        node_map = {}
        for entity in entities:
            entity_id = entity.get("id")
            if entity_id:
                node_id = f"{entity_id}-{document_id}"
                node_map[entity_id] = node_id
        
        # Insert edges
        edges_created = storage.insert_edges(all_relationships, str(document_id), node_map)
        
        logger.info(f"KG build complete for document {document_id}: {nodes_created} nodes, {edges_created} edges")
        
        return {
            "nodes_created": nodes_created,
            "edges_created": edges_created
        }
        
    except Exception as e:
        logger.error(f"Error building KG for document {document_id}: {str(e)}", exc_info=True)
        return {"nodes_created": 0, "edges_created": 0}

