from django.db import migrations, models


def move_references_to_products(apps, schema_editor):
    alias = schema_editor.connection.alias
    product = apps.get_model('catalogue', 'Produit')
    references = apps.get_model('catalogue', 'DolibarrReference').objects.using(alias)
    by_product = {}
    for product_id, reference in references.values_list('produit_id', 'reference').iterator():
        if by_product.setdefault(product_id, reference) != reference:
            raise ValueError(
                f'Le produit {product_id} possède des références Dolibarr différentes selon la source. '
                'Alignez ses références avant de relancer la mise à jour.'
            )
    product.objects.using(alias).bulk_update([
        product(pk=pk, reference_dolibarr=reference) for pk, reference in by_product.items()
    ], ['reference_dolibarr'])


def restore_references_by_source(apps, schema_editor):
    alias = schema_editor.connection.alias
    products = apps.get_model('catalogue', 'Produit').objects.using(alias).exclude(reference_dolibarr='')
    if not products.exists():
        return
    sources = apps.get_model('catalogue', 'DolibarrSource').objects.using(alias)
    source_ids = list(sources.values_list('pk', flat=True))
    if not source_ids:
        source_ids = [sources.create(nom='Dolibarr historique', url='', active=False).pk]
    reference_model = apps.get_model('catalogue', 'DolibarrReference')
    reference_model.objects.using(alias).bulk_create([
        reference_model(produit_id=pk, source_id=source_id, reference=reference)
        for pk, reference in products.values_list('pk', 'reference_dolibarr')
        for source_id in source_ids
    ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0009_remove_legacy_dolibarr_reference')]
    operations = [
        migrations.AddField(
            model_name='produit', name='reference_dolibarr',
            field=models.CharField(
                'référence Dolibarr', max_length=255, blank=True, default='', db_index=True,
                help_text='Référence exacte de ce produit, commune à toutes les sources Dolibarr.',
            ),
        ),
        migrations.RunPython(move_references_to_products, restore_references_by_source),
    ]
