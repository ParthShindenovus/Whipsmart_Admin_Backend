from django.urls import path, include
from core.router import NoFormatSuffixRouter
from .views import DocumentViewSet, KnowledgebaseStatsView, PDFExtractView
from .views_streaming import StreamingDocumentUploadView

router = NoFormatSuffixRouter()
router.register(r"documents", DocumentViewSet, basename="document")

urlpatterns = [
    # Put specific routes BEFORE router to avoid conflicts
    path(
        "documents/upload-stream/",
        StreamingDocumentUploadView.as_view(),
        name="knowledgebase-document-upload-stream",
    ),
    path("stats/", KnowledgebaseStatsView.as_view(), name="knowledgebase-stats"),
    path(
        "pdf-extract/",
        PDFExtractView.as_view(),
        name="knowledgebase-pdf-extract",
    ),
    path("", include(router.urls)),
]
