import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import ActivityEvent, Categorie, Document, ExportRecord, Marque, Produit, TypeDocument, TypeExport


class DocumentLibraryTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=settings.RUNTIME_DIR)
        self.addCleanup(directory.cleanup)
        storage = override_settings(MEDIA_ROOT=Path(directory.name), STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        })
        storage.enable()
        self.addCleanup(storage.disable)
        self.brand = Marque.objects.create(nom='Marque A')
        self.other_brand = Marque.objects.create(nom='Marque B')
        category = Categorie.objects.create(nom='Centrales')
        group = TypeExport.objects.create(libelle='Documents techniques')
        self.kind = TypeDocument.objects.create(nom='Notice technique', type_export=group)
        self.alpha = Produit.objects.create(reference='A-100', nom='Centrale Alpha', marque=self.brand, categorie=category)
        self.beta = Produit.objects.create(reference='B-200', nom='Centrale Bêta', marque=self.other_brand, categorie=category)
        self.archived = Produit.objects.create(reference='A-OLD', nom='Ancienne centrale', marque=self.brand, categorie=category, actif=False)
        self.alpha_doc = self.document('Notice Alpha', [self.alpha], 'alpha.pdf')
        self.beta_doc = self.document('Notice Bêta', [self.beta], 'beta.pdf')
        self.shared_doc = self.document('Notice commune', [self.alpha, self.beta], 'commune.pdf')
        self.archived_doc = self.document('Notice archivée', [self.archived], 'ancienne.pdf',
            date_expiration=timezone.localdate() - timedelta(days=1))

    def document(self, name, products, filename=None, **kwargs):
        document = Document.objects.create(nom=name, type_document=self.kind, **kwargs)
        if filename:
            document.fichier.save(filename, ContentFile(b'%PDF-1.4\nDocument de test'))
        document.produits.set(products)
        return document

    def result_ids(self, response):
        return [result['document'].pk for result in response.context['results']]

    def test_public_library_lists_each_document_once_and_keeps_unlinked_documents(self):
        unlinked = self.document('Document commun non associé', [], 'sans-produit.pdf')
        response = self.client.get('/documents/')
        self.assertEqual(response.status_code, 200)
        ids = self.result_ids(response)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 5)
        self.assertIn(unlinked.pk, ids)
        self.assertContains(response, 'Aucun produit associé')
        self.assertContains(response, 'Inactif')
        self.assertContains(response, 'Expiré le')

    def test_brand_and_partial_reference_must_match_the_same_product(self):
        response = self.client.get('/documents/', {'marque': self.brand.pk, 'reference': 'a-1'})
        self.assertCountEqual(self.result_ids(response), [self.alpha_doc.pk, self.shared_doc.pk])
        shared = next(result for result in response.context['results'] if result['document'].pk == self.shared_doc.pk)
        self.assertEqual([product.pk for product in shared['products']], [self.alpha.pk])
        response = self.client.get('/documents/', {'marque': self.brand.pk, 'reference': 'B-200'})
        self.assertEqual(self.result_ids(response), [])
        self.assertContains(response, 'Aucun document trouvé.')
        response = self.client.get('/documents/', {'marque': self.other_brand.pk})
        self.assertCountEqual(self.result_ids(response), [self.beta_doc.pk, self.shared_doc.pk])

    def test_missing_files_are_identified_without_view_or_download_links(self):
        Path(self.alpha_doc.fichier.path).unlink()
        response = self.client.get('/documents/', {'reference': self.alpha.reference})
        unavailable = next(result for result in response.context['results'] if result['document'].pk == self.alpha_doc.pk)
        self.assertFalse(unavailable['available'])
        self.assertContains(response, 'Fichier à déposer')
        self.assertNotContains(response, f'/documents/{self.alpha_doc.pk}/consulter/')
        self.assertNotContains(response, f'/documents/{self.alpha_doc.pk}/telecharger/')

    def test_document_type_filter_works_alone_and_with_brand_and_reference(self):
        certificate = TypeDocument.objects.create(nom='Certificat', type_export=self.kind.type_export)
        self.shared_doc.type_document = certificate
        self.shared_doc.save(update_fields=['type_document'])
        unlinked = self.document('Certificat sans produit', [], 'certificat.pdf')
        unlinked.type_document = certificate
        unlinked.save(update_fields=['type_document'])
        response = self.client.get('/documents/', {'type_document': certificate.pk})
        self.assertCountEqual(self.result_ids(response), [self.shared_doc.pk, unlinked.pk])
        query = {'marque': self.brand.pk, 'reference': 'a-1', 'type_document': certificate.pk}
        response = self.client.get('/documents/', query)
        self.assertEqual(self.result_ids(response), [self.shared_doc.pk])
        self.assertEqual([product.pk for product in response.context['results'][0]['products']], [self.alpha.pk])
        self.assertEqual(str(response.context['form']['type_document'].value()), str(certificate.pk))
        response = self.client.get('/documents/', {**query, 'type_document': self.kind.pk})
        self.assertEqual(self.result_ids(response), [self.alpha_doc.pk])
        response = self.client.get('/documents/', {'type_document': ''})
        self.assertEqual(len(self.result_ids(response)), 5)

    def test_invalid_filters_are_rejected_with_a_readable_form(self):
        for query in (
            {'marque': 'invalid'}, {'marque': 999999}, {'reference': 'A' * 256},
            {'type_document': 'invalid'}, {'type_document': 999999},
        ):
            with self.subTest(query=query):
                response = self.client.get('/documents/', query)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.context['form'].errors)
                self.assertEqual(self.result_ids(response), [])

    @patch('catalogue.document_views.PAGE_SIZE', 2)
    def test_pagination_retains_filters_and_handles_invalid_page_numbers(self):
        query = {'marque': self.brand.pk, 'reference': 'A', 'type_document': self.kind.pk}
        response = self.client.get('/documents/', query)
        self.assertEqual(response.context['page'].paginator.count, 3)
        self.assertEqual(len(self.result_ids(response)), 2)
        self.assertContains(response, f'marque={self.brand.pk}&amp;reference=A&amp;type_document={self.kind.pk}&amp;page=2')
        response = self.client.get('/documents/', {**query, 'page': 999})
        self.assertEqual(response.context['page'].number, 2)
        self.assertEqual(len(self.result_ids(response)), 1)

    def test_search_does_not_query_products_separately_for_each_document(self):
        for index in range(20):
            self.document(f'Notice {index}', [self.alpha], f'notice-{index}.pdf')
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/documents/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.result_ids(response)), 24)
        self.assertLessEqual(len(queries), 8)

    def test_pdf_can_be_viewed_inline_or_downloaded_and_actions_are_logged(self):
        response = self.client.get(f'/documents/{self.alpha_doc.pk}/consulter/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], 'inline; filename="alpha.pdf"')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        response = self.client.get(f'/documents/{self.alpha_doc.pk}/telecharger/')
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="alpha.pdf"')
        b''.join(response.streaming_content)
        self.assertTrue(ActivityEvent.objects.filter(event='document.viewed', details__document=self.alpha_doc.pk).exists())
        self.assertTrue(ActivityEvent.objects.filter(event='document.downloaded', details__document=self.alpha_doc.pk).exists())
        self.assertFalse(ExportRecord.objects.exists())

    def test_non_pdf_is_downloaded_and_missing_files_return_404(self):
        html = self.document('Document HTML', [self.alpha], 'document.html')
        response = self.client.get(f'/documents/{html.pk}/consulter/')
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        b''.join(response.streaming_content)
        missing = self.document('Fichier absent', [self.alpha])
        self.assertEqual(self.client.get(f'/documents/{missing.pk}/consulter/').status_code, 404)
        self.assertEqual(self.client.get('/documents/999999/consulter/').status_code, 404)
        Path(self.alpha_doc.fichier.path).unlink()
        self.assertEqual(self.client.get(f'/documents/{self.alpha_doc.pk}/consulter/').status_code, 404)

    def test_search_and_document_access_are_get_only(self):
        for path in ('/documents/', f'/documents/{self.alpha_doc.pk}/consulter/', f'/documents/{self.alpha_doc.pk}/telecharger/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 405)
