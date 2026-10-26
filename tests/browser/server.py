"""Launch browser fixtures in a fresh SQLite directory, never the real catalogue."""
import os
import logging
import secrets
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
temporary_root = ROOT / '.tmp' / 'browser-tests'
temporary_root.mkdir(parents=True, exist_ok=True)

# Explicitly override inherited production configuration before Django loads.
for name in list(os.environ):
    if name.startswith('POSTGRES_'):
        del os.environ[name]
os.environ.update({
    'DJANGO_SETTINGS_MODULE': 'sersi_web.settings',
    'SERSI_DATA_DIR': tempfile.mkdtemp(dir=temporary_root),
    'SERSI_SECRET_KEY': secrets.token_urlsafe(64),
    'SERSI_DEBUG': '1',
    'SERSI_HTTPS': '0',
    'SERSI_TRUST_PROXY': '0',
})

import django
django.setup()

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from catalogue.models import (
    AdministrationAccess, Categorie, Document, DossierCible, MaintenanceSettings,
    Marque, Produit, Systeme, TypeDocument, TypeExport,
)

settings.STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
logging.getLogger('django.server').setLevel(logging.WARNING)
call_command('migrate', verbosity=0, interactive=False)
MaintenanceSettings.objects.create(pk=1, automatic_backups=False)
AdministrationAccess.objects.create(pk=1, password_hash=make_password('Browser-test-only-password-2026!'))
systems = [Systeme.objects.create(nom=name) for name in ('Type 4', 'SSI')]
brands = [Marque.objects.create(nom=name, generique=name == 'Commun') for name in ('Marque A', 'Marque B', 'Commun')]
categories = [Categorie.objects.create(nom=name) for name in ('Centrales', 'Périphériques', 'Accessoires')]
group = TypeExport.objects.create(libelle='Documents techniques')
kind = TypeDocument.objects.create(nom='Notice', type_export=group)
certificate_kind = TypeDocument.objects.create(nom='Certificat', type_export=group)
folder = DossierCible.objects.create(nom='Notices', chemin_relatif='Notices')
child = DossierCible.objects.create(nom='Techniques', chemin_relatif='Techniques', parent=folder)
fixtures = [
    ('AA-4', 'Centrale Alpha', 0, 0, [0], True),
    ('BB-4', 'Détecteur Bêta', 1, 1, [0], True),
    ('AA-SSI', 'Centrale SSI', 0, 0, [1], True),
    ('GEN', 'Accessoire commun', 2, 2, [0, 1], True),
    ('AA-OLD', 'Ancien produit', 0, 1, [0], False),
]
for reference, name, brand, category, compatible, active in fixtures:
    product = Produit.objects.create(reference=reference, nom=name, marque=brands[brand], categorie=categories[category], actif=active)
    product.systemes.set([systems[index] for index in compatible])
    document = Document.objects.create(nom=f'Notice {reference}',
        type_document=certificate_kind if reference == 'GEN' else kind,
        date_expiration=timezone.localdate() - timedelta(days=1) if reference == 'BB-4' else None)
    document.fichier.save(f'{reference}.pdf', ContentFile(b'%PDF-1.4\nBrowser test fixture\n'))
    document.dossiers.add(child)
    product.documents.add(document)

call_command('runserver', '127.0.0.1:8767', use_reloader=False, verbosity=0)
