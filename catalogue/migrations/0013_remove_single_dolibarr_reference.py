from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0012_reference_dolibarr')]
    operations = [migrations.RemoveField(model_name='produit', name='reference_dolibarr')]
