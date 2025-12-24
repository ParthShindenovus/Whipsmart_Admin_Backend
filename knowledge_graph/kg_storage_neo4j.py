"""
Knowledge Graph Storage - Neo4j Implementation
Stores knowledge graph in Neo4j graph database.
Uses the newer driver.execute_query() API as per Neo4j 5.x documentation.
"""
import logging
from typing import Dict, List, Optional
from neo4j import GraphDatabase  # type: ignore
from django.conf import settings  # type: ignore

logger = logging.getLogger(__name__)


class KGStorageNeo4j:
    """Neo4j-based storage for knowledge graph using driver.execute_query() API."""
    
    def __init__(self):
        """Initialize Neo4j connection."""
        self.uri = settings.NEO4J_URI
        self.user = settings.NEO4J_USER
        self.password = settings.NEO4J_PASSWORD
        # Default database name (neo4j is the standard default)
        self.database = "neo4j"
        
        if not self.password:
            raise ValueError("NEO4J_PASSWORD must be set in settings")
        
        try:
            # Use context manager pattern as per documentation
            # For AuraDB (neo4j+s://), we need encrypted=True and trusted_certificates=True
            driver_kwargs = {
                'auth': (self.user, self.password)
            }
            
            # Add SSL/TLS parameters for secure connections (neo4j+s://)
            if self.uri.startswith('neo4j+s://') or self.uri.startswith('bolt+s://'):
                driver_kwargs['encrypted'] = True
                driver_kwargs['trusted_certificates'] = True
            
            self.driver = GraphDatabase.driver(self.uri, **driver_kwargs)
            # Verify connectivity
            self.driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {self.uri}")
            self._init_constraints()
        except Exception as e:
            logger.error(f"Error connecting to Neo4j: {str(e)}", exc_info=True)
            if hasattr(self, 'driver'):
                self.driver.close()
            raise
    
    def _init_constraints(self):
        """Initialize constraints and indexes in Neo4j."""
        try:
            # Create unique constraint on node ID
            self.driver.execute_query("""
                CREATE CONSTRAINT node_id_unique IF NOT EXISTS
                FOR (n:KGNode) REQUIRE n.id IS UNIQUE
            """, database_=self.database)
            
            # Create indexes for better query performance
            self.driver.execute_query(
                "CREATE INDEX node_entity_id IF NOT EXISTS FOR (n:KGNode) ON (n.entity_id)",
                database_=self.database
            )
            self.driver.execute_query(
                "CREATE INDEX node_document_id IF NOT EXISTS FOR (n:KGNode) ON (n.document_id)",
                database_=self.database
            )
            self.driver.execute_query(
                "CREATE INDEX node_type IF NOT EXISTS FOR (n:KGNode) ON (n.type)",
                database_=self.database
            )
            self.driver.execute_query(
                "CREATE INDEX node_name IF NOT EXISTS FOR (n:KGNode) ON (n.name)",
                database_=self.database
            )
            
            logger.info("Neo4j constraints and indexes initialized")
        except Exception as e:
            # Some constraints might already exist, that's okay
            logger.warning(f"Error initializing Neo4j constraints (may already exist): {str(e)}")
    
    def close(self):
        """Close Neo4j driver connection."""
        if hasattr(self, 'driver'):
            self.driver.close()
    
    def insert_nodes(self, nodes: List[Dict], document_id: str) -> int:
        """
        Insert nodes into the knowledge graph.
        
        Args:
            nodes: List of node dictionaries with 'id', 'type', 'name'
            document_id: Document ID these nodes belong to
            
        Returns:
            Number of nodes inserted
        """
        if not nodes:
            return 0
        
        try:
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
                
                # Use MERGE to create or update node
                records, summary, keys = self.driver.execute_query("""
                    MERGE (n:KGNode {id: $node_id})
                    SET n.entity_id = $entity_id,
                        n.type = $node_type,
                        n.name = $name,
                        n.document_id = $document_id,
                        n.created_at = datetime()
                    RETURN n
                """, 
                    node_id=node_id,
                    entity_id=entity_id,
                    node_type=node_type,
                    name=name,
                    document_id=document_id,
                    database_=self.database
                )
                
                if records:
                    inserted += 1
            
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
        if not edges:
            return 0
        
        try:
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
                
                # Create relationship with properties
                records, summary, keys = self.driver.execute_query("""
                    MATCH (source:KGNode {id: $source_id})
                    MATCH (target:KGNode {id: $target_id})
                    MERGE (source)-[r:RELATES_TO {
                        type: $rel_type,
                        document_id: $document_id,
                        evidence: $evidence,
                        created_at: datetime()
                    }]->(target)
                    RETURN r
                """,
                    source_id=source_node_id,
                    target_id=target_node_id,
                    rel_type=rel_type,
                    document_id=document_id,
                    evidence=evidence,
                    database_=self.database
                )
                
                if records:
                    inserted += 1
            
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
        try:
            records, summary, keys = self.driver.execute_query("""
                MATCH (n:KGNode)
                WHERE toLower(n.name) CONTAINS toLower($name)
                RETURN n.id as id, n.entity_id as entity_id, n.type as type, 
                       n.name as name, n.document_id as document_id, 
                       n.created_at as created_at
            """,
                name=name,
                database_=self.database
            )
            
            return [record.data() for record in records]
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
        try:
            records, summary, keys = self.driver.execute_query("""
                MATCH (source:KGNode {id: $entity_id})-[r:RELATES_TO]->(target:KGNode)
                RETURN source.id as source_id, target.id as target_id,
                       r.type as relationship_type, r.evidence as evidence,
                       r.document_id as document_id, r.created_at as created_at,
                       source.name as source_name, target.name as target_name
                UNION
                MATCH (source:KGNode)-[r:RELATES_TO]->(target:KGNode {id: $entity_id})
                RETURN source.id as source_id, target.id as target_id,
                       r.type as relationship_type, r.evidence as evidence,
                       r.document_id as document_id, r.created_at as created_at,
                       source.name as source_name, target.name as target_name
            """,
                entity_id=entity_id,
                database_=self.database
            )
            
            return [record.data() for record in records]
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
        try:
            results = []
            
            if node_type:
                records, summary, keys = self.driver.execute_query("""
                    MATCH (n:KGNode)
                    WHERE n.type = $node_type
                    RETURN n.id as id, n.entity_id as entity_id, n.type as type,
                           n.name as name, n.document_id as document_id,
                           n.created_at as created_at
                """,
                    node_type=node_type,
                    database_=self.database
                )
                results.extend([record.data() for record in records])
            
            if rel_type:
                records, summary, keys = self.driver.execute_query("""
                    MATCH (source:KGNode)-[r:RELATES_TO]->(target:KGNode)
                    WHERE r.type = $rel_type
                    RETURN source.id as source_id, target.id as target_id,
                           r.type as relationship_type, r.evidence as evidence,
                           r.document_id as document_id, r.created_at as created_at,
                           source.name as source_name, target.name as target_name
                """,
                    rel_type=rel_type,
                    database_=self.database
                )
                results.extend([record.data() for record in records])
            
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
        try:
            # Get nodes
            nodes_records, summary, keys = self.driver.execute_query("""
                MATCH (n:KGNode)
                WHERE n.document_id = $document_id
                RETURN n.id as id, n.entity_id as entity_id, n.type as type,
                       n.name as name, n.document_id as document_id,
                       n.created_at as created_at
            """,
                document_id=document_id,
                database_=self.database
            )
            nodes = [record.data() for record in nodes_records]
            
            # Get edges
            edges_records, summary, keys = self.driver.execute_query("""
                MATCH (source:KGNode)-[r:RELATES_TO]->(target:KGNode)
                WHERE r.document_id = $document_id
                RETURN source.id as source_id, target.id as target_id,
                       r.type as relationship_type, r.evidence as evidence,
                       r.document_id as document_id, r.created_at as created_at,
                       source.name as source_name, target.name as target_name
            """,
                document_id=document_id,
                database_=self.database
            )
            edges = [record.data() for record in edges_records]
            
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
        try:
            # First, get counts before deletion
            graph = self.get_document_graph(document_id)
            nodes_count = len(graph.get("nodes", []))
            edges_count = len(graph.get("edges", []))
            
            # Delete relationships first (to avoid constraint violations)
            records, summary, keys = self.driver.execute_query("""
                MATCH (source:KGNode)-[r:RELATES_TO]->(target:KGNode)
                WHERE r.document_id = $document_id
                DELETE r
                RETURN count(r) as deleted_count
            """,
                document_id=document_id,
                database_=self.database
            )
            
            # Delete nodes
            records, summary, keys = self.driver.execute_query("""
                MATCH (n:KGNode)
                WHERE n.document_id = $document_id
                DELETE n
                RETURN count(n) as deleted_count
            """,
                document_id=document_id,
                database_=self.database
            )
            
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
        try:
            # First, get counts before deletion
            nodes_records, summary, keys = self.driver.execute_query("""
                MATCH (n:KGNode)
                RETURN count(n) as node_count
            """, database_=self.database)
            nodes_count = nodes_records[0].data()['node_count'] if nodes_records else 0
            
            edges_records, summary, keys = self.driver.execute_query("""
                MATCH ()-[r:RELATES_TO]->()
                RETURN count(r) as edge_count
            """, database_=self.database)
            edges_count = edges_records[0].data()['edge_count'] if edges_records else 0
            
            # Delete all relationships first (to avoid constraint violations)
            self.driver.execute_query("""
                MATCH ()-[r:RELATES_TO]->()
                DELETE r
            """, database_=self.database)
            
            # Delete all nodes
            self.driver.execute_query("""
                MATCH (n:KGNode)
                DELETE n
            """, database_=self.database)
            
            logger.info(f"Cleared all graphs: {nodes_count} nodes and {edges_count} edges deleted")
            return {
                "nodes_deleted": nodes_count,
                "edges_deleted": edges_count
            }
        except Exception as e:
            logger.error(f"Error clearing all graphs: {str(e)}", exc_info=True)
            return {"nodes_deleted": 0, "edges_deleted": 0}