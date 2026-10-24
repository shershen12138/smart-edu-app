from django.db import migrations


def seed(apps, schema_editor):
    Dictionary = apps.get_model('school', 'DataDictionary')
    Item = apps.get_model('school', 'DictionaryItem')
    Classroom = apps.get_model('school', 'Classroom')
    for code, name, field, fallback in [('course', '课程', 'course_name', 'Python 程序设计'), ('term', '学期', 'term', '2026 秋季')]:
        dictionary, _ = Dictionary.objects.get_or_create(code=code, defaults={'name': name})
        values = set(Classroom.objects.values_list(field, flat=True)) | {fallback}
        for order, value in enumerate(sorted(v for v in values if v)):
            Item.objects.get_or_create(dictionary=dictionary, value=value, defaults={'label': value, 'order': order})


class Migration(migrations.Migration):
    dependencies = [('school', '0004_coursework_worker_token')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
