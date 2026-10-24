"""Teacher/assistant editing workflows; published data stays available to old submissions."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, OuterRef, Subquery

from .models import (
    Assignment,
    AssignmentQuestion,
    AssignmentVersion,
    ProblemVersion,
    SubmissionRuleVersion,
)
from .permissions import permitted, require_staff
from .services import audit, publish_assignment


def latest_problems(classroom):
    latest = ProblemVersion.objects.filter(problem_id=OuterRef('problem_id')).order_by('-number')
    return (
        ProblemVersion.objects.filter(
            problem__classroom=classroom,
            problem__active=True,
            pk=Subquery(latest.values('pk')[:1]),
        )
        .select_related('problem')
        .order_by('problem_id')
    )


def latest_drafts(classroom_ids):
    latest = AssignmentVersion.objects.filter(assignment_id=OuterRef('assignment_id')).order_by(
        '-number'
    )
    return (
        AssignmentVersion.objects.filter(
            assignment__classroom_id__in=classroom_ids,
            status='draft',
            pk=Subquery(latest.values('pk')[:1]),
        )
        .select_related('assignment__classroom')
        .order_by('-pk')
    )


def edit_token(version):
    if not version:
        return ''
    state = {
        'version': version.pk,
        'status': version.status,
        'title': version.title,
        'description': version.description,
        'rule': {
            field.attname: getattr(version.rule, field.attname)
            for field in SubmissionRuleVersion._meta.fields
        },
        'questions': list(
            version.questions.order_by('pk').values(
                'pk', 'problem_version_id', 'order', 'max_score'
            )
        ),
    }

    def canonical(value):
        if isinstance(value, Decimal):
            return format(value.normalize(), 'f')
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        return str(value)

    return hashlib.sha256(json.dumps(state, sort_keys=True, default=canonical).encode()).hexdigest()


def readiness_error(version):
    for question in version.questions.select_related('problem_version'):
        problem = question.problem_version
        if not problem.evaluation_configured:
            return f'“{problem.title}”的评测待接入，接入完成前仅保存草稿。'
        if not problem.reference_verified:
            return f'“{problem.title}”尚未通过参考程序校验，校验完成后才能发布。'
    return ''


@transaction.atomic
def save_assignment(actor, classroom, assignment, data):
    require_staff(actor, classroom, 'edit')
    if assignment:
        assignment = Assignment.objects.select_for_update().get(pk=assignment.pk)
        old = assignment.versions.order_by('-number').first()
        if not data.get('edit_token') or data['edit_token'] != edit_token(old):
            raise ValidationError('这份作业已被更新，请返回作业重新打开编辑，避免覆盖他人的修改。')
    else:
        assignment = Assignment.objects.create(classroom=classroom, created_by=actor)
        old = None
    problems = list(data['problems'])
    if assignment.current_version_id and assignment.submissions.exists():
        current = assignment.current_version
        if current.rule.selection != data['selection']:
            raise ValidationError('已有提交后不能更改成绩选取方式。')
        if set(current.questions.values_list('question_key', flat=True)) != {
            p.problem.code for p in problems
        }:
            raise ValidationError('已有提交后须保留原题目；增删题请新建作业。')
    old_points = (
        {
            q.problem_version.problem_id: q.max_score
            for q in old.questions.select_related('problem_version')
        }
        if old
        else {}
    )
    rule_fields = [
        'opens_at',
        'deadline',
        'late_deadline',
        'max_attempts',
        'selection',
        'late_penalty',
    ]
    if old and old.status == 'draft':
        version, rule = old, old.rule
        for field in rule_fields:
            setattr(rule, field, data[field])
        rule.save(update_fields=rule_fields)
        version.title, version.description = data['title'], data['description']
        version.save(update_fields=['title', 'description'])
    else:
        number = (assignment.versions.aggregate(n=Max('number'))['n'] or 0) + 1
        limits = (
            {
                key: getattr(old.rule, key)
                for key in ('interval_seconds', 'max_pending', 'max_size_kb')
            }
            if old
            else {}
        )
        rule = SubmissionRuleVersion.objects.create(
            assignment=assignment,
            number=number,
            **limits,
            **{key: data[key] for key in rule_fields},
        )
        version = AssignmentVersion.objects.create(
            assignment=assignment,
            number=number,
            rule=rule,
            title=data['title'],
            description=data['description'],
        )
    keys = []
    for index, problem in enumerate(problems, 1):
        keys.append(problem.problem.code)
        points = data.get(f'score_{problem.problem_id}')
        if points is None:
            points = old_points.get(problem.problem_id, data['points'])
        AssignmentQuestion.objects.update_or_create(
            version=version,
            question_key=problem.problem.code,
            defaults={'problem_version': problem, 'order': index, 'max_score': points},
        )
    version.questions.exclude(question_key__in=keys).delete()
    audit(actor, 'assignment.save', f'assignment:{assignment.pk}', {'snapshot': version.number})
    pending = readiness_error(version)
    if assignment.current_version_id and permitted(actor, classroom, 'publish') and not pending:
        version = publish_assignment(actor, version)
    return version, pending
