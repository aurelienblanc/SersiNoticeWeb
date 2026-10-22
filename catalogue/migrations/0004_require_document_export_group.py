from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('catalogue', '0003_activityevent_backuprecord_maintenancesettings_and_more')]

    operations = [
        migrations.AlterField(
            model_name='typedocument',
            name='type_export',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='catalogue.typeexport',
                verbose_name='type d’export',
            ),
        ),
    ]
