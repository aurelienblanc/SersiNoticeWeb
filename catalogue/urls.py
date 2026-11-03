from django.urls import path
from . import document_views, dolibarr_views, views

urlpatterns = [
    path('', views.index, name='index'),
    path('preparer/', views.preview, name='preview'),
    path('exporter/', views.download_export, name='download_export'),
    path('dolibarr/', dolibarr_views.proposal_lookup, name='dolibarr_lookup'),
    path('dolibarr/preparer/', dolibarr_views.proposal_preview, name='dolibarr_preview'),
    path('documents/', document_views.document_library, name='document_library'),
    path('documents/<int:pk>/consulter/', document_views.view_document, name='view_document'),
    path('documents/<int:pk>/telecharger/', document_views.download_document, name='download_document'),
    path('health/', views.health, name='health'),
]
