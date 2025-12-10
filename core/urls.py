from django.urls import path, include
from core.router import NoFormatSuffixRouter
from .views import AdminUserViewSet

router = NoFormatSuffixRouter()
router.register(r'users', AdminUserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),
]
