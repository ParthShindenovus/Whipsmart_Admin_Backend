from rest_framework import viewsets, filters, status, views
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema_view, extend_schema
from django.http import StreamingHttpResponse
from django.utils import timezone
import json
import logging
from .models import ChatMessage, Session
from .serializers import ChatMessageSerializer, SessionSerializer, ChatRequestSerializer
from agents.graph import get_graph
from agents.session_manager import session_manager
from agents.state import AgentState
from core.views_base import StandardizedResponseMixin
from core.utils import success_response, error_response

logger = logging.getLogger(__name__)


def validate_session(session_id):
    """
    Validate that a session exists, is active, and not expired.
    
    Returns:
        tuple: (session_object, error_response) 
               If validation fails, returns (None, error_response)
               If validation succeeds, returns (session, None)
    """
    if not session_id:
        return None, error_response('session_id is required', status_code=status.HTTP_400_BAD_REQUEST)
    
    try:
        session = Session.objects.get(session_id=session_id)
    except Session.DoesNotExist:
        return None, error_response('Session not found', status_code=status.HTTP_404_NOT_FOUND)
    
    if not session.is_active:
        return None, error_response('Session is not active', status_code=status.HTTP_403_FORBIDDEN)
    
    if session.is_expired():
        return None, error_response('Session has expired', status_code=status.HTTP_403_FORBIDDEN)
    
    return session, None


@extend_schema_view(
    list=extend_schema(
        summary="List all chat sessions",
        description="Retrieve a list of all chat sessions. No authentication required. No user_id needed.",
        tags=['Sessions'],
    ),
    create=extend_schema(
        summary="Create new chat session",
        description="Create a new chat session. Session ID will be auto-generated if not provided. No user_id required.",
        tags=['Sessions'],
    ),
    retrieve=extend_schema(
        summary="Get session details",
        description="Retrieve detailed information about a specific chat session.",
        tags=['Sessions'],
    ),
    update=extend_schema(exclude=True),  # Hide update endpoint
    partial_update=extend_schema(exclude=True),  # Hide partial update endpoint
    destroy=extend_schema(
        summary="Delete session",
        description="Delete a chat session and all associated messages.",
        tags=['Sessions'],
    ),
)
class SessionViewSet(StandardizedResponseMixin, viewsets.ModelViewSet):
    """
    ViewSet for Session model.
    
    Manages chat sessions. Sessions are independent and do not require admin authentication or user_id.
    Provides CRUD operations: Create, Read, Delete, List.
    """
    queryset = Session.objects.all()
    serializer_class = SessionSerializer
    permission_classes = [AllowAny]  # Sessions are public, no admin required, no user_id needed
    search_fields = ['session_id', 'external_user_id']
    filterset_fields = ['is_active', 'external_user_id']
    ordering = ['-created_at']


