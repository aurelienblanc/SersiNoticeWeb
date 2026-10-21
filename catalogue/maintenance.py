import contextlib
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .backups import BackupError, backup_path, create_backup, restore_backup, verify_backup
from .journal import record_event
from .models import ActivityEvent, BackupRecord, ExportRecord, MaintenanceJob, MaintenanceSettings


@contextlib.contextmanager
def maintenance_lock():
    """One OS lock for all web/worker processes; released even after a crash."""
    path = Path(settings.RUNTIME_DIR) / 'maintenance.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    pass
            yield acquired
        finally:
            if acquired:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def queue_job(kind, backup=None, origin='manual'):
    with transaction.atomic():
        MaintenanceSettings.objects.get_or_create(pk=1)
        MaintenanceSettings.objects.select_for_update().get(pk=1)
        if MaintenanceJob.objects.filter(status__in=['queued', 'running'], kind='restore').exists():
            raise BackupError('Une restauration est déjà en attente ou en cours.')
        if kind == 'restore' and MaintenanceJob.objects.filter(status__in=['queued', 'running']).exists():
            raise BackupError('Attendez la fin des opérations déjà demandées avant de restaurer.')
        if kind != 'restore' and MaintenanceJob.objects.filter(kind=kind, backup=backup, status__in=['queued', 'running']).exists():
            raise BackupError('Cette opération est déjà en attente ou en cours.')
        return MaintenanceJob.objects.create(kind=kind, backup=backup, origin=origin)


def delete_backup(backup, automatic=False):
    if MaintenanceJob.objects.filter(backup=backup, status__in=['queued', 'running']).exists():
        raise BackupError('Cette sauvegarde est utilisée par une opération en cours.')
    identifier = str(backup.pk)
    backup_path(backup).unlink(missing_ok=True)
    backup.delete()
    record_event('backups', 'backup.deleted', 'Sauvegarde supprimée selon la conservation automatique.' if automatic else 'Sauvegarde supprimée.', details={'sauvegarde': identifier})


def purge_logs(days):
    from django.contrib.admin.models import LogEntry
    before = timezone.now() - timedelta(days=days)
    count, _ = ActivityEvent.objects.filter(created_at__lt=before).delete()
    history_count, _ = LogEntry.objects.filter(action_time__lt=before).delete()
    export_count, _ = ExportRecord.objects.filter(created_at__lt=before).delete()
    MaintenanceJob.objects.filter(finished_at__lt=before, status__in=['done', 'failed']).delete()
    record_event('system', 'logs.purged', 'Nettoyage des anciens journaux.', details={'jours_conserves': days, 'evenements_supprimes': count, 'historique_supprime': history_count, 'exports_supprimes': export_count})
    return count


def prune_backups(config):
    for origin, keep in [('automatic', config.automatic_retention), ('safety', 3)]:
        for backup in list(BackupRecord.objects.filter(origin=origin).order_by('-created_at')[keep:]):
            try:
                delete_backup(backup, automatic=True)
            except (BackupError, OSError):
                continue


def run_pending_job():
    with maintenance_lock() as acquired:
        if not acquired:
            return None
        # No process owns the OS lock, so leftover running jobs were interrupted.
        abandoned = MaintenanceJob.objects.filter(status='running')
        if abandoned.exists():
            abandoned.update(status='failed', finished_at=timezone.now(), message='Opération interrompue par un arrêt du service. Vous pouvez la relancer.')
            record_event('system', 'maintenance.interrupted', 'Une opération de maintenance a été interrompue.', level='WARNING')
        job = MaintenanceJob.objects.filter(status='queued').order_by('created_at').first()
        if not job:
            return None
        job.status, job.started_at = 'running', timezone.now()
        job.save(update_fields=['status', 'started_at'])
        record_event('backups', 'maintenance.started', f'{job.get_kind_display()} démarrée.', details={'operation': str(job.pk)})
        last_percent = -1

        def progress(percent, message):
            nonlocal last_percent
            if percent != last_percent:
                MaintenanceJob.objects.filter(pk=job.pk).update(progress=percent, message=message)
                MaintenanceSettings.objects.filter(pk=1).update(worker_seen_at=timezone.now())
                last_percent = percent

        try:
            if job.kind == 'backup':
                job.backup = create_backup(job.origin, progress)
                job.message = 'Sauvegarde créée et vérifiée.'
            elif job.kind == 'verify':
                verify_backup(job.backup, progress)
                job.message = 'Tous les fichiers de la sauvegarde sont intègres.'
                record_event('backups', 'backup.verified', 'Sauvegarde vérifiée.', details={'sauvegarde': str(job.backup_id)})
            else:
                safety = restore_backup(job.backup, progress)
                job.message = f'Restauration terminée. Sauvegarde de protection : {safety.pk}.'
            job.status, job.progress = 'done', 100
        except Exception as error:
            job.status = 'failed'
            job.message = str(error) if isinstance(error, BackupError) else 'Une erreur technique a interrompu l’opération. Les données précédentes sont conservées si la restauration n’a pas abouti.'
            if job.backup and job.kind in ('verify', 'restore'):
                BackupRecord.objects.filter(pk=job.backup_id).update(verified_at=None)
            record_event('backups', 'maintenance.failed', job.message, level='ERROR', details={
                'operation': str(job.pk), 'type_erreur': type(error).__name__,
            })
        job.finished_at = timezone.now()
        job.save(update_fields=['backup', 'status', 'progress', 'message', 'finished_at'])
        if job.status == 'done' and (job.origin == 'automatic' or job.kind == 'restore'):
            prune_backups(MaintenanceSettings.objects.get(pk=1))
        return job


def housekeeping():
    with maintenance_lock() as acquired:
        if not acquired:
            return
        config, _ = MaintenanceSettings.objects.get_or_create(pk=1)
        now = timezone.localtime()
        MaintenanceSettings.objects.filter(pk=1).update(worker_seen_at=timezone.now())
        if config.automatic_backups and config.last_scheduled_date < now.date() and now.time() >= config.backup_time:
            try:
                queue_job('backup', origin='automatic')
            except BackupError:
                pass  # Retry after the current manual operation or restore.
            else:
                config.last_scheduled_date = now.date()
                config.save(update_fields=['last_scheduled_date'])
        if config.last_cleanup_date != now.date():
            purge_logs(config.log_retention_days)
            # Never prune manual or imported archives automatically. Keep the
            # latest three protection archives independently of the daily policy.
            prune_backups(config)
            config.last_cleanup_date = now.date()
            config.save(update_fields=['last_cleanup_date'])
