"""
Knowledge Graph Schema Definitions
Defines strict node types and relationship types for the knowledge graph.
"""
from enum import Enum


class NodeType(str, Enum):
    """Strict node types allowed in the knowledge graph."""
    DOCUMENT = "Document"
    ORGANISATION = "Organisation"
    REGULATION = "Regulation"
    FINANCIAL_CONCEPT = "FinancialConcept"
    PRODUCT = "Product"
    PROCESS = "Process"


class RelationshipType(str, Enum):
    """Strict relationship types allowed in the knowledge graph."""
    GOVERNED_BY = "GOVERNED_BY"
    DEPENDS_ON = "DEPENDS_ON"
    INFLUENCED_BY = "INFLUENCED_BY"
    CANNOT_BE_CHANGED = "CANNOT_BE_CHANGED"
    APPLIES_TO = "APPLIES_TO"
    MENTIONS = "MENTIONS"


# Allowed node types for validation
ALLOWED_NODE_TYPES = [nt.value for nt in NodeType]

# Allowed relationship types for validation
ALLOWED_RELATIONSHIP_TYPES = [rt.value for rt in RelationshipType]

