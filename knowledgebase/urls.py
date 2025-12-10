from django.urls import path, include
from core.router import NoFormatSuffixRouter
from .views import DocumentViewSet, KnowledgebaseStatsView

router = NoFormatSuffixRouter()
router.register(r'documents', DocumentViewSet, basename='document')

urlpatterns = [
    path('', include(router.urls)),
    path('stats/', KnowledgebaseStatsView.as_view(), name='knowledgebase-stats'),
]
