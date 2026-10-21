from django.contrib import messages
from django.contrib.admin import AdminSite
from django.contrib.admin.models import LogEntry
from django.contrib.auth.hashers import make_password
from django.http import HttpResponseRedirect
from django.middleware.csrf import rotate_token
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.views.decorators.debug import sensitive_post_parameters

from .admin_access import (
    SESSION_KEY, SharedLoginForm, SharedPasswordChangeForm,
    access_token, audit_principal, verify_password,
)
from .models import AdministrationAccess, Document, Marque, Produit
from .journal import record_event


class SharedPasswordAdminSite(AdminSite):
    site_header = 'SERSI Notice'
    site_title = 'Administration · SERSI Notice'
    index_title = 'Votre bibliothèque, à jour.'
    index_template = 'admin/sersi_index.html'

    def get_urls(self):
        from django.urls import path
        from . import maintenance_views as views
        definitions = [
            ('', views.overview, 'maintenance'), ('settings/', views.save_settings, 'maintenance_settings'),
            ('journal/', views.journal, 'maintenance_journal'), ('journal/export/', views.export_journal, 'maintenance_journal_export'),
            ('journal/purge/', views.purge, 'maintenance_journal_purge'), ('status/', views.status, 'maintenance_status'),
            ('backups/create/', views.create, 'maintenance_backup_create'), ('backups/upload/', views.upload, 'maintenance_backup_upload'),
            ('backups/<uuid:pk>/download/', views.download, 'maintenance_backup_download'),
            ('backups/<uuid:pk>/verify/', views.verify, 'maintenance_backup_verify'),
            ('backups/<uuid:pk>/restore/', views.restore, 'maintenance_backup_restore'),
            ('backups/<uuid:pk>/delete/', views.remove, 'maintenance_backup_delete'),
        ]
        return [path('maintenance/' + route, self.admin_view(view), name=name) for route, view, name in definitions] + super().get_urls()

    def has_permission(self, request):
        if hasattr(request, '_sersi_admin_permission'):
            return request._sersi_admin_permission
        access = AdministrationAccess.objects.filter(pk=1).first()
        token = request.session.get(SESSION_KEY, '')
        allowed = bool(access and isinstance(token, str) and constant_time_compare(token, access_token(access)))
        request._sersi_admin_permission = allowed
        if allowed:
            request.user = audit_principal()
        return allowed

    def index(self, request, extra_context=None):
        return super().index(request, {
            'catalogue_stats': {
                'produits': Produit.objects.count(), 'documents': Document.objects.count(),
                'marques': Marque.objects.count(),
                'expires': Document.objects.filter(date_expiration__lt=timezone.localdate()).count(),
            },
            'recent_changes': LogEntry.objects.select_related('content_type').order_by('-action_time')[:6],
            **(extra_context or {}),
        })

    def app_index(self, request, app_label, extra_context=None):
        return HttpResponseRedirect(reverse('admin:index'))

    @method_decorator(never_cache)
    @method_decorator(csrf_protect)
    @method_decorator(sensitive_post_parameters('password'))
    def login(self, request, extra_context=None):
        if request.method == 'GET' and self.has_permission(request):
            return HttpResponseRedirect(reverse('admin:index'))
        access = AdministrationAccess.objects.filter(pk=1).first()
        form = SharedLoginForm(request.POST if request.method == 'POST' else None)
        target = request.POST.get('next', request.GET.get('next', ''))
        if not url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
            target = reverse('admin:index')
        status = 200
        if request.method == 'POST' and form.is_valid():
            if not access:
                form.add_error(None, 'L’accès à l’administration n’est pas encore configuré.')
                status = 503
            else:
                valid, blocked = verify_password(request, form.cleaned_data['password'], access)
                if valid:
                    request.session.flush()
                    request.session[SESSION_KEY] = access_token(access)
                    rotate_token(request)
                    record_event('security', 'admin.login', 'Ouverture de l’administration.')
                    return HttpResponseRedirect(target)
                record_event('security', 'admin.login_failed', 'Connexion à l’administration refusée.', level='WARNING', details={'blocage_temporaire': blocked})
                form.add_error('password', 'Trop de tentatives. Réessayez dans cinq minutes.' if blocked else 'Le mot de passe est incorrect.')
                status = 429 if blocked else 200
        request.current_app = self.name
        return TemplateResponse(request, 'admin/shared_login.html', {
            'site_title': self.site_title, 'title': 'Accès à l’administration',
            'form': form, 'next': target, 'configured': bool(access), 'is_nav_sidebar_enabled': False,
            **(extra_context or {}),
        }, status=status)

    @method_decorator(require_POST)
    def logout(self, request, extra_context=None):
        record_event('security', 'admin.logout', 'Fermeture de la session d’administration.')
        request.session.flush()
        return HttpResponseRedirect(reverse('admin:login'))

    @method_decorator(never_cache)
    @method_decorator(sensitive_post_parameters('current_password', 'new_password', 'confirmation'))
    def password_change(self, request, extra_context=None):
        access = AdministrationAccess.objects.get(pk=1)
        form = SharedPasswordChangeForm(request.POST if request.method == 'POST' else None, access=access)
        if request.method == 'POST' and form.is_valid():
            access.password_hash = make_password(form.cleaned_data['new_password'])
            access.save(update_fields=['password_hash'])
            record_event('security', 'admin.password_changed', 'Modification du mot de passe commun.')
            request.session.cycle_key()
            request.session[SESSION_KEY] = access_token(access)
            rotate_token(request)
            messages.success(request, 'Le mot de passe commun a été modifié. Les autres sessions devront se reconnecter.')
            return HttpResponseRedirect(reverse('admin:index'))
        request.current_app = self.name
        return TemplateResponse(request, 'admin/shared_password_change.html', {
            **self.each_context(request), 'title': 'Changer le mot de passe commun', 'form': form,
            **(extra_context or {}),
        })

    def password_change_done(self, request, extra_context=None):
        return HttpResponseRedirect(reverse('admin:index'))


admin_site = SharedPasswordAdminSite(name='admin')
