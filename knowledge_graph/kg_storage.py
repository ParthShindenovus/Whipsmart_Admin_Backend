"""
Knowledge Graph Storage
Stores knowledge graph using SQLite (default) or Neo4j (optional).
"""
import sqlite3
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from django.conf import settings

logger = logging.getLogger(__name__)


class KGStorage:
    """
    Storage for knowledge graph.
    Supports both SQLite (default) and Neo4j (when enabled).
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize KG storage.
        
        Args:
            db_path: Optional path to SQLite database. Defaults to knowledge_graph/kg.db
                     Ignored if USE_NEO4J is True
        """
        # Check if Neo4j is enabled
        use_neo4j = getattr(settings, 'USE_NEO4J', False)
        
        if use_neo4j:
            try:
                from .kg_storage_neo4j import KGStorageNeo4j
                self.storage = KGStorageNeo4j()
                self.use_neo4j = True
                logger.info("Using Neo4j for Knowledge Graph storage")
                return
            except Exception as e:
                logger.error(f"Failed to initialize Neo4j, falling back to SQLite: {str(e)}")
                # Fall through to SQLite
        
        # Use SQLite (default)
        if db_path is None:
            # Default to knowledge_graph/kg.db in project root
            base_dir = Path(settings.BASE_DIR)
            kg_dir = base_dir / "knowledge_graph"
            kg_dir.mkdir(exist_ok=True)
            db_path = str(kg_dir / "kg.db")
        
        self.db_path = db_path
        self.use_neo4j = False
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Nodes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entity_id, document_id)
                )
            """)
            
            # Edges table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kg_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    evidence TEXT,
                    document_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES kg_nodes(id),
                    FOREIGN KEY (target_id) REFERENCES kg_nodes(id)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_entity_id ON kg_nodes(entity_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_document_id ON kg_nodes(document_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON kg_nodes(type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON kg_nodes(name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON kg_edges(source_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON kg_edges(target_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_document_id ON kg_edges(document_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_type ON kg_edges(relationship_type)")
            
            conn.commit()
            conn.close()
            logger.info(f"Initialized KG database at {self.db_path}")
        except Exception as e:
            logger.error(f"Error initializing KG database: {str(e)}", exc_info=True)
            raise
    
    def insert_nodes(self, nodes: List[Dict], document_id: str) -> int:
        """
        Insert nodes into the knowledge graph.
        
        Args:
            nodes: List of node dictionaries with 'id', 'type', 'name'
            document_id: Document ID these nodes belong to
            
        Returns:
            Number of nodes inserted
        """
        if self.use_neo4j:
            return self.storage.insert_nodes(nodes, document_id)
        if not nodes:
            return 0
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            inserted = 0
            for node in nodes:
                entity_id = node.get("id")
                node_type = node.get("type")
                name = node.get("name")
                
                if not all([entity_id, node_type, name]):
                    logger.warning(f"Skipping invalid node: {node}")
                    continue
                
                # Create unique node ID: entity_id-document_id
                node_id = f"{entity_id}-{document_id}"
                
                try:
                    cursor.execute("""
                        INSERT OR REPLACE INTO kg_nodes (id, entity_id, type, name, document_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (node_id, entity_id, node_type, name, document_id))
                    inserted += 1
                except sqlite3.IntegrityError:
                    # Node already exists, skip
                    pass
            
            conn.commit()
            conn.close()
            logger.info(f"Inserted {inserted} nodes for document {document_id}")
            return inserted
            
        except Exception as e:
            logger.error(f"Error inserting nodes: {str(e)}", exc_info=True)
            return 0
    
    def insert_edges(self, edges: List[Dict], document_id: str, node_map: Dict[str, str]) -> int:
        """
        Insert edges into the knowledge graph.
        
        Args:
            edges: List of edge dictionaries with 'source', 'target', 'type', 'evidence'
            document_id: Document ID these edges belong to
            node_map: Mapping from entity_id to node_id (entity_id-document_id)
            
        Returns:
            Number of edges inserted
        """
        if self.use_neo4j:
            return self.storage.insert_edges(edges, document_id, node_map)
        if not edges:
            return 0
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            inserted = 0
            for edge in edges:
                source_entity_id = edge.get("source")
                target_entity_id = edge.get("target")
                rel_type = edge.get("type")
                evidence = edge.get("evidence", "")
                
                if not all([source_entity_id, target_entity_id, rel_type]):
                    logger.warning(f"Skipping invalid edge: {edge}")
                    continue
                
                # Map entity IDs to node IDs
                source_node_id = node_map.get(source_entity_id) if source_entity_id else None
                target_node_id = node_map.get(target_entity_id) if target_entity_id else None
                
                if not source_node_id or not target_node_id:
                    logger.warning(f"Could not find node IDs for edge: {edge}")
                    continue
                
                try:
                    cursor.execute("""
                        INSERT INTO kg_edges (source_id, target_id, relationship_type, evidence, document_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (source_node_id, target_node_id, rel_type, evidence, document_id))
                    inserted += 1
                except sqlite3.IntegrityError as e:
                    logger.warning(f"Edge already exists or constraint violation: {e}")
            
            conn.commit()
            conn.close()
            logger.info(f"Inserted {inserted} edges for document {document_id}")
            return inserted
            
        except Exception as e:
            logger.error(f"Error inserting edges: {str(e)}", exc_info=True)
            return 0
    
    def get_entity_by_name(self, name: str) -> List[Dict]:
        """
        Query entities by name (case-insensitive partial match).
        
        Args:
            name: Entity name to search for
            
        Returns:
            List of matching entities
        """
        if self.use_neo4j:
            return self.storage.get_entity_by_name(name)
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, entity_id, type, name, document_id, created_at
                FROM kg_nodes
                WHERE LOWER(name) LIKE LOWER(?)
            """, (f"%{name}%",))
            
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error querying entity by name: {str(e)}", exc_info=True)
            return []
    
    def get_relationships(self, entity_id: str) -> List[Dict]:
        """
        Get all relationships for an entity.
        
        Args:
            entity_id: Node ID (entity_id-document_id format)
            
        Returns:
            List of relationships
        """
        if self.use_neo4j:
            return self.storage.get_relationships(entity_id)
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT e.id, e.source_id, e.target_id, e.relationship_type, e.evidence, 
                       e.document_id, e.created_at,
                       s.name as source_name, t.name as target_name
                FROM kg_edges e
                JOIN kg_nodes s ON e.source_id = s.id
                JOIN kg_nodes t ON e.target_id = t.id
                WHERE e.source_id = ? OR e.target_id = ?
            """, (entity_id, entity_id))
            
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error querying relationships: {str(e)}", exc_info=True)
            return []
    
    def get_facts_by_type(self, node_type: Optional[str] = None, rel_type: Optional[str] = None) -> List[Dict]:
        """
        Get facts filtered by node type or relationship type.
        
        Args:
            node_type: Filter by node type
            rel_type: Filter by relationship type
            
        Returns:
            List of facts (nodes and/or relationships)
        """
        if self.use_neo4j:
            return self.storage.get_facts_by_type(node_type, rel_type)
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            results = []
            
            if node_type:
                cursor.execute("""
                    SELECT id, entity_id, type, name, document_id, created_at
                    FROM kg_nodes
                    WHERE type = ?
                """, (node_type,))
                results.extend([dict(row) for row in cursor.fetchall()])
            
            if rel_type:
                cursor.execute("""
                    SELECT e.id, e.source_id, e.target_id, e.relationship_type, e.evidence,
                           e.document_id, e.created_at,
                           s.name as source_name, t.name as target_name
                    FROM kg_edges e
                    JOIN kg_nodes s ON e.source_id = s.id
                    JOIN kg_nodes t ON e.target_id = t.id
                    WHERE e.relationship_type = ?
                """, (rel_type,))
                results.extend([dict(row) for row in cursor.fetchall()])
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error querying facts by type: {str(e)}", exc_info=True)
            return []
    
    def get_document_graph(self, document_id: str) -> Dict:
        """
        Get all nodes and edges for a document.
        
        Args:
            document_id: Document ID
            
        Returns:
            Dictionary with 'nodes' and 'edges' lists
        """
        if self.use_neo4j:
            return self.storage.get_document_graph(document_id)
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get nodes
            cursor.execute("""
                SELECT id, entity_id, type, name, document_id, created_at
                FROM kg_nodes
                WHERE document_id = ?
            """, (document_id,))
            nodes = [dict(row) for row in cursor.fetchall()]
            
            # Get edges
            cursor.execute("""
                SELECT e.id, e.source_id, e.target_id, e.relationship_type, e.evidence,
                       e.document_id, e.created_at,
                       s.name as source_name, t.name as target_name
                FROM kg_edges e
                JOIN kg_nodes s ON e.source_id = s.id
                JOIN kg_nodes t ON e.target_id = t.id
                WHERE e.document_id = ?
            """, (document_id,))
            edges = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            return {"nodes": nodes, "edges": edges}
            
        except Exception as e:
            logger.error(f"Error querying document graph: {str(e)}", exc_info=True)
            return {"nodes": [], "edges": []}
    
    def delete_document_graph(self, document_id: str) -> Dict[str, int]:
        """
        Delete all nodes and edges for a document.
        
        Args:
            document_id: Document ID
            
        Returns:
            Dictionary with 'nodes_deleted' and 'edges_deleted' counts
        """
        if self.use_neo4j:
            return self.storage.delete_document_graph(document_id)
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get counts before deletion
            cursor.execute("SELECT COUNT(*) FROM kg_nodes WHERE document_id = ?", (document_id,))
            nodes_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM kg_edges WHERE document_id = ?", (document_id,))
            edges_count = cursor.fetchone()[0]
            
            # Delete edges first (to avoid foreign key constraint violations)
            cursor.execute("DELETE FROM kg_edges WHERE document_id = ?", (document_id,))
            
            # Delete nodes
            cursor.execute("DELETE FROM kg_nodes WHERE document_id = ?", (document_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Deleted {nodes_count} nodes and {edges_count} edges for document {document_id}")
            return {
                "nodes_deleted": nodes_count,
                "edges_deleted": edges_count
            }
        except Exception as e:
            logger.error(f"Error deleting document graph: {str(e)}", exc_info=True)
            return {"nodes_deleted": 0, "edges_deleted": 0}
    
    def clear_all_graphs(self) -> Dict[str, int]:
        """
        Delete ALL nodes and edges from the knowledge graph.
        WARNING: This will delete all data in the knowledge graph!
        
        Returns:
            Dictionary with 'nodes_deleted' and 'edges_deleted' counts
        """
        if self.use_neo4j:
            return self.storage.clear_all_graphs()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get counts before deletion
            cursor.execute("SELECT COUNT(*) FROM kg_nodes")
            nodes_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM kg_edges")
            edges_count = cursor.fetchone()[0]
            
            # Delete all edges first (to avoid foreign key constraint violations)
            cursor.execute("DELETE FROM kg_edges")
            
            # Delete all nodes
            cursor.execute("DELETE FROM kg_nodes")
            
            conn.commit()
            conn.close()
            
            logger.info(f"Cleared all graphs: {nodes_count} nodes and {edges_count} edges deleted")
            return {
                "nodes_deleted": nodes_count,
                "edges_deleted": edges_count
            }
        except Exception as e:
            logger.error(f"Error clearing all graphs: {str(e)}", exc_info=True)
            return {"nodes_deleted": 0, "edges_deleted": 0}

