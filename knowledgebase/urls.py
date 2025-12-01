from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DocumentViewSet, KnowledgebaseStatsView

router = DefaultRouter()
router.register(r'documents', DocumentViewSet, basename='document')

urlpatterns = [
    path('', include(router.urls)),
    path('stats/', KnowledgebaseStatsView.as_view(), name='knowledgebase-stats'),
]
