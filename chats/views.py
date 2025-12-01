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
from .serializers import ChatMessageSerializer, SessionSerializer

logger = logging.getLogger(__name__)


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
    destroy=extend_schema(
        summary="Delete session",
        description="Delete a chat session and all associated messages.",
        tags=['Sessions'],
    ),
)
class SessionViewSet(viewsets.ModelViewSet):
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
    create=extend_schema(
        summary="Create new chat message",
        description="Create a new chat message in a session. session_id is required. Message is permanently stored.",
        tags=['Messages'],
    ),
    retrieve=extend_schema(
        summary="Get message details",
        description="Retrieve detailed information about a specific chat message.",
        tags=['Messages'],
    ),
    destroy=extend_schema(
        summary="Soft delete message",
        description="Soft delete a chat message (sets is_deleted flag).",
        tags=['Messages'],
    ),
)
class ChatMessageViewSet(viewsets.ModelViewSet):
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
        description="Send a chat message and receive a response. session_id is required. Response is returned as complete message.",
        request={
            'type': 'object',
            'properties': {
                'message': {'type': 'string', 'description': 'User message'},
                'session_id': {'type': 'string', 'description': 'Session ID (required)'}
            },
            'required': ['message', 'session_id']
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'response': {'type': 'string', 'description': 'Assistant response'},
                    'session_id': {'type': 'string'},
                    'message_id': {'type': 'string'},
                    'response_id': {'type': 'string'}
                }
            }
        },
        tags=['Messages'],
    )
    @action(detail=False, methods=['post'], url_path='chat')
    def chat(self, request):
        """
        Non-streaming chat endpoint.
        Receives user message and session_id, returns complete assistant response.
        Both messages are permanently stored.
        """
        message = request.data.get('message')
        session_id = request.data.get('session_id')
        
        if not message:
            return Response(
                {'error': 'message is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not session_id:
            return Response(
                {'error': 'session_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get or create session
        try:
            session = Session.objects.get(session_id=session_id)
        except Session.DoesNotExist:
            return Response(
                {'error': 'Session not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Store user message permanently
        user_message = ChatMessage.objects.create(
            session=session,
            message=message,
            role='user',
            metadata={}
        )
        
        # TODO: Integrate with your AI/LLM service here
        # For now, return a placeholder response
        assistant_response_text = f"Echo: {message}"  # Replace with actual AI response
        
        # Store assistant response permanently
        assistant_message = ChatMessage.objects.create(
            session=session,
            message=assistant_response_text,
            role='assistant',
            metadata={}
        )
        
        return Response({
            'response': assistant_response_text,
            'session_id': session_id,
            'message_id': str(user_message.id),
            'response_id': str(assistant_message.id)
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Streaming chat (SSE)",
        description="Send a chat message and receive streaming response via Server-Sent Events (SSE). session_id is required.",
        request={
            'type': 'object',
            'properties': {
                'message': {'type': 'string', 'description': 'User message'},
                'session_id': {'type': 'string', 'description': 'Session ID (required)'}
            },
            'required': ['message', 'session_id']
        },
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
            }
        },
        tags=['Messages'],
    )
    @action(detail=False, methods=['post'], url_path='chat/stream')
    def chat_stream(self, request):
        """
        Streaming chat endpoint using Server-Sent Events (SSE).
        Receives user message and session_id, streams assistant response.
        Both messages are permanently stored.
        """
        message = request.data.get('message')
        session_id = request.data.get('session_id')
        
        if not message:
            return Response(
                {'error': 'message is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not session_id:
            return Response(
                {'error': 'session_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get or create session
        try:
            session = Session.objects.get(session_id=session_id)
        except Session.DoesNotExist:
            return Response(
                {'error': 'Session not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Store user message permanently
        user_message = ChatMessage.objects.create(
            session=session,
            message=message,
            role='user',
            metadata={}
        )
        
        def generate_stream():
            """Generator function for SSE streaming."""
            full_response = ""
            
            # TODO: Integrate with your AI/LLM streaming service here
            # For now, simulate streaming with placeholder
            response_text = f"Echo: {message}"  # Replace with actual AI streaming
            
            # Simulate streaming by sending chunks
            words = response_text.split()
            for i, word in enumerate(words):
                full_response += word + " "
                chunk_data = {
                    'chunk': word + " ",
                    'done': False,
                    'message_id': str(user_message.id)
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
            
            # Send final chunk with done flag
            final_data = {
                'chunk': '',
                'done': True,
                'message_id': str(user_message.id)
            }
            yield f"data: {json.dumps(final_data)}\n\n"
            
            # Store complete assistant response permanently
            assistant_message = ChatMessage.objects.create(
                session=session,
                message=full_response.strip(),
                role='assistant',
                metadata={}
            )
            
            # Send response_id in final message
            response_id_data = {
                'chunk': '',
                'done': True,
                'message_id': str(user_message.id),
                'response_id': str(assistant_message.id)
            }
            yield f"data: {json.dumps(response_id_data)}\n\n"
        
        response = StreamingHttpResponse(
            generate_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
