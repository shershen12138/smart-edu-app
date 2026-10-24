import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('school', '0010_coursework_package_updates')]

    operations = [
        migrations.AlterField(
            model_name='courseworkpackageupdate',
            name='package',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='package_updates',
                to='school.evaluationpackage',
            ),
        ),
        migrations.AlterField(
            model_name='courseworkpackageupdate',
            name='previous_package',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='replaced_by_updates',
                to='school.evaluationpackage',
            ),
        ),
        migrations.AddField(
            model_name='courseworkpackageupdate',
            name='materials_path',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='courseworkpackageupdate',
            name='previous_materials_path',
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
