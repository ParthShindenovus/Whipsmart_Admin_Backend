from rest_framework import serializers
from django.utils import timezone
from .models import ChatMessage, Session, Visitor
import uuid


class VisitorSerializer(serializers.ModelSerializer):
    """
    Serializer for Visitor model.
    
    Visitor IDs are auto-generated UUIDs. No input required from client.
    """
    class Meta:
        model = Visitor
        fields = ['id', 'created_at', 'last_seen_at', 'metadata']
        read_only_fields = ['id', 'created_at', 'last_seen_at']


class ChatRequestSerializer(serializers.Serializer):
    """
    Serializer for chat request (both streaming and non-streaming).
    Used for Swagger documentation to properly display request body.
    """
    message = serializers.CharField(
        required=True,
        help_text="User message to send to the assistant"
    )
    session_id = serializers.CharField(
        required=True,
        help_text="Session ID (required). Must be a valid, active, and non-expired session."
    )
    visitor_id = serializers.UUIDField(
        required=True,
        help_text="Visitor ID (required). Must match the visitor associated with the session."
    )


class SessionSerializer(serializers.ModelSerializer):
    """
    Serializer for Session model.
    
    The id field (UUID) serves as the session identifier.
    Visitor ID is REQUIRED - must be created first via /api/chats/visitors/ endpoint.
    expires_at is optional (auto-generated if not provided).
    """
    visitor_id = serializers.UUIDField(
        required=True,
        write_only=True,
        help_text="Visitor ID (REQUIRED). Must be created first via POST /api/chats/visitors/"
    )
    visitor = VisitorSerializer(read_only=True, help_text="Visitor details (read-only)")
    expires_at = serializers.DateTimeField(required=False, allow_null=True, help_text="Expiration time (optional, defaults to 24h from now)")
    
    last_message = serializers.SerializerMethodField(help_text="Last message in the session (for frontend preview)")
    last_message_at = serializers.SerializerMethodField(help_text="Timestamp of the last message")
    
    class Meta:
        model = Session
        fields = ['id', 'visitor_id', 'visitor', 'external_user_id', 
                  'conversation_data', 'created_at', 'expires_at', 'is_active', 
                  'last_message', 'last_message_at', 'metadata']
        read_only_fields = ['id', 'visitor', 'created_at', 'last_message', 'last_message_at']
    
    def get_last_message(self, obj):
        """Get last_message field - optimized to use model field directly."""
        # Use model field directly (fast - no DB query)
        return getattr(obj, 'last_message', None)
    
    def get_last_message_at(self, obj):
        """Get last_message_at field - optimized to use model field directly."""
        # Use model field directly (fast - no DB query)
        return getattr(obj, 'last_message_at', None)
    
    def validate_visitor_id(self, value):
        """Validate that visitor exists - optimized with select_related."""
        try:
            # Use exists() for faster validation (doesn't load full object)
            if not Visitor.objects.filter(id=value).exists():
                raise Visitor.DoesNotExist
            # Update last_seen_at using update() for better performance
            Visitor.objects.filter(id=value).update(last_seen_at=timezone.now())
            return value
        except Visitor.DoesNotExist:
            raise serializers.ValidationError(
                f"Visitor with ID '{value}' does not exist. Please create a visitor first via POST /api/chats/visitors/"
            )
    
    def create(self, validated_data):
        """
        Create session - optimized for performance.
        - id (UUID) is auto-generated as primary key
        - visitor_id is REQUIRED and must exist (validated in validate_visitor_id)
        - expires_at will be set by model's save() method if not provided
        - conversation_data defaults to empty dict if not provided
        """
        visitor_id = validated_data.pop('visitor_id')
        # Use only() to fetch only needed fields for better performance
        visitor = Visitor.objects.only('id').get(id=visitor_id)
        validated_data['visitor'] = visitor
        
        # Ensure conversation_data has a default value
        if 'conversation_data' not in validated_data:
            validated_data['conversation_data'] = {}
        
        return super().create(validated_data)


class ChatMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for ChatMessage model.
    
    Session details are excluded from the response - only session_id (UUID) is shown.
    Only user and assistant messages are returned (system messages are excluded).
    """
    session_id = serializers.UUIDField(
        source='session.id',
        read_only=True,
        help_text="Session ID (read-only UUID)"
    )
    
    class Meta:
        model = ChatMessage
        fields = ['id', 'session_id', 'message', 'role', 'metadata', 'timestamp']
        read_only_fields = ['id', 'session_id', 'timestamp']
        # Exclude is_deleted from response - we only show non-deleted messages
