from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChatMessageViewSet, SessionViewSet, VisitorViewSet

router = DefaultRouter()
router.register(r'visitors', VisitorViewSet, basename='visitor')
router.register(r'sessions', SessionViewSet, basename='session')
router.register(r'messages', ChatMessageViewSet, basename='message')

urlpatterns = [
    path('', include(router.urls)),
]
