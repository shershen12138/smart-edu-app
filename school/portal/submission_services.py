import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from school.models import Coursework, CourseworkQuestionResult, CourseworkSubmission
from school.services import audit
from school.storage import code_digest, save_private

from .access import allowed, classes_for, role
from .coursework_services import snapshot


@transaction.atomic
def submit(actor, work_id, data):
    if role(actor) != 'student':
        raise PermissionDenied
    work = (
        Coursework.objects.select_for_update()
        .select_related('package')
        .get(pk=work_id, deleted_at__isnull=True)
    )
    if not classes_for(actor).filter(pk=work.classroom_id).exists() or work.status != 'open':
        raise PermissionDenied
    previous = CourseworkSubmission.objects.filter(request_id=data['request_id']).first()
    if previous:
        if previous.student_id != actor.pk or previous.coursework_id != work.pk:
            raise PermissionDenied
        return previous
    now = timezone.now()
    if not work.opens_at <= now <= work.deadline:
        raise ValidationError('当前不在作业提交时间内。')
    entries = work.entries.filter(student=actor)
    count = entries.count()
    if count >= work.max_attempts:
        raise ValidationError('已达到本次作业的提交次数上限。')
    if entries.filter(status__in=['pending', 'queued', 'running']).exists():
        raise ValidationError('上次提交还在批阅中，请完成后再提交。')
    state = snapshot(work)
    if work.grading_mode == 'manual':
        archive = data['source']['raw']
        source_path = save_private(archive, '.zip')
        source_hash = hashlib.sha256(archive).hexdigest()
        status = 'review'
    else:
        source_path = save_private(data['source'], '.py')
        source_hash = code_digest(data['source'])
        status = 'pending' if state['ready'] else 'waiting'
    entry = CourseworkSubmission.objects.create(
        coursework=work,
        student=actor,
        sequence=count + 1,
        request_id=data['request_id'],
        source_path=source_path,
        source_hash=source_hash,
        snapshot=state,
        status=status,
    )
    CourseworkQuestionResult.objects.bulk_create(
        [
            CourseworkQuestionResult(
                submission=entry,
                function_name=i['function'],
                title=i['title'],
                points=i['points'],
                order=i['order'],
                verdict=(
                    'MANUAL_PENDING'
                    if work.grading_mode == 'manual'
                    else ('PENDING' if state['ready'] else 'WAITING')
                ),
            )
            for i in state['items']
        ]
    )
    audit(actor, 'portal.submit', str(entry.pk))
    return entry


@transaction.atomic
def review_manual_submission(actor, entry_id, reviews):
    entry = (
        CourseworkSubmission.objects.select_for_update()
        .select_related('coursework__classroom')
        .get(pk=entry_id)
    )
    if role(actor) not in ('teacher', 'admin') or not allowed(
        actor, entry.coursework.classroom, 'view_grades'
    ):
        raise PermissionDenied
    if entry.coursework.grading_mode != 'manual' or entry.status not in ('review', 'done'):
        raise ValidationError('该提交不能进行人工批阅。')
    questions = {question.pk: question for question in entry.questions.select_for_update()}
    if set(questions) != {item['question_id'] for item in reviews}:
        raise ValidationError('批阅题目与当前提交不一致，请刷新后重试。')
    total = 0
    for item in reviews:
        question = questions[item['question_id']]
        question.score = item['score']
        question.feedback = item['feedback']
        question.verdict = 'MANUAL'
        question.save(update_fields=['score', 'feedback', 'verdict'])
        total += item['score']
    entry.status = 'done'
    entry.total = total
    entry.error = ''
    entry.finished_at = timezone.now()
    entry.graded_by = actor
    entry.save(update_fields=['status', 'total', 'error', 'finished_at', 'graded_by'])
    audit(actor, 'portal.manual_review', str(entry.pk))
    return entry
