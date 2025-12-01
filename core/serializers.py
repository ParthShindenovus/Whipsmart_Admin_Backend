from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import AdminUser


class AdminUserSerializer(serializers.ModelSerializer):
    """Serializer for AdminUser model."""
    class Meta:
        model = AdminUser
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 
                  'is_active_admin', 'is_staff', 'created_at']
        read_only_fields = ['id', 'created_at']


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        
        if username and password:
            user = authenticate(username=username, password=password)
            if not user:
                raise serializers.ValidationError('Invalid credentials.')
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            if not user.is_active_admin:
                raise serializers.ValidationError('Admin account is not active.')
            attrs['user'] = user
        else:
            raise serializers.ValidationError('Must include username and password.')
        return attrs
