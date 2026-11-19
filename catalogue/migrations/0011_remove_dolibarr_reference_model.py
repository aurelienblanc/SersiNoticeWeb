from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0010_shared_dolibarr_reference')]
    operations = [migrations.DeleteModel(name='DolibarrReference')]
