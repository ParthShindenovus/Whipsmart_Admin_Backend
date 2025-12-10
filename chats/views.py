from rest_framework import viewsets, filters, status, views
from rest_framework.decorators import action, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.authentication import BaseAuthentication
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema_view, extend_schema
from django.http import StreamingHttpResponse, Http404
from django.utils import timezone
import json
import logging
from .models import ChatMessage, Session, Visitor
from .serializers import ChatMessageSerializer, SessionSerializer, ChatRequestSerializer, VisitorSerializer
from agents.graph import get_graph
from agents.session_manager import session_manager
from agents.state import AgentState
from core.views_base import StandardizedResponseMixin
from core.utils import success_response, error_response
from widget.authentication import APIKeyAuthentication
from widget.permissions import RequiresAPIKey


class NoAuthentication(BaseAuthentication):
    """
    Authentication class that does nothing - allows all requests without authentication.
    Used for public endpoints like session creation.
    
    Returns None to indicate no authentication was attempted.
    This prevents DRF from trying other authentication classes.
    """
    def authenticate(self, request):
        # Return None to indicate no authentication attempted
        # This prevents DRF from trying default authentication classes
        return None
    
    def authenticate_header(self, request):
        """
        Return None to indicate no authentication header is required.
        """
        return None

logger = logging.getLogger(__name__)


def validate_session(session_id):
    """
    Validate that a session exists, is active, and not expired.
    session_id is the UUID id of the Session (primary key).
    
    Returns:
        tuple: (session_object, error_response) 
               If validation fails, returns (None, error_response)
               If validation succeeds, returns (session, None)
    """
    if not session_id:
        return None, error_response('session_id is required', status_code=status.HTTP_400_BAD_REQUEST)
    
    try:
        # session_id is now the id (UUID primary key)
        session = Session.objects.get(id=session_id)
    except (Session.DoesNotExist, ValueError):
        return None, error_response('Session not found', status_code=status.HTTP_404_NOT_FOUND)
    
    if not session.is_active:
        return None, error_response('Session is not active', status_code=status.HTTP_403_FORBIDDEN)
    
    if session.is_expired():
        return None, error_response('Session has expired', status_code=status.HTTP_403_FORBIDDEN)
    
    return session, None


