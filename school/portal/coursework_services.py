from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from school.models import Coursework, CourseworkItem, EvaluationPackage
from school.services import audit
from school.storage import save_private

from .access import allowed


MANUAL_CHAPTER10_ITEMS = [
    {'function': str(number), 'title': f'{number}.py', 'points': 10}
    for number in range(1001, 1006)
]


def save_uploaded_package(actor, data, archive):
    package = EvaluationPackage.objects.filter(digest=data['digest']).first()
    if package:
        if package.status == 'error':
            package.status = 'pending'
            package.validation_error = ''
            package.validated_at = None
            package.active = True
            package.save(
                update_fields=['status', 'validation_error', 'validated_at', 'active']
            )
        return package
    return EvaluationPackage.objects.create(
        code='upload-' + data['digest'][:16],
        name=data['name'][:160],
        owner=actor,
        description=data['description'],
        document_digest=data['document_digest'],
        archive_path=save_private(archive, '.zip'),
        template_path=save_private(data['sample'], '.py'),
        reference_path=save_private(data['reference'], '.py'),
        spec=data['spec'],
        digest=data['digest'],
        status='pending',
    )


@transaction.atomic
def save_work(actor, form):
    candidate = form.save(commit=False)
    if not allowed(actor, candidate.classroom, 'edit'):
        raise PermissionDenied
    old_package = None
    old_mode = None
    if candidate.pk:
        current = Coursework.objects.select_for_update().get(
            pk=candidate.pk, deleted_at__isnull=True
        )
        if current.revision != form.cleaned_data['revision']:
            raise ValidationError('作业已被其他人修改，请刷新后重新编辑。')
        old_package = current.package_id
        old_mode = current.grading_mode
        candidate.revision = current.revision + 1
    else:
        candidate.owner = actor
        candidate.opens_at = timezone.now()
    candidate.status = 'open'
    if form.cleaned_data.get('raw_file'):
        filename = form.cleaned_data.get('document_name')
        package_data = form.cleaned_data.get('package_data')
        manual_data = form.cleaned_data.get('manual_data')
        package = (
            save_uploaded_package(actor, package_data, form.cleaned_data['package_raw'])
            if package_data
            else form.cleaned_data.get('package')
        )
        if (
            candidate.pk
            and current.entries.exists()
            and (
                (package.pk if package else None) != current.package_id
                or manual_data
                or candidate.grading_mode != current.grading_mode
            )
        ):
            raise ValidationError(
                '已有提交，替换文件会改变批阅规则，请新建一份作业；本次修改未保存。'
            )
        candidate.package = package
        if manual_data:
            candidate.materials_path = save_private(form.cleaned_data['materials_raw'], '.zip')
            candidate.materials_name = form.cleaned_data['materials_name'][:200]
        elif candidate.grading_mode == 'automatic':
            candidate.materials_path = ''
            candidate.materials_name = ''
        candidate.description = form.cleaned_data['description']
        candidate.title = Path(filename).stem[:160]
        candidate.document_name = filename[:200]
        candidate.document_path = save_private(
            form.cleaned_data['raw_file'], Path(filename).suffix.lower()
        )
    candidate.save()
    rebuild_items = (
        old_package != candidate.package_id
        or old_mode != candidate.grading_mode
        or bool(form.cleaned_data.get('manual_data'))
    )
    if rebuild_items:
        candidate.items.all().delete()
        if candidate.grading_mode == 'manual':
            specs = MANUAL_CHAPTER10_ITEMS
        elif candidate.package:
            specs = [
                {
                    'function': item['function'],
                    'title': item['function'],
                    'points': item['points'],
                }
                for item in candidate.package.spec
            ]
        else:
            specs = []
        if specs:
            CourseworkItem.objects.bulk_create(
                [
                    CourseworkItem(
                        coursework=candidate,
                        function_name=item['function'],
                        title=item['title'],
                        points=item['points'],
                        order=index,
                    )
                    for index, item in enumerate(specs, 1)
                ]
            )
    audit(actor, 'portal.work.save', str(candidate.pk))
    return candidate


def snapshot(work):
    specs = {item['function']: item for item in work.package.spec} if work.package else {}
    items = [
        {
            **specs.get(item.function_name, {}),
            'function': item.function_name,
            'title': item.title,
            'points': item.points,
            'order': item.order,
        }
        for item in work.items.all()
    ]
    reference = work.package.reference_path if work.package else ''
    ready = bool(
        work.package
        and work.package.status == 'ready'
        and reference
        and items
        and all(
            item.get('inputs')
            and len(item.get('expected', [])) == len(item['inputs'])
            for item in items
        )
    )
    return {
        'title': work.title,
        'revision': work.revision,
        'grading_mode': work.grading_mode,
        'items': items,
        'reference_path': reference,
        'package_id': work.package_id,
        'package_digest': work.package.digest if work.package else '',
        'ready': ready,
        'required_files': [f"{item['function']}.py" for item in items]
        if work.grading_mode == 'manual'
        else [],
        'max_score': sum(i['points'] for i in items),
    }
