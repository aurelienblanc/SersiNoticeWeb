from django.urls import include, path

from catalogue.admin_site import admin_site

urlpatterns = [path('admin/', admin_site.urls), path('', include('catalogue.urls'))]
