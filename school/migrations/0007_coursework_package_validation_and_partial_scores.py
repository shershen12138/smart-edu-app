from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('school', '0006_account_password_recovery'),
    ]

    operations = [
        migrations.AddField(
            model_name='evaluationpackage',
            name='archive_path',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='evaluationpackage',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='judge_packages',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='evaluationpackage',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', '等待验证'),
                    ('validating', '正在验证'),
                    ('ready', '验证通过'),
                    ('error', '验证失败'),
                ],
                db_index=True,
                default='pending',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='evaluationpackage',
            name='validated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='evaluationpackage',
            name='validation_error',
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AlterField(
            model_name='courseworkquestionresult',
            name='score',
            field=models.DecimalField(decimal_places=4, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='courseworkquestionresult',
            name='passed_cases',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='courseworkquestionresult',
            name='total_cases',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='courseworksubmission',
            name='total',
            field=models.DecimalField(decimal_places=4, max_digits=12, null=True),
        ),
    ]
