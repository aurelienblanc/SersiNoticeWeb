import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import Client, SimpleTestCase, TestCase, override_settings

from .dolibarr import DolibarrClient, DolibarrError, DolibarrRecordType, NoRedirect, match_record
from .dolibarr_config import encrypt_key, legacy_connection
from .models import (
    Categorie, Document, DolibarrSource, DossierCible, Marque,
    Produit, Systeme, TypeDocument, TypeExport,
)


class DolibarrClientTests(SimpleTestCase):
    def setUp(self):
        url = 'https://erp.example.test/doli'
        self.source = DolibarrSource(url=url, cle_chiffree=encrypt_key(url, 'test-api-key-only'))

    @patch('catalogue.dolibarr.build_opener')
    def test_client_only_reads_and_fetches_each_product_once(self, factory):
        factory.return_value.open.side_effect = [
            io.BytesIO(json.dumps({'id': '42', 'ref': 'PR-TEST', 'lines': [
                {'fk_product': '7', 'label': '<b>Produit</b>'}, {'fk_product': '7'}, {'fk_product': 0},
            ]}).encode()),
            io.BytesIO(b'{"ref":"ERP-001"}'),
        ]
        reference, lines = DolibarrClient(self.source).read_record(DolibarrRecordType.PROPOSAL, 'PR-TEST')
        self.assertEqual(reference, 'PR-TEST')
        self.assertEqual([line['reference'] for line in lines], ['ERP-001', 'ERP-001', ''])
        self.assertEqual(lines[0]['label'], 'Produit')
        self.assertEqual(factory.return_value.open.call_count, 2)
        for call in factory.return_value.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Dolapikey'), 'test-api-key-only')
            self.assertNotIn('test-api-key-only', request.full_url)
            self.assertLessEqual(call.kwargs['timeout'], 10)
        self.assertTrue(factory.return_value.open.call_args.args[0].full_url.endswith('/products/7'))

    @patch('catalogue.dolibarr.build_opener')
    def test_order_by_reference_uses_the_order_lines_endpoint_if_needed(self, factory):
        opener = factory.return_value.open
        opener.side_effect = [
            io.BytesIO(b'{"id":"42","ref":"CO-TEST"}'),
            io.BytesIO(b'[{"fk_product":"7"}]'),
            io.BytesIO(b'{"ref":"ERP-001"}'),
        ]
        reference, lines = DolibarrClient(self.source).read_record(DolibarrRecordType.ORDER, 'CO-TEST')
        self.assertEqual(reference, 'CO-TEST')
        self.assertEqual([line['reference'] for line in lines], ['ERP-001'])
        self.assertEqual([call.args[0].selector for call in opener.call_args_list], [
            '/doli/api/index.php/orders/ref/CO-TEST',
            '/doli/api/index.php/orders/42/lines',
            '/doli/api/index.php/products/7',
        ])

    @patch('catalogue.dolibarr.build_opener')
    def test_http_network_and_invalid_response_errors_do_not_disclose_secrets(self, factory):
        failures = [URLError('test-api-key-only'), TimeoutError('test-api-key-only')]
        failures += [HTTPError('https://erp.example.test', code, 'test-api-key-only', {}, io.BytesIO(b'private'))
                     for code in (401, 403, 404, 302, 500)]
        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                factory.return_value.open.side_effect = failure
                with self.assertRaises(DolibarrError) as error:
                    DolibarrClient(self.source).get_json('/proposals/ref/PR-TEST')
                self.assertNotIn('test-api-key-only', str(error.exception))
        factory.return_value.open.side_effect = None
        factory.return_value.open.return_value = io.BytesIO(b'<html>login</html>')
        with self.assertRaises(DolibarrError):
            DolibarrClient(self.source).get_json('/proposals/ref/PR-TEST')
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    @patch('catalogue.dolibarr.build_opener')
    def test_payload_size_deadline_and_proposal_identity_are_checked(self, factory):
        factory.return_value.open.return_value = io.BytesIO(b'x' * 40)
        with patch('catalogue.dolibarr.MAX_RESPONSE_BYTES', 32), self.assertRaises(DolibarrError):
            DolibarrClient(self.source).get_json('/proposals/ref/PR-TEST')
        with patch('catalogue.dolibarr.time.monotonic', return_value=100):
            client = DolibarrClient(self.source)
        with patch('catalogue.dolibarr.time.monotonic', return_value=200), self.assertRaises(DolibarrError):
            client.get_json('/proposals/ref/PR-TEST')
        factory.return_value.open.return_value = io.BytesIO(b'{"ref":"OTHER","lines":[]}')
        with self.assertRaises(DolibarrError):
            DolibarrClient(self.source).read_record(DolibarrRecordType.PROPOSAL, 'PR-TEST')

    def test_key_can_be_read_from_a_local_file_and_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=settings.RUNTIME_DIR) as directory:
            path = Path(directory) / 'api.key'
            path.write_text('local-file-test-key\n', encoding='utf-8')
            with override_settings(SERSI_DOLIBARR_URL=self.source.url, SERSI_DOLIBARR_API_KEY='',
                                   SERSI_DOLIBARR_API_KEY_FILE=str(path)):
                self.assertEqual(legacy_connection(), (self.source.url, 'local-file-test-key'))
        for url in ('', 'ftp://erp.example', 'https://user:password@erp.example', 'https://erp.example?x=1'):
            with self.subTest(url=url), self.assertRaises(DolibarrError):
                DolibarrClient(DolibarrSource(url=url))
        self.source.url = 'https://other.example.test'
        with self.assertRaises(DolibarrError):
            DolibarrClient(self.source)


