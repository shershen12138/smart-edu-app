from collections import Counter
from copy import deepcopy
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from school.models import (
    Coursework,
    CourseworkGradeHistory,
    CourseworkItem,
    CourseworkPackageUpdate,
    CourseworkQuestionResult,
    CourseworkSubmission,
)
from school.services import audit
from school.storage import read_private_bytes, save_private

from .coursework_services import save_uploaded_package, snapshot
from .parsers import (
    manual_archive_files,
    parse_manual_materials_archive,
    parse_package_archive,
    replace_manual_member,
    replace_package_member,
)


def package_update_display(work, limit=10):
    """Return one actionable alert and recent immutable update history for teachers."""
    updates = list(
        work.package_updates.select_related('package').order_by('-created_at', '-pk')[:limit]
    )
    alert = None
    for update in updates:
        counts = Counter(update.archived_grades.values_list('submission__status', flat=True))
        total = sum(counts.values())
        success = counts['done']
        failed = counts['error']
        remaining = max(0, total - success - failed)
        update.regrade_progress = {
            'total': total,
            'success': success,
            'failed': failed,
            'remaining': remaining,
        }
        if alert is not None:
            continue
        if (
            (
                update.status in ('pending', 'validating', 'error')
                and update.previous_package_id == work.package_id
            )
            or update.status == 'activated'
            and update.grading_changed
            and (remaining or failed)
        ):
            alert = update
    return alert, updates


def _validation_message(code):
    messages = {
        'DOCKER_UNAVAILABLE': 'Docker 服务不可用，请恢复后重新验证。',
        'REFERENCE_TLE': '参考答案运行超时。',
        'REFERENCE_MLE': '参考答案运行时超出内存限制。',
        'REFERENCE_OLE': '参考答案输出过多。',
        'REFERENCE_RE': '参考答案运行异常。',
        'REFERENCE_OUTPUT_INVALID': '参考答案返回了无法识别的验证结果。',
        'REFERENCE_RESULT_COUNT_MISMATCH': '参考答案返回的题目数量不匹配。',
        'REFERENCE_CASE_COUNT_MISMATCH': '参考答案返回的用例数量不匹配。',
        'REFERENCE_VALIDATION_FAILED': '参考答案验证失败。',
    }
    return messages.get(code, code)


def _archive_results(entry):
    results = []
    for question in entry.questions.prefetch_related('cases'):
        results.append(
            {
                'function': question.function_name,
                'title': question.title,
                'points': question.points,
                'score': str(question.score) if question.score is not None else None,
                'verdict': question.verdict,
                'passed_cases': question.passed_cases,
                'total_cases': question.total_cases,
                'feedback': question.feedback,
                'cases': [
                    {
                        'order': case.order,
                        'verdict': case.verdict,
                        'elapsed_ms': case.elapsed_ms,
                        'actual_output': case.actual_output,
                    }
                    for case in question.cases.all()
                ],
            }
        )
    return results


