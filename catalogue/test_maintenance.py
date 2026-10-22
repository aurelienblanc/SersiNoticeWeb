import hashlib
import io
import json
import logging
import stat
import tempfile
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.test import Client, RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone

from .backups import BackupError, backup_path, create_backup, restore_backup, validate_archive, verify_backup
from .journal import record_event
from .logging_handlers import JournalErrorHandler
from .maintenance import housekeeping, maintenance_lock, purge_logs, queue_job, run_pending_job
from .models import (
    ActivityEvent, AdministrationAccess, BackupRecord, Categorie, Document, DossierCible,
    MaintenanceJob, MaintenanceSettings, Marque, Produit, Systeme, TypeDocument, TypeExport,
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class MaintenanceTests(TransactionTestCase):
    password = 'Mot-commun-maintenance-2026!'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        override = override_settings(RUNTIME_DIR=self.root, MEDIA_ROOT=self.root / 'documents',
            SERSI_BACKUP_DIR=self.root / 'backups', STORAGES={
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
            })
        override.enable()
        self.addCleanup(override.disable)
        self.access = AdministrationAccess.objects.create(pk=1, password_hash=make_password(self.password))
        self.config = MaintenanceSettings.objects.create(pk=1, automatic_backups=False)
        self.brand = Marque.objects.create(nom='SERSI test')
        self.category = Categorie.objects.create(nom='ECS')
        self.system = Systeme.objects.create(nom='Type 1')
        self.export = TypeExport.objects.create(libelle='Technique')
        self.kind = TypeDocument.objects.create(nom='Notice', type_export=self.export)
        self.folder = DossierCible.objects.create(nom='Notices', chemin_relatif='Notices')
        self.child = DossierCible.objects.create(nom='ECS', chemin_relatif='ECS', parent=self.folder)
        self.product = Produit.objects.create(reference='ASD-TEST', nom='Produit initial', marque=self.brand, categorie=self.category)
        self.product.systemes.add(self.system)
        self.document = Document.objects.create(nom='Notice initiale', type_document=self.kind)
        self.content = b'%PDF-1.4\nDocumentation de test\n'
        self.document.fichier.save('notice.pdf', ContentFile(self.content))
        self.document.dossiers.add(self.child)
        self.product.documents.add(self.document)

    def connect(self, client=None):
        client = client or self.client
        self.assertEqual(client.post('/admin/login/', {'password': self.password}).status_code, 302)
        return client

    def test_round_trip_restores_data_relations_and_bytes_and_keeps_current_password(self):
        record_event('catalogue', 'test.event', 'Événement avant sauvegarde')
        backup = create_backup()
        initial_filename = self.document.fichier.name
        self.product.nom = 'Produit modifié'
        self.product.save()
        self.product.documents.clear()
        self.document.fichier.save('nouvelle-notice.pdf', ContentFile(b'nouveau fichier'))
        changed_path = Path(self.document.fichier.path)
        Produit.objects.create(reference='AJOUT', nom='Ajout temporaire', marque=self.brand, categorie=self.category)
        self.access.password_hash = make_password('Autre-mot-commun-2026!')
        self.access.save()
        current_hash = self.access.password_hash
        safety = restore_backup(backup)
        self.product.refresh_from_db()
        self.document.refresh_from_db()
        self.access.refresh_from_db()
        self.assertEqual(self.product.nom, 'Produit initial')
        self.assertEqual(Produit.objects.count(), 1)
        self.assertEqual(list(self.product.documents.values_list('pk', flat=True)), [self.document.pk])
        self.assertEqual(list(self.product.systemes.values_list('pk', flat=True)), [self.system.pk])
        self.assertEqual(self.document.dossiers.get().parent_id, self.folder.pk)
        self.assertEqual(Path(self.document.fichier.path).read_bytes(), self.content)
        self.assertEqual(self.document.nom_fichier, 'notice.pdf')
        self.assertNotEqual(self.document.fichier.name, initial_filename)
        self.assertTrue(changed_path.exists())
        self.assertEqual(self.access.password_hash, current_hash)
        self.assertEqual(safety.origin, 'safety')
        self.assertTrue(ActivityEvent.objects.filter(event='backup.restored').exists())
        self.assertEqual(ActivityEvent.objects.filter(event='test.event').count(), 1)

    def test_backup_contains_only_allowed_data_and_rejects_corruption_before_restore(self):
        backup = create_backup()
        path = backup_path(backup)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'catalogue.json', 'historique.json', 'journal.json', f'documents/{self.document.fichier.name}'})
            self.assertNotIn(self.password, archive.read('catalogue.json').decode())
            self.assertNotIn('password_hash', archive.read('catalogue.json').decode())
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaises(BackupError):
            restore_backup(backup)
        self.assertEqual(BackupRecord.objects.count(), 1)
        self.assertEqual(Produit.objects.get().nom, 'Produit initial')

    def test_unsafe_paths_symlinks_and_size_limits_are_rejected_without_extraction(self):
        for name, symlink in [('../outside.txt', False), ('C:/outside.txt', False), ('documents/link', True)]:
            path = self.root / f'bad-{uuid.uuid4().hex}.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                info = zipfile.ZipInfo(name)
                if symlink:
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, 'outside')
            with self.assertRaises(BackupError):
                validate_archive(path)
        backup = create_backup()
        with override_settings(SERSI_BACKUP_MAX_BYTES=1):
            with self.assertRaises(BackupError):
                validate_archive(backup_path(backup))
        self.assertFalse((self.root.parent / 'outside.txt').exists())

    def test_archive_cannot_inject_accounts_or_unexpected_models(self):
        backup = create_backup()
        path = backup_path(backup)
        with zipfile.ZipFile(path) as archive:
            data = {name: archive.read(name) for name in archive.namelist()}
        rows = json.loads(data['catalogue.json'])
        rows.append({'model': 'auth.user', 'pk': 999, 'fields': {'username': 'injected'}})
        data['catalogue.json'] = json.dumps(rows).encode()
        manifest = json.loads(data['manifest.json'])
        manifest['entries']['catalogue.json'] = {'size': len(data['catalogue.json']), 'sha256': hashlib.sha256(data['catalogue.json']).hexdigest()}
        data['manifest.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, 'w') as archive:
            for name, content in data.items():
                archive.writestr(name, content)
        with self.assertRaises(BackupError):
            validate_archive(path)

    def test_failed_restore_rolls_back_database_and_removes_only_staged_files(self):
        backup = create_backup()
        self.product.nom = 'État à préserver'
        self.product.save()
        original_files = set((self.root / 'documents').iterdir())
        with patch('catalogue.backups.connection.check_constraints', side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):
                restore_backup(backup)
        self.assertEqual(Produit.objects.get().nom, 'État à préserver')
        self.assertEqual(set((self.root / 'documents').iterdir()), original_files)
        self.assertTrue(BackupRecord.objects.filter(origin='safety').exists())

    def test_missing_media_does_not_leave_a_partial_backup(self):
        Path(self.document.fichier.path).unlink()
        with self.assertRaises(BackupError):
            create_backup()
        self.assertEqual(BackupRecord.objects.count(), 0)
        self.assertFalse(list((self.root / 'backups').iterdir()))

    def test_audit_failure_cannot_publish_a_backup_or_commit_a_restore(self):
        with patch('catalogue.backups.record_event', side_effect=RuntimeError('Journal indisponible')):
            with self.assertRaises(RuntimeError):
                create_backup()
        self.assertEqual(BackupRecord.objects.count(), 0)
        self.assertFalse(list((self.root / 'backups').iterdir()))
        backup = create_backup()
        self.product.nom = 'État avant restauration'
        self.product.save()
        from .backups import record_event as emit

        def fail_restore_event(category, event, *args, **kwargs):
            if event == 'backup.restored':
                raise RuntimeError('Journal indisponible')
            return emit(category, event, *args, **kwargs)

        with patch('catalogue.backups.record_event', side_effect=fail_restore_event):
            with self.assertRaises(RuntimeError):
                restore_backup(backup)
        self.assertEqual(Produit.objects.get().nom, 'État avant restauration')

    def test_queue_worker_and_cross_process_lock(self):
        job = queue_job('backup')
        with self.assertRaises(BackupError):
            queue_job('backup')
        with maintenance_lock() as acquired:
            self.assertTrue(acquired)
            self.assertIsNone(run_pending_job())
        self.assertEqual(run_pending_job().status, 'done')
        job.refresh_from_db()
        self.assertTrue(job.backup.verified_at)
        verification = queue_job('verify', job.backup)
        self.assertEqual(run_pending_job().pk, verification.pk)
        verification.refresh_from_db()
        self.assertEqual(verification.status, 'done')

    def test_interrupted_job_is_reported_without_repeating_it(self):
        abandoned = MaintenanceJob.objects.create(kind='restore', status='running')
        self.assertIsNone(run_pending_job())
        abandoned.refresh_from_db()
        self.assertEqual(abandoned.status, 'failed')
        self.assertTrue(ActivityEvent.objects.filter(event='maintenance.interrupted').exists())

    def test_backup_pages_downloads_and_jobs_require_shared_auth_and_csrf(self):
        backup = create_backup()
        for url in ['/admin/maintenance/', '/admin/maintenance/journal/', '/admin/maintenance/status/',
                    f'/admin/maintenance/backups/{backup.pk}/download/']:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.connect()
        self.assertEqual(self.client.get('/admin/maintenance/').status_code, 200)
        response = self.client.get(f'/admin/maintenance/backups/{backup.pk}/download/')
        self.assertEqual(b''.join(response.streaming_content), backup_path(backup).read_bytes())
        secure = Client(enforce_csrf_checks=True)
        self.assertEqual(secure.post('/admin/maintenance/backups/create/').status_code, 403)
        self.assertEqual(self.client.get('/admin/maintenance/backups/create/').status_code, 405)

    def test_restore_requires_password_and_explicit_confirmation_then_runs_in_worker(self):
        backup = create_backup()
        self.connect()
        url = f'/admin/maintenance/backups/{backup.pk}/restore/'
        for data in [{'password': 'wrong', 'confirmation': 'RESTAURER'}, {'password': self.password, 'confirmation': 'oui'}]:
            self.assertEqual(self.client.post(url, data).status_code, 200)
            self.assertFalse(MaintenanceJob.objects.exists())
        self.assertEqual(self.client.post(url, {'password': self.password, 'confirmation': 'RESTAURER'}).status_code, 302)
        self.product.nom = 'À restaurer'
        self.product.save()
        self.assertEqual(run_pending_job().status, 'done')
        self.assertEqual(Produit.objects.get().nom, 'Produit initial')

    def test_restore_temporarily_blocks_catalogue_but_not_health_or_status(self):
        MaintenanceJob.objects.create(kind='restore', status='running')
        self.assertEqual(self.client.get('/').status_code, 503)
        self.assertEqual(self.client.get('/health/').status_code, 200)
        self.connect()
        self.assertEqual(self.client.get('/admin/maintenance/status/').status_code, 200)
        self.assertEqual(self.client.get('/admin/catalogue/produit/').status_code, 503)

    def test_logs_filter_export_and_password_redaction(self):
        record_event('catalogue', 'test.catalogue', '=FAUSSE_FORMULE')
        record_event('backups', 'test.backup', 'Copie réussie')
        self.connect()
        response = self.client.get('/admin/maintenance/journal/?category=catalogue')
        self.assertContains(response, '=FAUSSE_FORMULE')
        self.assertNotContains(response, 'Copie réussie')
        response = self.client.get('/admin/maintenance/journal/export/?category=catalogue')
        csv = b''.join(response.streaming_content).decode('utf-8-sig')
        self.assertIn("'=FAUSSE_FORMULE", csv)
        self.assertNotIn(self.password, csv)
        request = RequestFactory().post('/admin/login/?password=secret-query', {'password': 'secret-body'})
        try:
            raise RuntimeError('secret-exception')
        except RuntimeError:
            import sys
            record = logging.LogRecord('django.request', logging.ERROR, __file__, 1, 'secret-message', (), sys.exc_info())
        record.request = request
        JournalErrorHandler().emit(record)
        event = ActivityEvent.objects.get(event='system.error')
        serialized = json.dumps(event.details)
        self.assertNotIn('secret', serialized)
        self.assertEqual(event.details['exception'], 'RuntimeError')

    def test_worker_error_keeps_safe_stack_in_journal_and_console(self):
        job = queue_job('backup')
        with patch('catalogue.maintenance.create_backup', side_effect=OSError('secret-exception-text')):
            with self.assertLogs('catalogue.maintenance', level='ERROR') as logs:
                result = run_pending_job()
        self.assertEqual(result.status, 'failed')
        event = ActivityEvent.objects.get(event='maintenance.failed')
        self.assertEqual(event.details['operation'], str(job.pk))
        self.assertEqual(event.details['exception'], 'OSError')
        self.assertTrue(event.details['pile'])
        self.assertIn('run_pending_job', [frame['fonction'] for frame in event.details['pile']])
        for value in (event.message, json.dumps(event.details), ''.join(logs.output)):
            self.assertNotIn('secret-exception-text', value)
        self.assertIn(str(job.pk), ''.join(logs.output))

    def test_daily_schedule_is_enqueued_once_and_logs_follow_retention(self):
        old = record_event('system', 'old', 'Ancien événement')
        ActivityEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=100))
        now = timezone.localtime().replace(hour=3, minute=0, second=0)
        self.config.automatic_backups = True
        self.config.last_scheduled_date = now.date() - timedelta(days=1)
        self.config.save()
        with patch('catalogue.maintenance.timezone.localtime', return_value=now):
            housekeeping()
            housekeeping()
        self.assertEqual(MaintenanceJob.objects.filter(origin='automatic', kind='backup').count(), 1)
        self.assertFalse(ActivityEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(MaintenanceSettings.objects.get(pk=1).worker_seen_at)

    def test_import_verifies_before_it_can_be_restored(self):
        backup = create_backup()
        self.connect()
        response = self.client.post('/admin/maintenance/backups/upload/', {'archive': ContentFile(backup_path(backup).read_bytes(), name='copie.zip')})
        self.assertEqual(response.status_code, 302)
        uploaded = BackupRecord.objects.get(origin='upload')
        self.assertIsNone(uploaded.verified_at)
        self.assertEqual(run_pending_job().status, 'done')
        uploaded.refresh_from_db()
        self.assertTrue(uploaded.verified_at)
        self.assertEqual((uploaded.products, uploaded.documents, uploaded.files), (1, 1, 1))

    def test_delete_is_post_only_with_confirmation_and_never_changes_the_catalogue(self):
        backup = create_backup()
        path = backup_path(backup)
        self.connect()
        url = f'/admin/maintenance/backups/{backup.pk}/delete/'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(path.exists())
        self.client.post(url, {'password': self.password, 'confirmation': 'SUPPRIMER'})
        self.assertFalse(path.exists())
        self.assertEqual(Produit.objects.count(), 1)
        self.assertTrue(self.document.disponible)

    def test_retention_prunes_only_automatic_and_old_protection_archives(self):
        from .backups import backup_directory
        self.config.automatic_retention = 2
        self.config.save()
        for origin, count in [('automatic', 5), ('safety', 5), ('manual', 2), ('upload', 1)]:
            for _ in range(count):
                record = BackupRecord.objects.create(origin=origin, filename=f'sersi-{uuid.uuid4().hex}.zip')
                (backup_directory() / record.filename).write_bytes(b'test fixture')
        housekeeping()
        self.assertEqual(BackupRecord.objects.filter(origin='automatic').count(), 2)
        self.assertEqual(BackupRecord.objects.filter(origin='safety').count(), 3)
        self.assertEqual(BackupRecord.objects.filter(origin='manual').count(), 2)
        self.assertEqual(BackupRecord.objects.filter(origin='upload').count(), 1)
        self.assertEqual(len(list(backup_directory().glob('*.zip'))), 8)

    def test_insufficient_space_fails_before_writing_an_archive(self):
        from types import SimpleNamespace
        with patch('catalogue.backups.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaises(BackupError):
                create_backup()
        self.assertEqual(BackupRecord.objects.count(), 0)

    def test_manual_log_purge_requires_confirmation_and_keeps_recent_events(self):
        old = record_event('system', 'test.old', 'À purger')
        ActivityEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=100))
        recent = record_event('system', 'test.recent', 'À conserver')
        self.connect()
        url = '/admin/maintenance/journal/purge/'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(ActivityEvent.objects.filter(pk=old.pk).exists())
        self.client.post(url, {'password': self.password, 'confirmation': 'PURGER', 'days': 90})
        self.assertFalse(ActivityEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(ActivityEvent.objects.filter(pk=recent.pk).exists())
