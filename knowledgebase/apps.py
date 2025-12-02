from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class KnowledgebaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'knowledgebase'
    
    def ready(self):
        """Initialize Pinecone connection at Django startup"""
        try:
            from knowledgebase.services.pinecone_service import initialize_pinecone
            initialize_pinecone()
            logger.info("Pinecone initialized at Django startup")
        except Exception as e:
            logger.warning(f"Failed to initialize Pinecone at startup: {str(e)}. It will be initialized on first use.")
