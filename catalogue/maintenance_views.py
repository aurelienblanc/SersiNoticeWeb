import csv
import hashlib
import json
import uuid
import zipfile
from datetime import timedelta

from django.contrib import messages
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import FileResponse, Http404, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .backups import BackupError, backup_directory, backup_path
from .journal import record_event
from .maintenance import delete_backup, maintenance_lock, purge_logs, queue_job
from .maintenance_forms import BackupUploadForm, ConfirmMaintenanceForm, JournalFilterForm, MaintenanceSettingsForm
from .models import ActivityEvent, BackupRecord, MaintenanceJob, MaintenanceSettings


def render_admin(request, template, context, status=200):
    from .admin_site import admin_site
    request.current_app = admin_site.name
    return TemplateResponse(request, template, {**admin_site.each_context(request), **context}, status=status)


def redirect_overview():
    return HttpResponseRedirect(reverse('admin:maintenance'))


@require_GET
def overview(request):
    config, _ = MaintenanceSettings.objects.get_or_create(pk=1)
    jobs = MaintenanceJob.objects.select_related('backup')
    backups = BackupRecord.objects.all()
    return render_admin(request, 'admin/maintenance.html', {
        'title': 'Maintenance et sauvegardes', 'config': config,
        'settings_form': MaintenanceSettingsForm(instance=config), 'upload_form': BackupUploadForm(),
        'backups': Paginator(backups, 15).get_page(request.GET.get('page')),
        'backup_count': backups.count(), 'backup_size': backups.aggregate(total=Sum('size'))['total'] or 0,
        'jobs': jobs[:8], 'active_jobs': jobs.filter(status__in=['queued', 'running']).exists(),
        'worker_alive': bool(config.worker_seen_at and timezone.now() - config.worker_seen_at < timedelta(seconds=90)),
        'storage_path': str(backup_directory()), 'upload_max_gb': settings.SERSI_BACKUP_UPLOAD_BYTES // 1024 ** 3,
    })


@require_POST
def save_settings(request):
    config, _ = MaintenanceSettings.objects.get_or_create(pk=1)
    form = MaintenanceSettingsForm(request.POST, instance=config)
    if form.is_valid():
        config = form.save(commit=False)
        config.last_cleanup_date = None
        config.save()
        record_event('backups', 'maintenance.settings_changed', 'Réglages de maintenance modifiés.', details={
            'automatique': config.automatic_backups, 'heure': config.backup_time.isoformat(),
            'copies_automatiques': config.automatic_retention, 'journaux_jours': config.log_retention_days,
        })
        messages.success(request, 'Réglages de maintenance enregistrés.')
    else:
        messages.error(request, 'Les réglages sont invalides. ' + ' '.join(error for values in form.errors.values() for error in values))
    return redirect_overview()


@require_POST
def create(request):
    try:
        queue_job('backup')
        messages.success(request, 'La sauvegarde est en attente. Vous pouvez suivre sa progression ci-dessous.')
    except BackupError as error:
        messages.error(request, str(error))
    return redirect_overview()


@require_POST
def upload(request):
    from django.conf import settings
    form = BackupUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Choisissez une sauvegarde ZIP respectant la taille maximale autorisée.')
        return redirect_overview()
    identifier = uuid.uuid4()
    filename = f'sersi-{identifier.hex}.zip'
    path = backup_directory() / filename
    digest, size = hashlib.sha256(), 0
    backup = None
    try:
        with path.open('xb') as stream:
            for chunk in form.cleaned_data['archive'].chunks():
                size += len(chunk)
                if size > settings.SERSI_BACKUP_UPLOAD_BYTES:
                    raise BackupError('Cette sauvegarde dépasse la taille maximale autorisée.')
                digest.update(chunk)
                stream.write(chunk)
        if not zipfile.is_zipfile(path):
            raise BackupError('Le fichier importé n’est pas une archive ZIP valide.')
        backup = BackupRecord.objects.create(id=identifier, filename=filename, origin='upload', size=size, sha256=digest.hexdigest())
        queue_job('verify', backup)
        record_event('backups', 'backup.uploaded', 'Archive de sauvegarde importée pour vérification.', details={'sauvegarde': str(backup.pk)})
        messages.success(request, 'Archive reçue. Sa vérification est en attente ; elle sera nécessaire avant la restauration.')
    except (BackupError, OSError) as error:
        path.unlink(missing_ok=True)
        if backup:
            backup.delete()
        messages.error(request, str(error) if isinstance(error, BackupError) else 'L’archive ne peut pas être enregistrée sur le serveur.')
    return redirect_overview()


@require_GET
def download(request, pk):
    backup = get_object_or_404(BackupRecord, pk=pk)
    try:
        stream = backup_path(backup).open('rb')
    except (OSError, BackupError) as error:
        raise Http404('La sauvegarde n’est plus disponible sur le serveur.') from error
    record_event('backups', 'backup.downloaded', 'Téléchargement d’une sauvegarde.', details={'sauvegarde': str(pk)})
    filename = f'SERSI-Notice-sauvegarde-{timezone.localtime(backup.created_at):%Y%m%d-%H%M%S}.zip'
    return FileResponse(stream, as_attachment=True, filename=filename, content_type='application/zip')


@require_POST
def verify(request, pk):
    backup = get_object_or_404(BackupRecord, pk=pk)
    try:
        queue_job('verify', backup)
        messages.success(request, 'Vérification de la sauvegarde en attente.')
    except BackupError as error:
        messages.error(request, str(error))
    return redirect_overview()