@transaction.atomic
def activate_package_update(update_id):
    work_id = CourseworkPackageUpdate.objects.values_list('coursework_id', flat=True).get(
        pk=update_id
    )
    # Serialize changes to a coursework before locking its individual update.
    work = Coursework.objects.select_for_update().get(pk=work_id)
    update = (
        CourseworkPackageUpdate.objects.select_for_update()
        .select_related('package', 'previous_package')
        .get(pk=update_id)
    )
    if update.status not in ('pending', 'validating'):
        return update
    if update.package.status != 'ready':
        raise ValidationError('新批阅包尚未验证通过。')
    if work.package_id != update.previous_package_id:
        update.status = 'superseded'
        update.error = '作业已切换到其他批阅包，本次更新未生效。'
        update.completed_at = timezone.now()
        update.save(update_fields=['status', 'error', 'completed_at'])
        return update

    work.package = update.package
    work.description = update.description
    work.document_path = update.document_path
    work.document_name = update.document_name
    work.revision += 1
    work.save(
        update_fields=['package', 'description', 'document_path', 'document_name', 'revision']
    )

    if update.grading_changed:
        work.items.all().delete()
        CourseworkItem.objects.bulk_create(
            [
                CourseworkItem(
                    coursework=work,
                    function_name=item['function'],
                    title=item['function'],
                    points=item['points'],
                    order=order,
                )
                for order, item in enumerate(update.package.spec, 1)
            ]
        )
        state = snapshot(work)
        entries = list(
            CourseworkSubmission.objects.select_for_update()
            .filter(coursework=work)
            .prefetch_related('questions__cases')
        )
        for entry in entries:
            CourseworkGradeHistory.objects.create(
                submission=entry,
                package=update.previous_package,
                package_update=update,
                snapshot=entry.snapshot,
                status=entry.status,
                total=entry.total,
                error=entry.error,
                results=_archive_results(entry),
                finished_at=entry.finished_at,
            )
            entry.questions.all().delete()
            CourseworkQuestionResult.objects.bulk_create(
                [
                    CourseworkQuestionResult(
                        submission=entry,
                        function_name=item['function'],
                        title=item['title'],
                        points=item['points'],
                        order=item['order'],
                        verdict='PENDING',
                    )
                    for item in state['items']
                ]
            )
            entry.snapshot = state
            entry.status = 'pending'
            entry.total = None
            entry.error = ''
            entry.heartbeat = None
            entry.worker_token = None
            entry.finished_at = None
            entry.graded_by = None
            entry.save(
                update_fields=[
                    'snapshot',
                    'status',
                    'total',
                    'error',
                    'heartbeat',
                    'worker_token',
                    'finished_at',
                    'graded_by',
                ]
            )
    else:
        # A document update may be the first package to finish validation.
        # Release waiting submissions without changing already graded results.
        state = snapshot(work)
        waiting = CourseworkSubmission.objects.select_for_update().filter(
            coursework=work, status='waiting'
        )
        for entry in waiting:
            entry.snapshot = state
            entry.status = 'pending'
            entry.error = ''
            entry.save(update_fields=['snapshot', 'status', 'error'])
            entry.questions.update(verdict='PENDING')

    update.status = 'activated'
    update.error = ''
    update.completed_at = timezone.now()
    update.save(update_fields=['status', 'error', 'completed_at'])
    audit(
        update.requested_by,
        'portal.package_file.activate',
        str(work.pk),
        {'path': update.changed_path, 'regraded': update.grading_changed},
    )
    return update


