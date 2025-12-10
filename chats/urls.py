from django.urls import path, include
from core.router import NoFormatSuffixRouter
from .views import ChatMessageViewSet, SessionViewSet, VisitorViewSet

router = NoFormatSuffixRouter()
router.register(r'visitors', VisitorViewSet, basename='visitor')
router.register(r'sessions', SessionViewSet, basename='session')
router.register(r'messages', ChatMessageViewSet, basename='message')

urlpatterns = [
    path('', include(router.urls)),
]
