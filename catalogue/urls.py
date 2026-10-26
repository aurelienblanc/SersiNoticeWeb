from django.urls import path
from . import document_views, views

urlpatterns = [
    path('', views.index, name='index'),
    path('preparer/', views.preview, name='preview'),
    path('exporter/', views.download_export, name='download_export'),
    path('documents/', document_views.document_library, name='document_library'),
    path('documents/<int:pk>/consulter/', document_views.view_document, name='view_document'),
    path('documents/<int:pk>/telecharger/', document_views.download_document, name='download_document'),
    path('health/', views.health, name='health'),
]
