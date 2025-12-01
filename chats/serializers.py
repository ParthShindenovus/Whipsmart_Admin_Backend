from rest_framework import serializers
from .models import ChatMessage, Session
import uuid


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
    
    def create(self, validated_data):
        """Create message with session_id. Message is permanently stored."""
        session_id = validated_data.pop('session_id')
        
        # Try to get session by session_id string first, then by UUID
        try:
            session = Session.objects.get(session_id=session_id)
        except Session.DoesNotExist:
            try:
                # Try as UUID
                session = Session.objects.get(id=session_id)
            except (Session.DoesNotExist, ValueError):
                raise serializers.ValidationError({
                    'session_id': f'Session not found with session_id: {session_id}'
                })
        
        validated_data['session'] = session
        # Message is automatically saved to database (permanent storage)
        return super().create(validated_data)