@extend_schema_view(
    list=extend_schema(
        summary="List chat messages",
        description="Retrieve a list of chat messages. session_id is required as query parameter. No user_id needed.",
        tags=['Messages'],
    ),
    create=extend_schema(exclude=True),  # Hide standard create - use /chat or /chat/stream instead
    retrieve=extend_schema(
        summary="Get message details",
        description="Retrieve detailed information about a specific chat message.",
        tags=['Messages'],
    ),
    update=extend_schema(exclude=True),  # Messages cannot be updated
    partial_update=extend_schema(exclude=True),  # Messages cannot be updated
    destroy=extend_schema(
        summary="Soft delete message",
        description="Soft delete a chat message (sets is_deleted flag).",
        tags=['Messages'],
    ),
)
class ChatMessageViewSet(StandardizedResponseMixin, viewsets.ModelViewSet):
    """
    ViewSet for ChatMessage model.
    
    Manages chat messages within sessions. All messages must have session_id.
    Messages are permanently stored. No user_id required.
    """
    queryset = ChatMessage.objects.filter(is_deleted=False)
    serializer_class = ChatMessageSerializer
    permission_classes = [AllowAny]  # Chat messages are public, no user_id needed
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['session', 'role']
    search_fields = ['message']
    ordering = ['timestamp']
    
    def get_queryset(self):
        """Filter messages by session_id if provided in query params."""
        queryset = super().get_queryset()
        session_id = self.request.query_params.get('session_id')
        if session_id:
            try:
                session = Session.objects.get(session_id=session_id)
                queryset = queryset.filter(session=session)
            except Session.DoesNotExist:
                queryset = queryset.none()
        return queryset
    
    def perform_create(self, serializer):
        """Ensure session_id is provided and message is permanently stored."""
        # session_id is already validated in serializer
        serializer.save()
        # Message is automatically saved to database (permanent storage)
    
    def perform_destroy(self, instance):
        """Soft delete instead of hard delete."""
        instance.is_deleted = True
        instance.save()
    
    @extend_schema(
        summary="Non-streaming chat",
        description="Send a chat message and receive a response. session_id is required. Response is returned as complete message. Session ID must be valid, active, and not expired.",
        request=ChatRequestSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'response': {'type': 'string', 'description': 'Assistant response'},
                    'session_id': {'type': 'string'},
                    'message_id': {'type': 'string'},
                    'response_id': {'type': 'string'}
                }
            },
            400: {'description': 'Bad request - message or session_id missing'},
            403: {'description': 'Forbidden - session is inactive or expired'},
            404: {'description': 'Not found - session does not exist'}
        },
        tags=['Messages'],
    )
    @action(detail=False, methods=['post'], url_path='chat')
    def chat(self, request):
        """
        Non-streaming chat endpoint.
        Receives user message and session_id, returns complete assistant response.
        Both messages are permanently stored.
        Session ID is required and must be valid, active, and not expired.
        """
        message = request.data.get('message')
        session_id = request.data.get('session_id')
        
        if not message:
            return error_response('message is required', status_code=status.HTTP_400_BAD_REQUEST)
        
        # Validate session
        session, error_response = validate_session(session_id)
        if error_response:
            return error_response
        
        try:
            logger.info("=" * 80)
            logger.info(f"[AGENT] AGENT CALLED - Session: {session_id}")
            logger.info(f"[MSG] User Message: {message}")
            logger.info("=" * 80)
            
            # Save user message to database
            session_manager.save_user_message(session_id, message)
            
            # Get or create agent state from Django session
            agent_state = session_manager.get_or_create_agent_state(session_id)
            logger.info(f"[STATS] Loaded agent state with {len(agent_state.messages)} previous messages")
            
            # Add user message to agent state
            agent_state.messages.append({
                "role": "user",
                "content": message
            })
            
            # Get the compiled graph
            graph = get_graph()
            logger.info("[OK] Agent graph compiled and ready")
            
            # Invoke graph with state (convert to dict for LangGraph)
            state_dict = agent_state.to_dict()
            logger.info("[SYNC] Invoking agent graph...")
            final_state_dict = graph.invoke(state_dict)
            
            # Convert back to AgentState
            final_state = AgentState.from_dict(final_state_dict)
            
            # Extract final answer
            final_answer = ""
            for msg in reversed(final_state.messages):
                if msg.get("role") == "assistant":
                    final_answer = msg.get("content", "")
                    break
            
            if not final_answer:
                # Fallback: try to get from tool_result
                if isinstance(final_state.tool_result, dict) and final_state.tool_result.get("action") == "final":
                    final_answer = final_state.tool_result.get("answer", "I'm sorry, I couldn't generate a response.")
                else:
                    final_answer = "I'm sorry, I couldn't generate a response."
            
            logger.info("=" * 80)
            logger.info(f"[OK] FINAL ANSWER GENERATED:")
            logger.info(f"{final_answer}")
            logger.info("=" * 80)
            
            # Save agent state (saves assistant message to database)
            session_manager.save_agent_state(session_id, final_state)
            
            # Get the saved messages for response
            user_message = ChatMessage.objects.filter(
                session=session,
                role='user',
                is_deleted=False
            ).order_by('-timestamp').first()
            
            assistant_message = ChatMessage.objects.filter(
                session=session,
                role='assistant',
                is_deleted=False
            ).order_by('-timestamp').first()
            
            return success_response({
                'response': final_answer,
                'session_id': session_id,
                'message_id': str(user_message.id) if user_message else None,
                'response_id': str(assistant_message.id) if assistant_message else None
            })
            
        except Exception as e:
            logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
            return error_response(
                'An error occurred while processing your request. Please try again.',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        summary="Streaming chat (SSE)",
        description="Send a chat message and receive streaming response via Server-Sent Events (SSE). session_id is required. Session ID must be valid, active, and not expired.",
        request=ChatRequestSerializer,
        responses={
            200: {
                'description': 'Streaming response via SSE',
                'content': {
                    'text/event-stream': {
                        'schema': {
                            'type': 'string',
                            'example': 'data: {"chunk": "Hello", "done": false}\n\n'
                        }
                    }
                }
            },
            400: {'description': 'Bad request - message or session_id missing'},
            403: {'description': 'Forbidden - session is inactive or expired'},
            404: {'description': 'Not found - session does not exist'}
        },
        tags=['Messages'],
    )
    @action(detail=False, methods=['post'], url_path='chat/stream')
    def chat_stream(self, request):
        """
        Streaming chat endpoint using Server-Sent Events (SSE).
        Receives user message and session_id, streams assistant response.
        Both messages are permanently stored.
        Session ID is required and must be valid, active, and not expired.
        """
        message = request.data.get('message')
        session_id = request.data.get('session_id')
        
        if not message:
            return error_response('message is required', status_code=status.HTTP_400_BAD_REQUEST)
        
        # Validate session
        session, error_response = validate_session(session_id)
        if error_response:
            return error_response
        
        try:
            logger.info("=" * 80)
            logger.info(f"[AGENT] AGENT CALLED (STREAMING) - Session: {session_id}")
            logger.info(f"[MSG] User Message: {message}")
            logger.info("=" * 80)
            
            # Save user message to database
            session_manager.save_user_message(session_id, message)
            
            # Get user message ID for response
            user_message = ChatMessage.objects.filter(
                session=session,
                role='user',
                is_deleted=False
            ).order_by('-timestamp').first()
            
            def generate_stream():
                """Generator function for SSE streaming."""
                try:
                    # Get or create agent state from Django session
                    agent_state = session_manager.get_or_create_agent_state(session_id)
                    logger.info(f"[STATS] Loaded agent state with {len(agent_state.messages)} previous messages")
                    
                    # Add user message to agent state
                    agent_state.messages.append({
                        "role": "user",
                        "content": message
                    })
                    
                    # Get the compiled graph
                    graph = get_graph()
                    logger.info("[OK] Agent graph compiled and ready")
                    
                    # Invoke graph with state (convert to dict for LangGraph)
                    state_dict = agent_state.to_dict()
                    logger.info("[SYNC] Invoking agent graph...")
                    final_state_dict = graph.invoke(state_dict)
                    
                    # Convert back to AgentState
                    final_state = AgentState.from_dict(final_state_dict)
                    
                    # Extract final answer
                    final_answer = ""
                    for msg in reversed(final_state.messages):
                        if msg.get("role") == "assistant":
                            final_answer = msg.get("content", "")
                            break
                    
                    if not final_answer:
                        # Fallback: try to get from tool_result
                        if isinstance(final_state.tool_result, dict) and final_state.tool_result.get("action") == "final":
                            final_answer = final_state.tool_result.get("answer", "I'm sorry, I couldn't generate a response.")
                        else:
                            final_answer = "I'm sorry, I couldn't generate a response."
                    
                    logger.info("=" * 80)
                    logger.info(f"[OK] FINAL ANSWER GENERATED (STREAMING):")
                    logger.info(f"{final_answer}")
                    logger.info("=" * 80)
                    
                    # Stream the response word by word
                    words = final_answer.split()
                    full_response = ""
                    
                    for i, word in enumerate(words):
                        full_response += word + " "
                        chunk_data = {
                            'chunk': word + " ",
                            'done': False,
                            'message_id': str(user_message.id) if user_message else None
                        }
                        yield f"data: {json.dumps(chunk_data)}\n\n"
                    
                    # Send final chunk with done flag
                    final_data = {
                        'chunk': '',
                        'done': True,
                        'message_id': str(user_message.id) if user_message else None
                    }
                    yield f"data: {json.dumps(final_data)}\n\n"
                    
                    # Save agent state (saves assistant message to database)
                    session_manager.save_agent_state(session_id, final_state)
                    
                    # Get the saved assistant message for response_id
                    assistant_message = ChatMessage.objects.filter(
                        session=session,
                        role='assistant',
                        is_deleted=False
                    ).order_by('-timestamp').first()
                    
                    # Send response_id in final message
                    if assistant_message:
                        response_id_data = {
                            'chunk': '',
                            'done': True,
                            'message_id': str(user_message.id) if user_message else None,
                            'response_id': str(assistant_message.id)
                        }
                        yield f"data: {json.dumps(response_id_data)}\n\n"
                        
                except Exception as e:
                    logger.error(f"Error in streaming: {str(e)}", exc_info=True)
                    error_data = {
                        'chunk': '',
                        'done': True,
                        'error': 'An error occurred while processing your request.'
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"
            
            response = StreamingHttpResponse(
                generate_stream(),
                content_type='text/event-stream'
            )
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
            
        except Exception as e:
            logger.error(f"Error in chat_stream endpoint: {str(e)}", exc_info=True)
            return error_response(
                'An error occurred while processing your request. Please try again.',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
