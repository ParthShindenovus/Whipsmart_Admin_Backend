from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login
from drf_spectacular.utils import extend_schema, extend_schema_view
from .models import AdminUser
from .serializers import AdminUserSerializer, LoginSerializer
from .views_base import StandardizedResponseMixin
from .utils import success_response, error_response


@extend_schema_view(
    list=extend_schema(
        summary="List all admin users",
        description="Retrieve a list of all admin users. Requires authentication.",
        tags=['Users'],
    ),
    retrieve=extend_schema(
        summary="Get admin user details",
        description="Retrieve detailed information about a specific admin user.",
        tags=['Users'],
    ),
    create=extend_schema(
        summary="Create new admin user",
        description="Create a new admin user account. Requires superuser privileges.",
        tags=['Users'],
    ),
    update=extend_schema(exclude=True),  # Hide full update - use partial_update if needed
    partial_update=extend_schema(exclude=True),  # Hide partial update endpoint
    destroy=extend_schema(
        summary="Delete admin user",
        description="Delete an admin user account. Requires superuser privileges.",
        tags=['Users'],
    ),
)
class AdminUserViewSet(StandardizedResponseMixin, viewsets.ModelViewSet):
    """
    ViewSet for AdminUser model.
    
    Provides CRUD operations for admin users with authentication endpoints.
    """
    queryset = AdminUser.objects.all()
    serializer_class = AdminUserSerializer
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Admin user login",
        description="Authenticate an admin user and receive JWT access and refresh tokens.",
        request=LoginSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'access': {'type': 'string', 'description': 'JWT access token'},
                    'refresh': {'type': 'string', 'description': 'JWT refresh token'},
                    'user': {'type': 'object', 'description': 'User information'},
                }
            },
            400: {'description': 'Invalid credentials'}
        },
        tags=['Authentication'],
    )
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def login(self, request):
        """Login endpoint for admin users."""
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            refresh = RefreshToken.for_user(user)
            login(request, user)
            return success_response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': AdminUserSerializer(user).data
            }, message="Login successful")
        return error_response(
            message="Invalid credentials",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    @extend_schema(
        summary="Get current user",
        description="Retrieve information about the currently authenticated user.",
        responses={200: AdminUserSerializer},
        tags=['Users'],
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def me(self, request):
        """Get current user information."""
        serializer = AdminUserSerializer(request.user)
        return success_response(serializer.data)
