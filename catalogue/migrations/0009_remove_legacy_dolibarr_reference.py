from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0008_migrate_dolibarr_references')]
    operations = [migrations.RemoveField(model_name='produit', name='reference_dolibarr')]
