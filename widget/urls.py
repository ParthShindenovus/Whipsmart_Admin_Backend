from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    WidgetAPIKeyViewSet,
    get_widget_config,
    get_embed_code,
)

router = DefaultRouter()
router.register(r'api-keys', WidgetAPIKeyViewSet, basename='widget-api-key')

urlpatterns = [
    path('', include(router.urls)),
    path('config/', get_widget_config, name='widget-config'),
    path('embed-code/', get_embed_code, name='widget-embed-code'),
]

