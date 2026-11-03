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

from .dolibarr import DolibarrClient, DolibarrError, NoRedirect, match_proposal
from .models import Categorie, Document, DossierCible, Marque, Produit, Systeme, TypeDocument, TypeExport


@override_settings(SERSI_DOLIBARR_URL='https://erp.example.test/doli',
                   SERSI_DOLIBARR_API_KEY='test-api-key-only', SERSI_DOLIBARR_API_KEY_FILE='')
class DolibarrClientTests(SimpleTestCase):
    @patch('catalogue.dolibarr.build_opener')
    def test_client_only_reads_and_fetches_each_product_once(self, factory):
        factory.return_value.open.side_effect = [
            io.BytesIO(json.dumps({'id': '42', 'ref': 'PR-TEST', 'lines': [
                {'fk_product': '7', 'label': '<b>Produit</b>'}, {'fk_product': '7'}, {'fk_product': 0},
            ]}).encode()),
            io.BytesIO(b'{"ref":"ERP-001"}'),
        ]
        reference, lines = DolibarrClient().proposal('PR-TEST')
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
    def test_http_network_and_invalid_response_errors_do_not_disclose_secrets(self, factory):
        failures = [URLError('test-api-key-only'), TimeoutError('test-api-key-only')]
        failures += [HTTPError('https://erp.example.test', code, 'test-api-key-only', {}, io.BytesIO(b'private'))
                     for code in (401, 403, 404, 302, 500)]
        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                factory.return_value.open.side_effect = failure
                with self.assertRaises(DolibarrError) as error:
                    DolibarrClient().get_json('/proposals/ref/PR-TEST')
                self.assertNotIn('test-api-key-only', str(error.exception))
        factory.return_value.open.side_effect = None
        factory.return_value.open.return_value = io.BytesIO(b'<html>login</html>')
        with self.assertRaises(DolibarrError):
            DolibarrClient().get_json('/proposals/ref/PR-TEST')
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    @patch('catalogue.dolibarr.build_opener')
    def test_payload_size_deadline_and_proposal_identity_are_checked(self, factory):
        factory.return_value.open.return_value = io.BytesIO(b'x' * 40)
        with patch('catalogue.dolibarr.MAX_RESPONSE_BYTES', 32), self.assertRaises(DolibarrError):
            DolibarrClient().get_json('/proposals/ref/PR-TEST')
        with patch('catalogue.dolibarr.time.monotonic', return_value=100):
            client = DolibarrClient()
        with patch('catalogue.dolibarr.time.monotonic', return_value=200), self.assertRaises(DolibarrError):
            client.get_json('/proposals/ref/PR-TEST')
        factory.return_value.open.return_value = io.BytesIO(b'{"ref":"OTHER","lines":[]}')
        with self.assertRaises(DolibarrError):
            DolibarrClient().proposal('PR-TEST')

    def test_key_can_be_read_from_a_local_file_and_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=settings.RUNTIME_DIR) as directory:
            path = Path(directory) / 'api.key'
            path.write_text('local-file-test-key\n', encoding='utf-8')
            with override_settings(SERSI_DOLIBARR_API_KEY='', SERSI_DOLIBARR_API_KEY_FILE=str(path)):
                self.assertEqual(DolibarrClient().key, 'local-file-test-key')
        for url in ('', 'ftp://erp.example', 'https://user:password@erp.example', 'https://erp.example?x=1'):
            with self.subTest(url=url), override_settings(SERSI_DOLIBARR_URL=url), self.assertRaises(DolibarrError):
                DolibarrClient()


@override_settings(SERSI_DOLIBARR_URL='https://erp.example.test', SERSI_DOLIBARR_NAME='ERP test',
                   SERSI_DOLIBARR_API_KEY='not-for-the-browser', SERSI_DOLIBARR_API_KEY_FILE='',
                   STORAGES={
                       'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                       'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
                   })
class DolibarrImportTests(TestCase):
    def setUp(self):
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
        self.remote = patch('catalogue.dolibarr.DolibarrClient.proposal', return_value=('PR-TEST', self.lines))
        self.proposal = self.remote.start()
        self.addCleanup(self.remote.stop)

    def load(self):
        return self.client.post('/dolibarr/', {'reference': 'PR-TEST'})

    def preparation(self, token, **extra):
        return self.client.post('/dolibarr/preparer/', {
            'import_token': token, 'types_export': [self.group.pk],
            'projet': 'PR-TEST', 'client': 'Client test', **extra,
        })

    def test_matches_duplicate_lines_once_and_reports_missing_ambiguous_and_free_lines(self):
        duplicate = self.products[0]
        Produit.objects.create(reference='OTHER', reference_dolibarr='ERP-1', nom='Autre produit',
                               marque=duplicate.marque, categorie=duplicate.categorie)
        self.proposal.return_value = ('PR-TEST', self.lines + [self.lines[1],
            {'line': 4, 'reference': 'MISSING', 'label': 'Sans correspondance'},
            {'line': 5, 'reference': '', 'label': 'Titre', 'reason': 'Ligne libre'},
        ])
        report = match_proposal('PR-TEST')
        self.assertEqual([product.pk for product in report['products']], [self.products[1].pk])
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
        self.proposal.assert_called_once()

    def test_unmatched_lines_require_explicit_confirmation_on_the_server(self):
        self.proposal.return_value = ('PR-TEST', self.lines + [{'line': 3, 'reference': 'MISSING', 'label': 'À vérifier'}])
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

    def test_empty_matches_errors_methods_and_csrf_are_handled(self):
        csrf = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post('/dolibarr/', {'reference': 'PR-TEST'}).status_code, 403)
        self.assertEqual(self.client.get('/dolibarr/preparer/').status_code, 405)
        self.assertEqual(self.client.put('/dolibarr/').status_code, 405)
        self.assertEqual(self.client.post('/dolibarr/', {'reference': '../bad'}).status_code, 400)
        self.proposal.assert_not_called()
        self.assertEqual(self.client.get('/dolibarr/').status_code, 200)
        self.proposal.assert_not_called()
        self.proposal.return_value = ('PR-TEST', [{'line': 1, 'reference': 'MISSING', 'label': 'Inconnu'}])
        response = self.load()
        self.assertContains(response, 'Aucun produit reconnu')
        self.assertNotContains(response, 'class="proposal-selection-form"')
        self.proposal.side_effect = DolibarrError('Connexion indisponible')
        response = self.load()
        self.assertContains(response, 'Connexion indisponible', status_code=400)
        self.assertNotContains(response, 'not-for-the-browser', status_code=400)