@override_settings(STORAGES={
                       'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                       'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
                   })
class DolibarrImportTests(TestCase):
    def setUp(self):
        url = 'https://erp.example.test'
        self.source = DolibarrSource.objects.create(
            nom='ERP test', url=url, cle_chiffree=encrypt_key(url, 'not-for-the-browser'),
        )
        directory = tempfile.TemporaryDirectory(dir=settings.RUNTIME_DIR)
        self.addCleanup(directory.cleanup)
        storage = override_settings(MEDIA_ROOT=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)
        brand = Marque.objects.create(nom='Marque ERP')
        category = Categorie.objects.create(nom='Produits ERP')
        system = Systeme.objects.create(nom='Système ERP')
        self.group = TypeExport.objects.create(libelle='Documents techniques')
        kind = TypeDocument.objects.create(nom='Notice', type_export=self.group)
        folder = DossierCible.objects.create(nom='Notices', chemin_relatif='Notices')
        self.products = []
        for number in (1, 2):
            product = Produit.objects.create(reference=f'LOCAL-{number}', reference_dolibarr=f'ERP-{number}',
                nom=f'Produit {number}', marque=brand, categorie=category, actif=number == 1)
            product.systemes.add(system)
            document = Document.objects.create(nom=f'Notice {number}', type_document=kind)
            document.fichier.save(f'notice-{number}.pdf', ContentFile(b'%PDF-1.4\nERP fixture'))
            document.dossiers.add(folder)
            product.documents.add(document)
            self.products.append(product)
        self.lines = [{'line': number, 'reference': f'ERP-{number}', 'label': f'Produit ERP {number}'}
                      for number in (1, 2)]
        self.remote = patch('catalogue.dolibarr.DolibarrClient.read_record', return_value=('PR-TEST', self.lines))
        self.read_record = self.remote.start()
        self.addCleanup(self.remote.stop)

    def load(self, source=None, **fields):
        return self.client.post('/dolibarr/', {'reference': 'PR-TEST', 'source': (source or self.source).pk, **fields})

    def preparation(self, token, **extra):
        return self.client.post('/dolibarr/preparer/', {
            'import_token': token, 'types_export': [self.group.pk],
            'projet': 'PR-TEST', 'client': 'Client test', **extra,
        })

    def test_matches_duplicate_lines_once_and_reports_missing_ambiguous_and_free_lines(self):
        duplicate = self.products[0]
        Produit.objects.create(reference='OTHER', reference_dolibarr='ERP-1', nom='Autre produit',
                               marque=duplicate.marque, categorie=duplicate.categorie)
        self.read_record.return_value = ('PR-TEST', self.lines + [self.lines[1],
            {'line': 4, 'reference': 'MISSING', 'label': 'Sans correspondance'},
            {'line': 5, 'reference': '', 'label': 'Titre', 'reason': 'Ligne libre'},
        ])
        report = match_record(self.source, DolibarrRecordType.PROPOSAL, 'PR-TEST')
        self.assertEqual(report['products'], [self.products[1]])
        self.assertEqual(report['matched_lines'], 2)
        self.assertEqual(len(report['issues']), 3)
        self.assertIn('Plusieurs produits', report['issues'][0]['reason'])

    def test_proposal_to_preview_and_zip_reuses_the_normal_export_flow(self):
        response = self.load()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'not-for-the-browser')
        self.assertContains(response, 'LOCAL-1')
        token = response.context['token']
        preview = self.preparation(token)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(len(preview.context['plan'].fichiers), 2)
        self.assertTrue(preview.context['selection']['inclure_inactifs'])
        self.assertEqual(preview.context['nom_archive'], 'Client test - PR-TEST.zip')
        archive = self.client.post('/exporter/', {'selection': preview.context['token']})
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b''.join(archive.streaming_content))) as zipped:
            self.assertEqual(len(zipped.namelist()), 2)
            self.assertTrue(all(name.startswith('Notices/') for name in zipped.namelist()))
        self.read_record.assert_called_once_with(DolibarrRecordType.PROPOSAL, 'PR-TEST')

    def test_order_keeps_its_type_and_reference_when_retrying_preparation(self):
        self.read_record.return_value = ('CO-TEST', self.lines[:1])
        response = self.load(record_type='orders', reference='CO-TEST')
        self.assertContains(response, 'Commande client CO-TEST')
        self.assertEqual(response.context['selection_form'].initial['projet'], 'CO-TEST')
        self.read_record.assert_called_once_with(DolibarrRecordType.ORDER, 'CO-TEST')
        token = response.context['token']
        retry = self.preparation(token, types_export=[])
        self.assertContains(retry, 'Commande client CO-TEST', status_code=400)
        preview = self.preparation(token, projet='CO-TEST')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context['nom_archive'], 'Client test - CO-TEST.zip')

    def test_unmatched_lines_require_explicit_confirmation_on_the_server(self):
        self.read_record.return_value = ('PR-TEST', self.lines + [{'line': 3, 'reference': 'MISSING', 'label': 'À vérifier'}])
        response = self.load()
        token = response.context['token']
        refused = self.preparation(token)
        self.assertEqual(refused.status_code, 400)
        self.assertIn('confirmer_lignes', refused.context['selection_form'].errors)
        self.assertEqual(self.preparation(token, confirmer_lignes='on').status_code, 200)

    def test_a_changed_mapping_or_tampered_token_cannot_prepare_a_dossier(self):
        token = self.load().context['token']
        self.products[0].reference_dolibarr = 'CHANGED'
        self.products[0].save(update_fields=['reference_dolibarr'])
        self.assertEqual(self.preparation(token).status_code, 409)
        self.assertEqual(self.preparation(token + 'tampered').status_code, 409)

    def test_same_reference_matches_the_same_product_from_any_source(self):
        url = 'https://erp-two.example.test'
        other = DolibarrSource.objects.create(nom='Autre ERP', url=url, cle_chiffree=encrypt_key(url, 'other-key'))
        self.read_record.return_value = ('PR-TEST', self.lines[:1])
        first = self.load()
        second = self.load(other)
        self.assertEqual(first.context['report']['products'], [self.products[0]])
        self.assertEqual(second.context['report']['products'], [self.products[0]])
        self.assertContains(second, 'Autre ERP')
        self.assertNotContains(second, 'other-key')
        self.assertNotContains(second, url)
        self.assertEqual(len(self.preparation(second.context['token']).context['plan'].fichiers), 1)
        other.active = False
        other.save(update_fields=['active'])
        self.assertEqual(self.preparation(second.context['token']).status_code, 409)
        self.assertEqual(self.load(other).status_code, 400)
        self.assertNotContains(self.client.get('/dolibarr/'), 'Autre ERP')
        self.assertEqual(self.read_record.call_count, 2)

    def test_empty_matches_errors_methods_and_csrf_are_handled(self):
        csrf = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post('/dolibarr/', {'reference': 'PR-TEST'}).status_code, 403)
        self.assertEqual(self.client.get('/dolibarr/preparer/').status_code, 405)
        self.assertEqual(self.client.put('/dolibarr/').status_code, 405)
        self.assertEqual(self.client.post('/dolibarr/', {'reference': '../bad'}).status_code, 400)
        self.assertEqual(self.load(record_type='../products').status_code, 400)
        self.read_record.assert_not_called()
        self.assertEqual(self.client.get('/dolibarr/').status_code, 200)
        self.read_record.assert_not_called()
        self.read_record.return_value = ('PR-TEST', [{'line': 1, 'reference': 'MISSING', 'label': 'Inconnu'}])
        response = self.load()
        self.assertContains(response, 'Aucun produit reconnu')
        self.assertNotContains(response, 'class="proposal-selection-form"')
        self.read_record.side_effect = DolibarrError('Connexion indisponible')
        response = self.load()
        self.assertContains(response, 'Connexion indisponible', status_code=400)
        self.assertNotContains(response, 'not-for-the-browser', status_code=400)
