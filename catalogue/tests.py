import io
import sqlite3
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .exports import build_plan, create_archive, folder_path
from .forms import SelectionForm
from .management.commands.import_legacy import FileResolver
from .models import Categorie, Document, DossierCible, ExportRecord, Marque, Produit, Systeme, TypeDocument, TypeExport
from .views import TOKEN_SALT


class ExportTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=settings.RUNTIME_DIR)
        self.addCleanup(self.temp.cleanup)
        override = override_settings(MEDIA_ROOT=Path(self.temp.name), STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        })
        override.enable()
        self.addCleanup(override.disable)
        self.brand = Marque.objects.create(nom='SERSI')
        self.category = Categorie.objects.create(nom='Alarmes')
        self.system = Systeme.objects.create(nom='Type 4')
        self.export = TypeExport.objects.create(libelle='DOE')
        self.kind = TypeDocument.objects.create(nom='Notice', type_export=self.export)
        self.folder = DossierCible.objects.create(nom='Notices', chemin_relatif='Notices')
        self.child = DossierCible.objects.create(nom='ECS', chemin_relatif='ECS', parent=self.folder)
        self.product = Produit.objects.create(reference='REF-01', nom='Centrale', marque=self.brand, categorie=self.category)
        self.product.systemes.add(self.system)
        self.doc = self.new_document('Notice', 'notice.pdf')
        self.data = {'produits': [self.product.pk], 'types_export': [self.export.pk], 'projet': 'Chantier', 'client': 'Exemple'}

    def new_document(self, name, filename=None, **kwargs):
        doc = Document.objects.create(nom=name, type_document=self.kind, **kwargs)
        if filename:
            doc.fichier.save(filename, ContentFile(b'%PDF-1.4\nDocument de test'))
        doc.dossiers.add(self.child)
        self.product.documents.add(doc)
        return doc

    def plan(self, include_expired=True):
        return build_plan(Produit.objects.filter(pk=self.product.pk), TypeExport.objects.filter(pk=self.export.pk), include_expired)

    def selection(self):
        form = SelectionForm(self.data)
        self.assertTrue(form.is_valid(), form.errors)
        return form.selection()

    def test_public_catalogue_and_protected_admin(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/health/').status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_archive_contains_only_documents_at_target_paths(self):
        other = Produit.objects.create(reference='REF-02', nom='Second', marque=self.brand, categorie=self.category)
        other.documents.add(self.doc)
        plan = build_plan(Produit.objects.all(), TypeExport.objects.all())
        self.assertEqual(len(plan.fichiers), 1)
        archive, filename = create_archive(plan, self.selection())
        self.assertEqual(filename, 'Exemple - Chantier.zip')
        self.addCleanup(archive.close)
        with zipfile.ZipFile(archive) as contents:
            self.assertEqual(contents.namelist(), ['Notices/ECS/notice.pdf'])
            self.assertEqual(contents.read('Notices/ECS/notice.pdf'), b'%PDF-1.4\nDocument de test')
            self.assertEqual(contents.testzip(), None)

    def test_same_filename_is_not_overwritten(self):
        self.new_document('Second document', 'NOTICE.pdf')
        names = [item.chemin.casefold() for item in self.plan().fichiers]
        self.assertEqual(len(set(names)), 2)
        self.assertTrue(any('_2.pdf' in name for name in names))

    def test_tree_preview_matches_zip_paths_with_nested_and_duplicate_files(self):
        self.doc.dossiers.add(self.folder)
        self.new_document('Second document', 'NOTICE.pdf')
        other = Produit.objects.create(reference='REF-02', nom='Second', marque=self.brand, categorie=self.category)
        other.documents.add(self.doc)
        preview = self.client.post('/preparer/', {**self.data, 'produits': [self.product.pk, other.pk]})
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'aria-controls="archive-list"')
        self.assertContains(preview, 'aria-controls="archive-tree"')
        tree = preview.context['arborescence']
        self.assertEqual(tree['nombre_fichiers'], 3)
        self.assertEqual([folder['nom'] for folder in tree['dossiers']], ['Notices'])
        notices = tree['dossiers'][0]
        self.assertEqual([folder['nom'] for folder in notices['dossiers']], ['ECS'])
        paths = {f"Notices/{entry['nom']}" for entry in notices['fichiers']}
        paths.update(f"Notices/ECS/{entry['nom']}" for entry in notices['dossiers'][0]['fichiers'])
        self.assertEqual(paths, {'Notices/notice.pdf', 'Notices/ECS/notice.pdf', 'Notices/ECS/NOTICE_2.pdf'})
        response = self.client.post('/exporter/', {'selection': preview.context['token']})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            self.assertEqual(set(archive.namelist()), paths)

    def test_unavailable_files_do_not_create_tree_folders(self):
        Path(self.doc.fichier.path).unlink()
        preview = self.client.post('/preparer/', self.data)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context['arborescence'], {'dossiers': [], 'fichiers': [], 'nombre_fichiers': 0})
        self.assertContains(preview, 'Aucun fichier disponible.')
        self.assertNotContains(preview, 'id="archive-view-switch"')

    def test_expired_documents_are_included_unless_exclusion_is_checked(self):
        self.doc.date_expiration = timezone.localdate() - timedelta(days=1)
        self.doc.save()
        self.new_document('Document valide', 'valide.pdf')
        self.assertEqual(len(self.plan().fichiers), 2)
        for excluded in (False, True):
            with self.subTest(excluded=excluded):
                data = {**self.data, 'exclure_expires': 'on'} if excluded else self.data
                preview = self.client.post('/preparer/', data)
                self.assertEqual(preview.status_code, 200)
                if excluded:
                    self.assertContains(preview, '1 document expiré exclu')
                else:
                    self.assertContains(preview, 'Des documents expirés sont inclus')
                    self.assertContains(preview, 'Expiré le')
                response = self.client.post('/exporter/', {'selection': preview.context['token']})
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
                    self.assertIn('Notices/ECS/valide.pdf', archive.namelist())
                    self.assertEqual('Notices/ECS/notice.pdf' in archive.namelist(), not excluded)

    def test_zip_filename_uses_client_and_project_when_provided(self):
        cases = [
            ('', '', 'Dossier documentaire.zip'),
            ('Client', '', 'Client.zip'),
            ('', 'Projet', 'Projet.zip'),
            ('Client', 'Projet', 'Client - Projet.zip'),
            ('  Client  ', '  Projet  ', 'Client - Projet.zip'),
            ('Client/Agence', 'Projet:Lot', 'Client_Agence - Projet_Lot.zip'),
        ]
        for client, project, filename in cases:
            with self.subTest(client=client, project=project):
                preview = self.client.post('/preparer/', {**self.data, 'client': client, 'projet': project})
                self.assertEqual(preview.status_code, 200)
                self.assertContains(preview, filename)
                response = self.client.post('/exporter/', {'selection': preview.context['token']})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Disposition'], f'attachment; filename="{filename}"')
                b''.join(response.streaming_content)

    def test_expiration_today_is_still_valid(self):
        self.doc.date_expiration = timezone.localdate()
        self.doc.save()
        self.assertEqual(len(self.plan(False).fichiers), 1)

    def test_missing_document_requires_explicit_confirmation(self):
        self.new_document('Document absent')
        preview = self.client.post('/preparer/', self.data)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'Document absent')
        token = preview.context['token']
        self.assertEqual(self.client.post('/exporter/', {'selection': token}).status_code, 409)
        response = self.client.post('/exporter/', {'selection': token, 'accepter_incomplet': 'on'})
        self.assertEqual(response.status_code, 200)
        contents = b''.join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            self.assertEqual(archive.namelist(), ['Notices/ECS/notice.pdf'])
        self.assertTrue(ExportRecord.objects.get().incomplet)

    def test_file_removed_after_preview_is_detected_again(self):
        preview = self.client.post('/preparer/', self.data)
        Path(self.doc.fichier.path).unlink()
        self.assertEqual(self.client.post('/exporter/', {'selection': preview.context['token']}).status_code, 409)

    def test_invalid_or_expired_signature_is_rejected(self):
        self.assertEqual(self.client.post('/exporter/', {'selection': 'forged'}).status_code, 400)
        with patch('django.core.signing.time.time', return_value=1):
            token = signing.dumps(self.selection(), salt=TOKEN_SALT)
        self.assertEqual(self.client.post('/exporter/', {'selection': token}).status_code, 400)

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/preparer/', self.data).status_code, 403)

    def test_inactive_or_unrelated_products_cannot_be_forged(self):
        self.product.actif = False
        self.product.save()
        self.assertFalse(SelectionForm(self.data).is_valid())
        self.assertTrue(SelectionForm({**self.data, 'inclure_inactifs': True}).is_valid())
        other = Systeme.objects.create(nom='Autre système')
        self.assertFalse(SelectionForm({**self.data, 'inclure_inactifs': True, 'systeme': other.pk}).is_valid())

    def test_generic_brand_is_allowed_with_other_brands(self):
        selected = Marque.objects.create(nom='Autre marque')
        self.brand.generique = True
        self.brand.save()
        self.assertTrue(SelectionForm({**self.data, 'marque': selected.pk}).is_valid())

    def test_empty_selection_or_export_types_is_rejected(self):
        self.assertEqual(self.client.post('/preparer/', {**self.data, 'produits': []}).status_code, 400)
        self.assertEqual(self.client.post('/preparer/', {**self.data, 'types_export': []}).status_code, 400)

    def test_only_selected_export_type_is_included(self):
        other = TypeExport.objects.create(libelle='Commercial')
        self.assertFalse(build_plan(Produit.objects.all(), TypeExport.objects.filter(pk=other.pk)).fichiers)

    def test_unmapped_legacy_type_is_reported_and_requires_incomplete_confirmation(self):
        kind = TypeDocument.objects.create(nom='Ancien type sans groupe')
        document = self.new_document('PDF non classé', 'non-classe.pdf')
        document.type_document = kind
        document.save()
        preview = self.client.post('/preparer/', self.data)
        self.assertContains(preview, 'PDF non classé')
        self.assertContains(preview, 'Type de document sans groupe')
        plan = preview.context['plan']
        self.assertEqual(len(plan.fichiers), 1)
        self.assertEqual(len(plan.indisponibles), 1)
        token = preview.context['token']
        self.assertEqual(self.client.post('/exporter/', {'selection': token}).status_code, 409)
        response = self.client.post('/exporter/', {'selection': token, 'accepter_incomplet': 'on'})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            self.assertEqual(archive.namelist(), ['Notices/ECS/notice.pdf'])
        self.assertTrue(ExportRecord.objects.get().incomplet)

    def test_long_pdf_names_keep_extension_in_zip_and_individual_download(self):
        self.doc.nom_fichier = 'A' * 151 + '.pdf'
        self.doc.save()
        expected = 'A' * 146 + '.pdf'
        plan = self.plan()
        self.assertEqual(plan.fichiers[0].chemin, f'Notices/ECS/{expected}')
        output, _ = create_archive(plan, self.selection())
        with output, zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), [f'Notices/ECS/{expected}'])
        response = self.client.get(f'/documents/{self.doc.pk}/telecharger/')
        self.assertEqual(response['Content-Disposition'], f'attachment; filename="{expected}"')
        b''.join(response.streaming_content)

    def test_long_filename_collisions_preserve_extension_and_limit(self):
        self.doc.nom_fichier = 'A' * 151 + '.pdf'
        self.doc.save()
        other = self.new_document('Second PDF', 'second.pdf')
        other.nom_fichier = 'A' * 150 + 'B.pdf'
        other.save()
        names = [Path(item.chemin).name for item in self.plan().fichiers]
        self.assertEqual(names, ['A' * 146 + '.pdf', 'A' * 144 + '_2.pdf'])
        self.assertTrue(all(len(name) == 150 for name in names))

    def test_path_traversal_and_folder_cycles_are_rejected(self):
        self.child.chemin_relatif = '../secret'
        with self.assertRaises(ValidationError):
            self.child.full_clean()
        self.child.chemin_relatif = 'ECS'
        self.child.save()
        self.folder.parent = self.child
        with self.assertRaises(ValidationError):
            self.folder.full_clean()
        self.folder.save()  # Simulate bad legacy data bypassing model validation.
        with self.assertRaises(ValidationError):
            folder_path(DossierCible.objects.get(pk=self.child.pk))

    @override_settings(SERSI_EXPORT_MAX_BYTES=1)
    def test_export_size_is_limited(self):
        with self.assertRaises(ValidationError):
            self.plan()

    def test_private_media_is_not_routed_and_download_is_attachment(self):
        self.assertEqual(self.client.get('/protected-media/' + self.doc.fichier.name).status_code, 404)
        response = self.client.get(f'/documents/{self.doc.pk}/telecharger/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        b''.join(response.streaming_content)  # The test client closes the stream and request once.


class LegacyImportTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=settings.RUNTIME_DIR)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / 'legacy.sqlite'
        fixture = Path(__file__).with_name('testdata') / 'legacy.sql'
        database = sqlite3.connect(self.source)
        database.executescript(fixture.read_text(encoding='utf-8'))
        database.close()
        self.report = self.directory / 'report.csv'

    def test_legacy_import_preserves_relations_and_source(self):
        before = self.source.read_bytes()
        call_command('import_legacy', str(self.source), report=self.report, stdout=io.StringIO())
        self.assertEqual(Produit.objects.count(), 3)
        self.assertEqual(Document.objects.count(), 3)
        self.assertEqual(Produit.systemes.through.objects.count(), 4)
        self.assertEqual(Produit.documents.through.objects.count(), 4)
        self.assertEqual(Document.dossiers.through.objects.count(), 4)
        self.assertEqual(self.source.read_bytes(), before)
        # PostgreSQL sequences must allow new records after importing explicit IDs.
        self.assertGreater(Marque.objects.create(nom='Nouvelle marque').pk, 9)
        with self.assertRaises(CommandError):
            call_command('import_legacy', str(self.source), report=self.report, stdout=io.StringIO())

    def test_dry_run_does_not_keep_catalogue_data(self):
        call_command('import_legacy', str(self.source), dry_run=True, report=self.report, stdout=io.StringIO())
        self.assertFalse(Produit.objects.exists())
        self.assertFalse(Document.objects.exists())

    def test_import_failure_rolls_back_catalogue(self):
        db = sqlite3.connect(self.source)
        db.execute('UPDATE DossierCible SET parent_id=id WHERE id=(SELECT MIN(id) FROM DossierCible)')
        db.commit()
        db.close()
        with self.assertRaises(CommandError):
            call_command('import_legacy', str(self.source), report=self.report, stdout=io.StringIO())
        self.assertFalse(Produit.objects.exists())
        self.assertFalse(Marque.objects.exists())

    def test_resolver_refuses_ambiguous_files_and_outside_paths(self):
        root = self.directory / 'docs'
        (root / 'a').mkdir(parents=True)
        (root / 'b').mkdir()
        (root / 'a' / 'notice.pdf').write_bytes(b'a')
        (root / 'b' / 'notice.pdf').write_bytes(b'b')
        outside = self.directory / 'secret.pdf'
        outside.write_bytes(b'private')
        resolver = FileResolver(root, ['Z:\\Documents=' + str(root)])
        self.assertIsNone(resolver.resolve('X:\\notice.pdf')[0])
        self.assertIsNone(resolver.resolve(str(outside))[0])
        self.assertEqual(resolver.resolve('Z:\\Documents\\a\\notice.pdf')[0], (root / 'a' / 'notice.pdf').resolve())
