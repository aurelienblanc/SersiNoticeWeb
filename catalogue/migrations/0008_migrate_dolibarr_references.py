from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from catalogue.dolibarr_config import LEGACY_SOURCE_NAME, encrypt_key, legacy_connection


def migrate_references(apps, schema_editor):
    alias = schema_editor.connection.alias
    products = apps.get_model('catalogue', 'Produit').objects.using(alias).exclude(reference_dolibarr='')
    sources = apps.get_model('catalogue', 'DolibarrSource').objects.using(alias)
    references = apps.get_model('catalogue', 'DolibarrReference').objects.using(alias)
    try:
        url, key = legacy_connection()
    except ValidationError:
        url, key = '', ''
    if not url and not products.exists():
        return
    source, _ = sources.get_or_create(
        url=url, defaults={
            'nom': (settings.SERSI_DOLIBARR_NAME or 'Dolibarr') if url else LEGACY_SOURCE_NAME,
            'active': bool(key), 'cle_chiffree': encrypt_key(url, key) if key else '',
        },
    )
    references.bulk_create([
        references.model(produit_id=pk, source_id=source.pk, reference=reference)
        for pk, reference in products.values_list('pk', 'reference_dolibarr')
    ], ignore_conflicts=True)


def restore_legacy_references(apps, schema_editor):
    alias = schema_editor.connection.alias
    product = apps.get_model('catalogue', 'Produit')
    references = apps.get_model('catalogue', 'DolibarrReference').objects.using(alias)
    if references.values('source_id').distinct().count() > 1:
        raise IrreversibleError('Les références de plusieurs ERP ne peuvent pas être regroupées dans un seul champ.')
    product.objects.using(alias).bulk_update([
        product(pk=pk, reference_dolibarr=reference)
        for pk, reference in references.values_list('produit_id', 'reference')
    ], ['reference_dolibarr'])


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0007_dolibarr_sources')]
    operations = [migrations.RunPython(migrate_references, restore_legacy_references)]
