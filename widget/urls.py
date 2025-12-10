from django.urls import path, include
from core.router import NoFormatSuffixRouter
from .views import (
    WidgetAPIKeyViewSet,
    get_widget_config,
    get_embed_code,
)

router = NoFormatSuffixRouter()
router.register(r'api-keys', WidgetAPIKeyViewSet, basename='widget-api-key')

urlpatterns = [
    path('', include(router.urls)),
    path('config/', get_widget_config, name='widget-config'),
    path('embed-code/', get_embed_code, name='widget-embed-code'),
]

