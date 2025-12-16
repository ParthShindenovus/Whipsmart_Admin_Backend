"""
WebSocket URL routing for chat application.
"""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Match /ws/chat/ with or without trailing slash
    re_path(r'^ws/chat/?$', consumers.ChatConsumer.as_asgi()),
]


