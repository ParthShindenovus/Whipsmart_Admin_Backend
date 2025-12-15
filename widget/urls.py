from django.urls import path, include
from core.router import NoFormatSuffixRouter
from .views import (
    WidgetAPIKeyViewSet,
    get_widget_config,
    get_embed_code,
    serve_widget_loader,
)

router = NoFormatSuffixRouter()
router.register(r'api-keys', WidgetAPIKeyViewSet, basename='widget-api-key')

urlpatterns = [
    path('', include(router.urls)),
    path('config/', get_widget_config, name='widget-config'),
    path('embed-code/', get_embed_code, name='widget-embed-code'),
    path('widget-loader.js', serve_widget_loader, name='widget-loader'),  # Serve widget loader with CORS
]

