import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings


class DocumentSchemaTests(TransactionTestCase):
    def test_removing_source_path_preserves_documents_products_and_relations(self):
        executor = MigrationExecutor(connection)
        previous = [('catalogue', '0004_require_document_export_group')]
        executor.migrate(previous)
        self.addCleanup(self.restore_current_schema)
        apps = executor.loader.project_state(previous).apps
        with tempfile.TemporaryDirectory(dir=settings.RUNTIME_DIR) as directory:
            pdf = Path(directory) / 'notice.pdf'
            pdf.write_bytes(b'%PDF-1.4\nSchema test')
            group = apps.get_model('catalogue', 'TypeExport').objects.create(libelle='Technique')
            kind = apps.get_model('catalogue', 'TypeDocument').objects.create(nom='Notice', type_export=group)
            brand = apps.get_model('catalogue', 'Marque').objects.create(nom='Marque test')
            category = apps.get_model('catalogue', 'Categorie').objects.create(nom='Catégorie test')
            system = apps.get_model('catalogue', 'Systeme').objects.create(nom='Système test')
            folder = apps.get_model('catalogue', 'DossierCible').objects.create(nom='Notices', chemin_relatif='Notices')
            document = apps.get_model('catalogue', 'Document').objects.create(
                nom='Document conservé', type_document=kind, fichier=pdf.name,
                nom_fichier=pdf.name, ancien_chemin='Z:\\Source\\notice.pdf',
            )
            product = apps.get_model('catalogue', 'Produit').objects.create(
                reference='SCHEMA-01', nom='Produit conservé', marque=brand, categorie=category,
            )
            product.documents.add(document)
            product.systemes.add(system)
            document.dossiers.add(folder)
            self.restore_current_schema()
            from .models import Document, Produit
            current = Document.objects.get(pk=document.pk)
            self.assertEqual(current.nom, 'Document conservé')
            self.assertEqual(current.fichier.name, pdf.name)
            self.assertEqual(current.dossiers.get().pk, folder.pk)
            self.assertEqual(Produit.objects.get(pk=product.pk).documents.get().pk, document.pk)
            self.assertEqual(Produit.objects.get(pk=product.pk).systemes.get().pk, system.pk)
            self.assertEqual(Produit.objects.get(pk=product.pk).reference, 'SCHEMA-01')
            self.assertFalse(Produit.objects.get(pk=product.pk).references_dolibarr.exists())
            self.assertEqual(pdf.read_bytes(), b'%PDF-1.4\nSchema test')
            self.assertNotIn('ancien_chemin', [field.name for field in current._meta.fields])

    @staticmethod
    def restore_current_schema():
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    @override_settings(SERSI_DOLIBARR_URL='https://erp.example.test/api/index.php/',
                       SERSI_DOLIBARR_NAME='ERP historique', SERSI_DOLIBARR_API_KEY='old-test-key')
    def test_migrating_existing_dolibarr_configuration_preserves_the_references(self):
        executor = MigrationExecutor(connection)
        previous = [('catalogue', '0006_produit_reference_dolibarr')]
        executor.migrate(previous)
        self.addCleanup(self.restore_current_schema)
        apps = executor.loader.project_state(previous).apps
        brand = apps.get_model('catalogue', 'Marque').objects.create(nom='Marque test')
        category = apps.get_model('catalogue', 'Categorie').objects.create(nom='Catégorie test')
        product = apps.get_model('catalogue', 'Produit').objects.create(
            reference='SCHEMA-02', nom='Produit ERP', marque=brand, categorie=category,
            reference_dolibarr='REF-HISTORIQUE',
        )
        self.restore_current_schema()
        from .dolibarr_config import decrypt_key
        from .models import DolibarrReference
        mapping = DolibarrReference.objects.select_related('source').get(produit_id=product.pk)
        self.assertEqual(mapping.reference, 'REF-HISTORIQUE')
        self.assertEqual(mapping.source.nom, 'ERP historique')
        self.assertEqual(mapping.source.url, 'https://erp.example.test')
        self.assertTrue(mapping.source.active)
        self.assertEqual(decrypt_key(mapping.source.url, mapping.source.cle_chiffree), 'old-test-key')
