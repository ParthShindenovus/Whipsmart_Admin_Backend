"""
URL configuration for knowledge_graph app.
"""
from django.urls import path
from .views import BuildKGView, QueryKGView, DeleteKGView, ClearAllKGView

urlpatterns = [
    path('build/', BuildKGView.as_view(), name='kg-build'),
    path('query/', QueryKGView.as_view(), name='kg-query'),
    path('delete/', DeleteKGView.as_view(), name='kg-delete'),
    path('clear/', ClearAllKGView.as_view(), name='kg-clear-all'),
]

