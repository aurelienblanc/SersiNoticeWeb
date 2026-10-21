from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'SERSI Notice · Administration'
admin.site.site_title = 'SERSI Notice'
admin.site.index_title = 'Gestion du catalogue documentaire'

urlpatterns = [path('admin/', admin.site.urls), path('', include('catalogue.urls'))]
