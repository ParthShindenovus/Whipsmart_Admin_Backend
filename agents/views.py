# Agents app for LangGraph integration
# This will be extended with actual agent implementation
from rest_framework import views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated


class AgentView(views.APIView):
    """Placeholder view for agent endpoints."""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        return Response({'message': 'Agent endpoints coming soon'})