@transaction.atomic
def create_package_update(actor, work, member, upload):
    work = Coursework.objects.select_for_update().select_related('package').get(pk=work.pk)
    if work.package_updates.filter(status__in=['pending', 'validating']).exists():
        raise ValidationError('已有文件更新正在验证，请等待完成后再操作。')
    if work.grading_mode == 'manual':
        if not work.materials_path:
            raise ValidationError('当前作业没有可更新的原始材料 ZIP。')
        original = read_private_bytes(work.materials_path)
        files, _, _ = manual_archive_files(original)
        replacement = upload.read()
        if files.get(member) == replacement:
            raise ValidationError('新文件内容与当前版本相同，无需更新。')
        rebuilt = replace_manual_member(original, member, replacement)
        parsed = parse_manual_materials_archive(rebuilt, 'updated-materials.zip')
        materials_path = save_private(rebuilt, '.zip')
        document_path = save_private(
            parsed['document_raw'], Path(parsed['document_name']).suffix.lower()
        )
        update = CourseworkPackageUpdate.objects.create(
            coursework=work,
            requested_by=actor,
            changed_path=member,
            grading_changed=False,
            document_path=document_path,
            document_name=parsed['document_name'][:200],
            description=parsed['description'],
            previous_materials_path=work.materials_path,
            materials_path=materials_path,
            status='activated',
            completed_at=timezone.now(),
        )
        work.materials_path = materials_path
        work.description = parsed['description']
        work.document_path = document_path
        work.document_name = parsed['document_name'][:200]
        work.revision += 1
        work.save(
            update_fields=[
                'materials_path',
                'description',
                'document_path',
                'document_name',
                'revision',
            ]
        )
        audit(
            actor,
            'portal.material_file.update',
            str(work.pk),
            {'path': member, 'requires_regrade': False},
        )
        return update

    if not work.package_id or not work.package.archive_path:
        raise ValidationError('当前机器批阅作业没有可更新的原始批阅包。')

    original = read_private_bytes(work.package.archive_path)
    rebuilt = replace_package_member(original, member, upload.read())
    parsed = parse_package_archive(rebuilt, 'updated-package.zip')
    if parsed['digest'] == work.package.digest:
        raise ValidationError('新文件内容与当前版本相同，无需更新。')

    grading_changed = Path(member).suffix.lower() != '.docx'
    package = save_uploaded_package(actor, parsed, rebuilt)
    document_path = save_private(
        parsed['document_raw'], Path(parsed['document_name']).suffix.lower()
    )
    update = CourseworkPackageUpdate.objects.create(
        coursework=work,
        previous_package=work.package,
        package=package,
        requested_by=actor,
        changed_path=member,
        grading_changed=grading_changed,
        document_path=document_path,
        document_name=parsed['document_name'][:200],
        description=parsed['description'],
        status='pending',
    )
    audit(
        actor,
        'portal.package_file.update',
        str(work.pk),
        {'path': member, 'requires_regrade': grading_changed},
    )

    if not grading_changed and snapshot(work)['ready']:
        package.spec = deepcopy(work.package.spec)
        package.status = 'ready'
        package.validation_error = ''
        package.validated_at = timezone.now()
        package.save(update_fields=['spec', 'status', 'validation_error', 'validated_at'])
        return activate_package_update(update.pk)
    if package.status == 'ready':
        return activate_package_update(update.pk)
    return update


def mark_package_updates_validating(package_id):
    CourseworkPackageUpdate.objects.filter(package_id=package_id, status='pending').update(
        status='validating', error=''
    )


def mark_package_updates_error(package_id, error):
    CourseworkPackageUpdate.objects.filter(
        package_id=package_id, status__in=['pending', 'validating']
    ).update(status='error', error=_validation_message(error)[:240], completed_at=timezone.now())


@transaction.atomic
def retry_package_update(actor, update):
    work = Coursework.objects.select_for_update().get(pk=update.coursework_id)
    locked = (
        CourseworkPackageUpdate.objects.select_for_update()
        .select_related('package')
        .get(pk=update.pk)
    )
    if locked.status != 'error' or work.package_id != locked.previous_package_id:
        raise ValidationError('该文件更新不能重新验证。')
    if (
        work.package_updates.exclude(pk=locked.pk)
        .filter(status__in=['pending', 'validating'])
        .exists()
    ):
        raise ValidationError('已有文件更新正在验证，请等待完成后再操作。')
    locked.package.status = 'pending'
    locked.package.validation_error = ''
    locked.package.validated_at = None
    locked.package.save(update_fields=['status', 'validation_error', 'validated_at'])
    locked.status = 'pending'
    locked.error = ''
    locked.completed_at = None
    locked.save(update_fields=['status', 'error', 'completed_at'])
    audit(
        actor,
        'portal.package_file.retry',
        str(locked.coursework_id),
        {'path': locked.changed_path},
    )
    return locked


def activate_ready_package_updates(package_id):
    for update_id in CourseworkPackageUpdate.objects.filter(
        package_id=package_id, status__in=['pending', 'validating']
    ).values_list('pk', flat=True):
        try:
            activate_package_update(update_id)
        except Exception as exc:  # noqa: BLE001 -- keep old package active on activation failure
            CourseworkPackageUpdate.objects.filter(pk=update_id).update(
                status='error', error=f'启用新版本失败：{exc}'[:240], completed_at=timezone.now()
            )
