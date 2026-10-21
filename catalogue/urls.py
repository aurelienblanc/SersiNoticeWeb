from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('preparer/', views.preview, name='preview'),
    path('exporter/', views.download_export, name='download_export'),
    path('documents/<int:pk>/telecharger/', views.download_document, name='download_document'),
    path('health/', views.health, name='health'),
]
