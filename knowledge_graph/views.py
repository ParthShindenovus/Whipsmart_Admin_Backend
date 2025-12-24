"""
Knowledge Graph API Views
Provides endpoints for building and querying the knowledge graph.
"""
import logging
from rest_framework import views, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from django.utils import timezone

from core.views_base import StandardizedResponseMixin
from core.utils import success_response, error_response
from .kg_builder import build_kg_for_document
from .kg_query import get_entity, get_relationships, get_facts_by_type, get_document_graph
from .kg_storage import KGStorage

logger = logging.getLogger(__name__)


class BuildKGView(StandardizedResponseMixin, views.APIView):
    """
    Build or update Knowledge Graph for a document.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Build Knowledge Graph",
        description="Build or update the Knowledge Graph for a document. Extracts entities and relationships from document text and stores them locally.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'document_id': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'UUID of the document to build KG for'
                    }
                },
                'required': ['document_id']
            }
        },
        responses={
            200: {
                'description': 'KG build summary',
                'type': 'object',
                'properties': {
                    'nodes_created': {'type': 'integer'},
                    'edges_created': {'type': 'integer'}
                }
            }
        },
        tags=['Knowledge Graph']
    )
    def post(self, request):
        """Build KG for a document."""
        try:
            document_id = request.data.get('document_id')
            
            if not document_id:
                return error_response(
                    'document_id is required',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate document exists and user has access
            from knowledgebase.models import Document
            try:
                document = Document.objects.get(id=document_id)
                # Check user access (non-superusers can only access their own documents)
                if not request.user.is_superuser and document.uploaded_by != request.user:
                    return error_response(
                        'You do not have permission to access this document',
                        status_code=status.HTTP_403_FORBIDDEN
                    )
            except Document.DoesNotExist:
                return error_response(
                    f'Document {document_id} not found',
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Build KG (wrapped in try/catch for failure isolation)
            # Note: KG is built from original source file, not from structured Q&A text
            try:
                result = build_kg_for_document(str(document_id))
                message = 'Knowledge Graph built successfully from original source file'
                return success_response(
                    data=result,
                    message=message
                )
            except Exception as e:
                logger.error(f"Error building KG for document {document_id}: {str(e)}", exc_info=True)
                # Return success with zero counts (failure isolation)
                return success_response(
                    data={"nodes_created": 0, "edges_created": 0},
                    message='Knowledge Graph build completed with errors (see logs)'
                )
                
        except Exception as e:
            logger.error(f"Error in BuildKGView: {str(e)}", exc_info=True)
            return error_response(
                'An error occurred while building the Knowledge Graph',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class QueryKGView(StandardizedResponseMixin, views.APIView):
    """
    Query the Knowledge Graph.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Query Knowledge Graph",
        description="Query entities, relationships, or facts from the Knowledge Graph. Supported query types: 1) type=entity&name=X - Search entities by name, 2) type=relationships&entity_id=X - Get relationships for an entity, 3) type=facts&node_type=X or rel_type=Y - Get facts by type, 4) type=document&document_id=X - Get graph for a document.",
        tags=['Knowledge Graph']
    )
    def get(self, request):
        """Query KG by entity name, type, or document."""
        try:
            query_type = request.query_params.get('type', '').lower()
            name = request.query_params.get('name')
            entity_id = request.query_params.get('entity_id')
            node_type = request.query_params.get('node_type')
            rel_type = request.query_params.get('rel_type')
            document_id = request.query_params.get('document_id')
            
            # Handle entity queries
            if query_type == 'entity':
                if not name:
                    return error_response(
                        'Missing required parameter: name. Use type=entity&name=<entity_name>',
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                results = get_entity(name)
                return success_response(data={'entities': results})
            
            # Handle relationship queries
            elif query_type == 'relationships':
                if not entity_id:
                    return error_response(
                        'Missing required parameter: entity_id. Use type=relationships&entity_id=<entity_id>',
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                results = get_relationships(entity_id)
                return success_response(data={'relationships': results})
            
            # Handle facts queries
            elif query_type == 'facts':
                if not node_type and not rel_type:
                    return error_response(
                        'Missing required parameter: node_type or rel_type. Use type=facts&node_type=<type> or type=facts&rel_type=<type>',
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                results = get_facts_by_type(node_type, rel_type)
                return success_response(data={'facts': results})
            
            # Handle document queries
            elif query_type == 'document':
                if not document_id:
                    return error_response(
                        'Missing required parameter: document_id. Use type=document&document_id=<uuid>',
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                results = get_document_graph(document_id)
                return success_response(data=results)
            
            # No query type provided or invalid query type
            else:
                return error_response(
                    'Invalid or missing query type. Supported types: entity, relationships, facts, document. '
                    'Examples: ?type=entity&name=ResidualValue, ?type=relationships&entity_id=entity-123, '
                    '?type=facts&node_type=Regulation, ?type=document&document_id=doc-uuid',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error in QueryKGView: {str(e)}", exc_info=True)
            return error_response(
                f'An error occurred while querying the Knowledge Graph: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DeleteKGView(StandardizedResponseMixin, views.APIView):
    """
    Delete Knowledge Graph for a document.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Delete Knowledge Graph",
        description="Delete the Knowledge Graph (all nodes and edges) for a document.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'document_id': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'UUID of the document to delete KG for'
                    }
                },
                'required': ['document_id']
            }
        },
        responses={
            200: {
                'description': 'KG deletion summary',
                'type': 'object',
                'properties': {
                    'nodes_deleted': {'type': 'integer'},
                    'edges_deleted': {'type': 'integer'}
                }
            }
        },
        tags=['Knowledge Graph']
    )
    def delete(self, request):
        """Delete KG for a document."""
        try:
            document_id = request.data.get('document_id')
            
            if not document_id:
                return error_response(
                    'document_id is required',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate document exists and user has access
            from knowledgebase.models import Document
            try:
                document = Document.objects.get(id=document_id)
                # Check user access (non-superusers can only access their own documents)
                if not request.user.is_superuser and document.uploaded_by != request.user:
                    return error_response(
                        'You do not have permission to access this document',
                        status_code=status.HTTP_403_FORBIDDEN
                    )
            except Document.DoesNotExist:
                return error_response(
                    f'Document {document_id} not found',
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Delete KG (wrapped in try/catch for failure isolation)
            try:
                storage = KGStorage()
                result = storage.delete_document_graph(str(document_id))
                
                if result["nodes_deleted"] == 0 and result["edges_deleted"] == 0:
                    return success_response(
                        data=result,
                        message='No Knowledge Graph found for this document'
                    )
                
                return success_response(
                    data=result,
                    message=f'Knowledge Graph deleted successfully ({result["nodes_deleted"]} nodes, {result["edges_deleted"]} edges removed)'
                )
            except Exception as e:
                logger.error(f"Error deleting KG for document {document_id}: {str(e)}", exc_info=True)
                return error_response(
                    'An error occurred while deleting the Knowledge Graph',
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            logger.error(f"Error in DeleteKGView: {str(e)}", exc_info=True)
            return error_response(
                'An error occurred while deleting the Knowledge Graph',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ClearAllKGView(StandardizedResponseMixin, views.APIView):
    """
    Clear ALL Knowledge Graphs from Neo4j/SQLite.
    WARNING: This will delete all knowledge graph data!
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Clear All Knowledge Graphs",
        description="Delete ALL nodes and edges from the Knowledge Graph database. WARNING: This operation cannot be undone! Requires superuser permissions.",
        responses={
            200: {
                'description': 'Clear operation summary',
                'type': 'object',
                'properties': {
                    'nodes_deleted': {'type': 'integer'},
                    'edges_deleted': {'type': 'integer'}
                }
            },
            403: {
                'description': 'Forbidden - requires superuser permissions'
            }
        },
        tags=['Knowledge Graph']
    )
    def delete(self, request):
        """Clear all graphs from the knowledge graph database."""
        try:
            # Only allow superusers to clear all graphs
            if not request.user.is_superuser:
                return error_response(
                    'Only superusers can clear all knowledge graphs',
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # Clear all graphs
            try:
                storage = KGStorage()
                result = storage.clear_all_graphs()
                
                if result["nodes_deleted"] == 0 and result["edges_deleted"] == 0:
                    return success_response(
                        data=result,
                        message='Knowledge Graph database is already empty'
                    )
                
                return success_response(
                    data=result,
                    message=f'All Knowledge Graphs cleared successfully ({result["nodes_deleted"]} nodes, {result["edges_deleted"]} edges deleted)'
                )
            except Exception as e:
                logger.error(f"Error clearing all graphs: {str(e)}", exc_info=True)
                return error_response(
                    'An error occurred while clearing all Knowledge Graphs',
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            logger.error(f"Error in ClearAllKGView: {str(e)}", exc_info=True)
            return error_response(
                'An error occurred while clearing all Knowledge Graphs',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