@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('password')
def restore(request, pk):
    backup = get_object_or_404(BackupRecord, pk=pk)
    if not backup.verified_at:
        messages.error(request, 'Vérifiez d’abord l’intégrité de cette sauvegarde.')
        return redirect_overview()
    form = ConfirmMaintenanceForm(request.POST if request.method == 'POST' else None, request=request, word='RESTAURER')
    if request.method == 'POST' and form.is_valid():
        try:
            queue_job('restore', backup)
            messages.success(request, 'La restauration est en attente. Une sauvegarde de protection sera créée avant toute modification.')
            return redirect_overview()
        except BackupError as error:
            form.add_error(None, str(error))
    return render_admin(request, 'admin/maintenance_confirm.html', {
        'title': 'Restaurer une sauvegarde', 'form': form, 'backup': backup,
        'description': 'Cette opération remplacera le catalogue, ses documents et son historique par le contenu de la sauvegarde. Une sauvegarde de protection sera créée auparavant. Le mot de passe commun et les réglages du serveur seront conservés.',
        'button': 'Confirmer la restauration',
    })


@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('password')
def remove(request, pk):
    backup = get_object_or_404(BackupRecord, pk=pk)
    form = ConfirmMaintenanceForm(request.POST if request.method == 'POST' else None, request=request, word='SUPPRIMER')
    if request.method == 'POST' and form.is_valid():
        with maintenance_lock() as acquired:
            try:
                if not acquired:
                    raise BackupError('Une opération de maintenance est en cours. Réessayez à sa fin.')
                delete_backup(backup)
                messages.success(request, 'La sauvegarde a été supprimée.')
                return redirect_overview()
            except (BackupError, OSError) as error:
                form.add_error(None, str(error) if isinstance(error, BackupError) else 'La sauvegarde ne peut pas être supprimée actuellement.')
    return render_admin(request, 'admin/maintenance_confirm.html', {
        'title': 'Supprimer une sauvegarde', 'form': form, 'backup': backup,
        'description': 'Cette opération supprime définitivement cette archive du serveur. Le catalogue et ses documents restent inchangés.',
        'button': 'Supprimer cette sauvegarde',
    })


def filtered_events(request):
    form = JournalFilterForm(request.GET)
    events = ActivityEvent.objects.all()
    if form.is_valid():
        data = form.cleaned_data
        if data['q']:
            events = events.filter(Q(message__icontains=data['q']) | Q(event__icontains=data['q']))
        for field in ('level', 'category'):
            if data[field]:
                events = events.filter(**{field: data[field]})
        if data['after']:
            events = events.filter(created_at__date__gte=data['after'])
        if data['before']:
            events = events.filter(created_at__date__lte=data['before'])
    else:
        events = events.none()
    return form, events


@require_GET
def journal(request):
    form, events = filtered_events(request)
    query = request.GET.copy()
    query.pop('page', None)
    return render_admin(request, 'admin/maintenance_journal.html', {
        'title': 'Journal d’activité', 'form': form, 'events': Paginator(events, 50).get_page(request.GET.get('page')),
        'query': query.urlencode(), 'event_count': events.count(),
    }, status=200 if form.is_valid() else 400)


class CsvEcho:
    def write(self, value):
        return value


def csv_cell(value):
    value = str(value)
    unsafe = value.startswith(('\t', '\r', '\n')) or value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@'))
    return "'" + value if unsafe else value


@require_GET
def export_journal(request):
    form, events = filtered_events(request)
    if not form.is_valid():
        return HttpResponseBadRequest('Les filtres du journal sont invalides.')
    record_event('system', 'logs.exported', 'Export du journal au format CSV.')
    writer = csv.writer(CsvEcho(), delimiter=';')

    def rows():
        yield '\ufeff'
        yield writer.writerow(['Date', 'Niveau', 'Rubrique', 'Événement', 'Message', 'Détails'])
        for event in events.iterator(chunk_size=1000):
            yield writer.writerow([csv_cell(value) for value in [timezone.localtime(event.created_at).isoformat(), event.level,
                event.get_category_display(), event.event, event.message, json.dumps(event.details, ensure_ascii=False)]])
    response = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="SERSI-Notice-journal.csv"'
    return response


@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('password')
def purge(request):
    config, _ = MaintenanceSettings.objects.get_or_create(pk=1)
    form = ConfirmMaintenanceForm(request.POST if request.method == 'POST' else None, request=request, word='PURGER', purge_days=config.log_retention_days)
    if request.method == 'POST' and form.is_valid():
        with maintenance_lock() as acquired:
            if acquired:
                count = purge_logs(form.cleaned_data['days'])
                messages.success(request, f'{count} ancien(s) événement(s) supprimé(s).')
                return HttpResponseRedirect(reverse('admin:maintenance_journal'))
            form.add_error(None, 'Une opération de maintenance est en cours. Réessayez à sa fin.')
    return render_admin(request, 'admin/maintenance_confirm.html', {
        'title': 'Nettoyer les anciens journaux', 'form': form,
        'description': 'Les événements et historiques antérieurs à la durée choisie seront définitivement supprimés. Les événements récents et les sauvegardes sont conservés.',
        'button': 'Nettoyer les journaux',
    })


@require_GET
def status(request):
    return JsonResponse({'jobs': list(MaintenanceJob.objects.values('id', 'kind', 'status', 'progress', 'message')[:8])})