@extend_schema_view(
    list=extend_schema(
        summary="List all chat sessions",
        description="Retrieve a list of all chat sessions. No authentication required. Sessions are automatically associated with visitors.",
        tags=['Sessions'],
    ),
    create=extend_schema(
        summary="Create new chat session (STEP 2)",
        description="Create a new chat session. visitor_id is REQUIRED - must be created first via POST /api/chats/visitors/. Session ID will be auto-generated. No user_id required.",
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
    
    Manages chat sessions. visitor_id is REQUIRED - must be created first via POST /api/chats/visitors/.
    Sessions are independent and do not require admin authentication or user_id.
    
    FLOW:
    1. POST /api/chats/visitors/ to create visitor (returns visitor_id)
    2. POST /api/chats/sessions/ with visitor_id to create session (returns session_id)
    3. Use session_id and visitor_id to send chat messages
    
    Provides CRUD operations: Create, Read, Delete, List.
    """
    queryset = Session.objects.all()
    serializer_class = SessionSerializer
    authentication_classes = []  # No authentication - completely public endpoint (empty list disables all auth)
    permission_classes = [AllowAny]  # Sessions are public, no admin required, no user_id needed
    search_fields = ['external_user_id']
    filterset_fields = ['is_active', 'external_user_id', 'visitor']
    ordering = ['-created_at']
    
    def get_authenticators(self):
        """
        Override to return empty list - no authentication for session endpoints.
        This prevents DRF from using default authentication classes.
        """
        return []


@extend_schema_view(
    list=extend_schema(
        summary="List all visitors",
        description="Retrieve a list of all visitors. No authentication required.",
        tags=['Visitors'],
    ),
    create=extend_schema(
        summary="Create new visitor (STEP 1)",
        description="Create a new visitor. Visitor ID is auto-generated (UUID). No input required from client. This is the FIRST step - you must create a visitor before creating sessions or sending chat messages.",
        tags=['Visitors'],
    ),
    retrieve=extend_schema(
        summary="Get visitor details",
        description="Retrieve detailed information about a specific visitor, including all their sessions.",
        tags=['Visitors'],
    ),
    update=extend_schema(exclude=True),  # Hide update endpoint
    partial_update=extend_schema(exclude=True),  # Hide partial update endpoint
    destroy=extend_schema(exclude=True),  # Hide delete endpoint
)
class VisitorViewSet(StandardizedResponseMixin, viewsets.ModelViewSet):
    """
    ViewSet for Visitor model.
    
    Manages visitors. Visitor IDs are auto-generated UUIDs created by the backend.
    No input required from client - just POST to create a new visitor.
    
    FLOW: 
    1. POST /api/chats/visitors/ to create visitor (returns visitor_id)
    2. Use visitor_id to create sessions and send chat messages
    
    Provides operations: Create, Read, List, Validate.
    """
    queryset = Visitor.objects.all()
    serializer_class = VisitorSerializer
    authentication_classes = []  # No authentication - completely public endpoint
    permission_classes = [AllowAny]  # Visitors are public, no admin required
    ordering = ['-created_at']
    
    def get_authenticators(self):
        """
        Override to return empty list - no authentication for visitor endpoints.
        This prevents DRF from using default authentication classes.
        """
        return []
    
    def create(self, request, *args, **kwargs):
        """
        Create a new visitor.
        Visitor ID is auto-generated - no input required from client.
        This is STEP 1 - create visitor before creating sessions.
        """
        serializer = self.get_serializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        visitor = serializer.save()
        return success_response(
            VisitorSerializer(visitor).data,
            message="Visitor created successfully. Use this visitor_id to create sessions and send chat messages.",
            status_code=status.HTTP_201_CREATED
        )
    
    @extend_schema(
        summary="Validate visitor ID",
        description="Check if a visitor ID exists and is valid. Returns visitor details if valid, error if not found.",
        tags=['Visitors'],
        responses={200: VisitorSerializer, 404: None}
    )
    @action(detail=True, methods=['get'], url_path='validate')
    def validate_visitor(self, request, pk=None):
        """
        Validate that a visitor ID exists.
        This endpoint can be used to check if a visitor_id is valid before creating sessions.
        """
        try:
            visitor = self.get_object()
            visitor.update_last_seen()
            return success_response(
                VisitorSerializer(visitor).data,
                message="Visitor ID is valid"
            )
        except (Visitor.DoesNotExist, Http404):
            return error_response(
                f"Visitor with ID '{pk}' does not exist. Please create a visitor first via POST /api/chats/visitors/",
                status_code=status.HTTP_404_NOT_FOUND
            )


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
    queryset = ChatMessage.objects.filter(is_deleted=False, role__in=['user', 'assistant'])
    serializer_class = ChatMessageSerializer
    authentication_classes = []  # Default: no auth (for list/retrieve endpoints)
    permission_classes = [AllowAny]  # Default: allow any (for list/retrieve endpoints)
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['role']  # Only allow filtering by role, session_id handled in get_queryset
    search_fields = ['message']
    ordering = ['timestamp']
    pagination_class = None  # Disable pagination to return all messages for a session
    
    def get_authenticators(self):
        """
        Override to return empty list for list/retrieve endpoints.
        Chat endpoints (chat, chat/stream) override this with APIKeyAuthentication via decorator.
        """
        # For list/retrieve, no authentication needed
        return []
    
    def get_queryset(self):
        """
        Filter messages by session_id if provided in query params.
        Only returns user and assistant messages (excludes system messages).
        """
        queryset = super().get_queryset()
        
        # Support both 'session_id' and 'session' query parameters
        session_id = self.request.query_params.get('session_id') or self.request.query_params.get('session')
        
        if session_id:
            try:
                # Validate session exists first
                session = Session.objects.get(id=session_id)
                
                # Filter directly by session_id (UUID) - use ForeignKey lookup
                # Use session__id to filter by the id field of the related Session
                queryset = queryset.filter(session__id=session_id)
                
                # Log for debugging
                total_count = queryset.count()
                user_count = queryset.filter(role='user').count()
                assistant_count = queryset.filter(role='assistant').count()
                logger.info(f"[MESSAGES] Found {total_count} messages for session_id: {session_id} (user: {user_count}, assistant: {assistant_count})")
                
                # Verify messages exist in DB directly (bypass queryset filters)
                all_db_messages = ChatMessage.objects.filter(
                    session__id=session_id
                ).order_by('timestamp')
                
                db_total = all_db_messages.count()
                db_not_deleted = all_db_messages.filter(is_deleted=False).count()
                db_user_assistant = all_db_messages.filter(is_deleted=False, role__in=['user', 'assistant']).count()
                
                logger.info(f"[MESSAGES] DB Stats for session_id {session_id}: Total={db_total}, NotDeleted={db_not_deleted}, User/Assistant={db_user_assistant}")
                
                # If we're missing messages, log them for debugging
                if db_user_assistant > total_count:
                    logger.warning(f"[MESSAGES] Missing {db_user_assistant - total_count} messages! Checking what's filtered out...")
                    deleted_messages = all_db_messages.filter(is_deleted=True).count()
                    system_messages = all_db_messages.filter(role='system').count()
                    logger.warning(f"[MESSAGES] Filtered out: deleted={deleted_messages}, system={system_messages}")
                
            except Session.DoesNotExist:
                logger.warning(f"[MESSAGES] Session not found: {session_id}")
                queryset = queryset.none()
            except (ValueError, Exception) as e:
                logger.warning(f"[MESSAGES] Invalid session_id format or error filtering: {session_id}, error: {str(e)}")
                queryset = queryset.none()
        else:
            # No session_id provided - log for debugging
            logger.debug("[MESSAGES] No session_id provided in query params - returning all messages")
        return queryset
    
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific message by ID.
        Provides helpful error message if session ID is used instead of message ID.
        """
        lookup_value = kwargs.get('pk')
        
        # Check if it might be a session ID instead of a message ID
        if lookup_value:
            try:
                session = Session.objects.get(id=lookup_value)
                # It's a session ID - provide helpful error message
                messages_count = ChatMessage.objects.filter(session=session, is_deleted=False).count()
                return error_response(
                    f'The provided ID is a Session ID, not a Message ID. '
                    f'To retrieve messages for this session, use: GET /api/chats/messages/?session_id={lookup_value}. '
                    f'This session has {messages_count} message(s).',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            except (Session.DoesNotExist, ValueError):
                pass  # Not a session ID, continue with normal lookup
        
        # Try normal retrieval
        try:
            return super().retrieve(request, *args, **kwargs)
        except Exception:
            # Message not found - provide helpful error message
            return error_response(
                'Message not found. Please provide a valid message ID. '
                'To list all messages for a session, use: GET /api/chats/messages/?session_id=<session_id>',
                status_code=status.HTTP_404_NOT_FOUND
            )
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
        summary="Non-streaming chat (STEP 3)",
        description="Send a chat message and receive a response. Requires API key authentication (X-API-Key header or Authorization: Bearer <api-key>). visitor_id and session_id are REQUIRED. Response is returned as complete message. Session ID must be valid, active, and not expired. Visitor ID must match the session's visitor.",
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
            400: {'description': 'Bad request - message, session_id, or visitor_id missing'},
            403: {'description': 'Forbidden - session is inactive or expired, or visitor_id mismatch'},
            404: {'description': 'Not found - session or visitor does not exist'}
        },
        tags=['Messages'],
    )
    @action(detail=False, methods=['post'], url_path='chat', 
            authentication_classes=[APIKeyAuthentication],
            permission_classes=[RequiresAPIKey])
    def chat(self, request):
        """
        Non-streaming chat endpoint.
        Receives user message, session_id, and visitor_id, returns complete assistant response.
        Both messages are permanently stored.
        visitor_id and session_id are REQUIRED. Session ID must be valid, active, and not expired.
        Visitor ID must match the session's visitor.
        """
        message = request.data.get('message')
        session_id = request.data.get('session_id')
        visitor_id = request.data.get('visitor_id')
        
        if not message:
            return error_response('message is required', status_code=status.HTTP_400_BAD_REQUEST)
        
        if not visitor_id:
            return error_response('visitor_id is required', status_code=status.HTTP_400_BAD_REQUEST)
        
        # Validate visitor exists
        try:
            visitor = Visitor.objects.get(id=visitor_id)
            visitor.update_last_seen()
        except Visitor.DoesNotExist:
            return error_response(
                f"Visitor with ID '{visitor_id}' does not exist. Please create a visitor first via POST /api/chats/visitors/",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Validate session
        session, error_response = validate_session(session_id)
        if error_response:
            return error_response
        
        # Validate visitor_id matches session's visitor
        if str(session.visitor.id) != str(visitor_id):
            return error_response(
                f"Visitor ID '{visitor_id}' does not match the session's visitor ID '{session.visitor.id}'",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
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
                'session_id': str(session.id),  # Return the id as session_id for API consistency
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
        summary="Streaming chat (SSE) (STEP 3)",
        description="Send a chat message and receive streaming response via Server-Sent Events (SSE). Requires API key authentication (X-API-Key header or Authorization: Bearer <api-key>). visitor_id and session_id are REQUIRED. Session ID must be valid, active, and not expired. Visitor ID must match the session's visitor.",
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
            400: {'description': 'Bad request - message, session_id, or visitor_id missing'},
            403: {'description': 'Forbidden - session is inactive or expired, or visitor_id mismatch'},
            404: {'description': 'Not found - session or visitor does not exist'}
        },
        tags=['Messages'],
    )
    @action(detail=False, methods=['post'], url_path='chat/stream',
            authentication_classes=[APIKeyAuthentication],
            permission_classes=[RequiresAPIKey])
    def chat_stream(self, request):
        """
        Streaming chat endpoint using Server-Sent Events (SSE).
        Receives user message, session_id, and visitor_id, streams assistant response.
        Both messages are permanently stored.
        visitor_id and session_id are REQUIRED. Session ID must be valid, active, and not expired.
        Visitor ID must match the session's visitor.
        """
        message = request.data.get('message')
        session_id = request.data.get('session_id')
        visitor_id = request.data.get('visitor_id')
        
        if not message:
            return error_response('message is required', status_code=status.HTTP_400_BAD_REQUEST)
        
        if not visitor_id:
            return error_response('visitor_id is required', status_code=status.HTTP_400_BAD_REQUEST)
        
        # Validate visitor exists
        try:
            visitor = Visitor.objects.get(id=visitor_id)
            visitor.update_last_seen()
        except Visitor.DoesNotExist:
            return error_response(
                f"Visitor with ID '{visitor_id}' does not exist. Please create a visitor first via POST /api/chats/visitors/",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Validate session
        session, error_response = validate_session(session_id)
        if error_response:
            return error_response
        
        # Validate visitor_id matches session's visitor
        if str(session.visitor.id) != str(visitor_id):
            return error_response(
                f"Visitor ID '{visitor_id}' does not match the session's visitor ID '{session.visitor.id}'",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
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
