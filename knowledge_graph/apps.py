"""
Django app configuration for knowledge_graph.
"""
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class KnowledgeGraphConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'knowledge_graph'
    verbose_name = 'Knowledge Graph'
    
    def ready(self):
        """Verify Neo4j connection at Django startup if enabled."""
        from django.conf import settings
        
        use_neo4j = getattr(settings, 'USE_NEO4J', False)
        if not use_neo4j:
            logger.info("Neo4j is disabled, using SQLite for Knowledge Graph storage")
            return
        
        try:
            from neo4j import GraphDatabase
            
            uri = getattr(settings, 'NEO4J_URI', 'bolt://localhost:7687')
            user = getattr(settings, 'NEO4J_USER', 'neo4j')
            password = getattr(settings, 'NEO4J_PASSWORD', '')
            
            # Debug prints
            print(f"[NEO4J DEBUG] URI: {uri}")
            print(f"[NEO4J DEBUG] USER: {user}")
            print(f"[NEO4J DEBUG] PASSWORD: {'***' if password else 'NOT SET'}")
            print(f"[NEO4J DEBUG] USE_NEO4J: {use_neo4j}")
            
            if not password:
                logger.warning("NEO4J_PASSWORD not set, Neo4j connection will fail. Falling back to SQLite.")
                return
            
            # Verify connectivity at startup
            print(f"[NEO4J DEBUG] Attempting to connect to {uri}...")
            
            # Add SSL/TLS parameters for secure connections (neo4j+s://)
            driver_kwargs = {'auth': (user, password)}
            if uri.startswith('neo4j+s://') or uri.startswith('bolt+s://'):
                driver_kwargs['encrypted'] = True
                driver_kwargs['trusted_certificates'] = True
                print(f"[NEO4J DEBUG] Using encrypted connection with trusted certificates")
            
            with GraphDatabase.driver(uri, **driver_kwargs) as driver:
                driver.verify_connectivity()
                logger.info(f"[OK] Neo4j connection verified successfully at {uri}")
                
        except Exception as e:
            logger.warning(
                f"Failed to verify Neo4j connection at startup: {str(e)}. "
                f"Knowledge Graph will fall back to SQLite. "
                f"Please check your NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD settings."
            )

