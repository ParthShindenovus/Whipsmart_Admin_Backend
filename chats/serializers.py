from rest_framework import serializers
from django.utils import timezone
from .models import ChatMessage, Session
import uuid


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


class SessionSerializer(serializers.ModelSerializer):
    """
    Serializer for Session model.
    
    No user_id required. session_id and expires_at are optional (auto-generated if not provided).
    """
    session_id = serializers.CharField(required=False, allow_blank=True, help_text="Session ID (optional, auto-generated if not provided)")
    expires_at = serializers.DateTimeField(required=False, allow_null=True, help_text="Expiration time (optional, defaults to 24h from now)")
    
    class Meta:
        model = Session
        fields = ['id', 'session_id', 'external_user_id', 'created_at', 
                  'expires_at', 'is_active', 'metadata']
        read_only_fields = ['id', 'created_at']
    
    def create(self, validated_data):
        """Generate session_id and expires_at if not provided. No user_id required."""
        # Generate session_id if not provided
        if 'session_id' not in validated_data or not validated_data.get('session_id'):
            validated_data['session_id'] = str(uuid.uuid4())
        
        # expires_at will be set by model's save() method if not provided
        return super().create(validated_data)


class ChatMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for ChatMessage model.
    
    session_id is ALWAYS required. Messages are permanently stored.
    No user_id required.
    """
    session = SessionSerializer(read_only=True)
    session_id = serializers.CharField(
        write_only=True, 
        required=True,
        help_text="Session ID (required). Can be UUID or session_id string."
    )
    
    class Meta:
        model = ChatMessage
        fields = ['id', 'session', 'session_id', 'message', 'role', 'metadata', 
                  'is_deleted', 'timestamp']
        read_only_fields = ['id', 'timestamp']
    
    def validate_session_id(self, value):
        """Validate that session exists, is active, and not expired."""
        if not value:
            raise serializers.ValidationError('session_id is required')
        
        # Try to get session by session_id string first, then by UUID
        try:
            session = Session.objects.get(session_id=value)
        except Session.DoesNotExist:
            try:
                # Try as UUID
                session = Session.objects.get(id=value)
            except (Session.DoesNotExist, ValueError):
                raise serializers.ValidationError(f'Session not found with session_id: {value}')
        
        # Check if session is active
        if not session.is_active:
            raise serializers.ValidationError('Session is not active')
        
        # Check if session has expired
        if session.is_expired():
            raise serializers.ValidationError('Session has expired')
        
        return value
    
    def create(self, validated_data):
        """Create message with session_id. Message is permanently stored."""
        session_id = validated_data.pop('session_id')
        
        # Get session (validation already done in validate_session_id)
        try:
            session = Session.objects.get(session_id=session_id)
        except Session.DoesNotExist:
            # Try as UUID if session_id validation passed
            session = Session.objects.get(id=session_id)
        
        validated_data['session'] = session
        # Message is automatically saved to database (permanent storage)
        return super().create(validated_data)
