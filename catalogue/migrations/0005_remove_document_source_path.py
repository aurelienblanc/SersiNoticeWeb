from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0004_require_document_export_group')]

    operations = [
        migrations.RemoveField(model_name='document', name='ancien_chemin'),
    ]
