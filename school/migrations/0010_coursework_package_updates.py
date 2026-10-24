import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('school', '0009_data_lifecycle_and_teacher_outputs')]

    operations = [
        migrations.CreateModel(
            name='CourseworkPackageUpdate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('changed_path', models.CharField(max_length=300)),
                ('grading_changed', models.BooleanField(default=False)),
                ('document_path', models.CharField(max_length=200)),
                ('document_name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('pending', '等待验证'), ('validating', '正在验证'), ('activated', '已生效'), ('error', '验证失败'), ('superseded', '已失效')], db_index=True, default='pending', max_length=12)),
                ('error', models.CharField(blank=True, max_length=240)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(null=True)),
                ('coursework', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='package_updates', to='school.coursework')),
                ('package', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='package_updates', to='school.evaluationpackage')),
                ('previous_package', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='replaced_by_updates', to='school.evaluationpackage')),
                ('requested_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='package_updates', to='school.user')),
            ],
            options={'ordering': ['-created_at', '-pk']},
        ),
        migrations.CreateModel(
            name='CourseworkGradeHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('snapshot', models.JSONField(default=dict)),
                ('status', models.CharField(max_length=12)),
                ('total', models.DecimalField(decimal_places=4, max_digits=12, null=True)),
                ('error', models.CharField(blank=True, max_length=240)),
                ('results', models.JSONField(default=list)),
                ('finished_at', models.DateTimeField(null=True)),
                ('archived_at', models.DateTimeField(auto_now_add=True)),
                ('package', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='historical_grades', to='school.evaluationpackage')),
                ('package_update', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='archived_grades', to='school.courseworkpackageupdate')),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grade_history', to='school.courseworksubmission')),
            ],
            options={'ordering': ['-archived_at', '-pk']},
        ),
        migrations.AddConstraint(
            model_name='courseworkgradehistory',
            constraint=models.UniqueConstraint(fields=('submission', 'package_update'), name='course_grade_history_update_unique'),
        ),
    ]
