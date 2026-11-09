import django.db.models.deletion
from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def copy_references(apps, schema_editor):
    alias = schema_editor.connection.alias
    products = apps.get_model('catalogue', 'Produit').objects.using(alias).exclude(reference_dolibarr='')
    reference_model = apps.get_model('catalogue', 'ReferenceDolibarr')
    reference_model.objects.using(alias).bulk_create([
        reference_model(produit_id=pk, reference=reference)
        for pk, reference in products.values_list('pk', 'reference_dolibarr')
    ])


def restore_single_reference(apps, schema_editor):
    alias = schema_editor.connection.alias
    product = apps.get_model('catalogue', 'Produit')
    references = apps.get_model('catalogue', 'ReferenceDolibarr').objects.using(alias).order_by()
    by_product = {}
    for product_id, reference in references.values_list('produit_id', 'reference').iterator():
        if product_id in by_product:
            raise IrreversibleError('Le format précédent accepte une seule référence Dolibarr par produit.')
        by_product[product_id] = reference
    product.objects.using(alias).bulk_update([
        product(pk=pk, reference_dolibarr=reference) for pk, reference in by_product.items()
    ], ['reference_dolibarr'])


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0011_remove_dolibarr_reference_model')]
    operations = [
        migrations.CreateModel(
            name='ReferenceDolibarr',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.CharField(db_index=True, max_length=255, verbose_name='référence')),
                ('produit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='references_dolibarr', to='catalogue.produit')),
            ],
            options={
                'ordering': ['reference'],
                'verbose_name': 'référence Dolibarr',
                'verbose_name_plural': 'références Dolibarr',
                'constraints': [
                    models.UniqueConstraint(fields=('produit', 'reference'), name='unique_dolibarr_reference_per_product'),
                ],
            },
        ),
        migrations.RunPython(copy_references, restore_single_reference),
    ]
