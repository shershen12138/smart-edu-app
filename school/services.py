import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from .models import (
    User,
    UserRole,
    Classroom,
    ClassStudent,
    ClassStaff,
    AuditLog,
    Assignment,
    AssignmentVersion,
    AssignmentQuestion,
    SubmissionRuleVersion,
    Submission,
    JudgeRun,
    GradeRevision,
    StudentGrade,
    StudentQuestionGrade,
    ExtensionRequest,
    Notification,
)
from .permissions import require_admin, require_staff, is_member
from .storage import save_private, code_digest


def audit(user, action, target, detail=None, request=None):
    return AuditLog.objects.create(
        actor=user if user and user.is_authenticated else None,
        action=action,
        target=str(target),
        detail=detail or {},
        ip=request.META.get('REMOTE_ADDR') if request else None,
    )


def notify(user, event, object_id, message, key):
    Notification.objects.get_or_create(
        dedup_key=key,
        defaults=dict(recipient=user, event=event, object_id=object_id, message=message),
    )


@transaction.atomic
def set_membership(actor, classroom, student, active=True):
    require_admin(actor)
    Classroom.objects.select_for_update().get(pk=classroom.pk)
    if not student.has_role('student'):
        raise ValidationError('该用户尚未分配学生身份。')
    if (
        active
        and ClassStaff.objects.filter(classroom=classroom, user=student, active=True).exists()
    ):
        raise ValidationError('同一教学班不能同时担任学生与任课人员。')
    member, _ = ClassStudent.objects.get_or_create(classroom=classroom, student=student)
    member.active = active
    member.left_at = None if active else timezone.now()
    if active:
        member.joined_at = timezone.now()
    member.save()
    audit(
        actor,
        'member.activate' if active else 'member.remove',
        f'class:{classroom.pk}/user:{student.pk}',
    )
    return member


@transaction.atomic
def set_staff(actor, classroom, user, role, **permissions):
    require_admin(actor)
    Classroom.objects.select_for_update().get(pk=classroom.pk)
    if role not in ('teacher', 'assistant') or not user.has_role(role):
        raise ValidationError('账号系统身份与教学班职务不匹配。')
    if ClassStudent.objects.filter(classroom=classroom, student=user, active=True).exists():
        raise ValidationError('同班学生不能同时担任教师或助教。')
    if role == 'teacher':
        ClassStaff.objects.filter(classroom=classroom, role='teacher', active=True).exclude(
            user=user
        ).update(active=False)
    staff, _ = ClassStaff.objects.update_or_create(
        classroom=classroom, user=user, defaults={'role': role, 'active': True, **permissions}
    )
    audit(actor, 'staff.authorize', f'class:{classroom.pk}/user:{user.pk}', {'role': role})
    return staff


@transaction.atomic
def publish_assignment(actor, version):
    assignment = Assignment.objects.select_for_update().get(pk=version.assignment_id)
    require_staff(actor, assignment.classroom, 'publish')
    version = AssignmentVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != 'draft':
        raise ValidationError('这份作业内容已经发布。')
    if assignment.versions.order_by('-number').first().pk != version.pk:
        raise ValidationError('这份草稿已过期，请重新打开当前作业。')
    questions = list(version.questions.select_related('problem_version__problem'))
    if not questions:
        raise ValidationError('请至少配置一道题目。')
    for q in questions:
        p = q.problem_version
        if not p.evaluation_configured:
            raise ValidationError(f'“{p.title}”的评测待接入，暂不能发布。')
        if p.problem.classroom_id != assignment.classroom_id or not p.reference_verified:
            raise ValidationError('所有题目必须属于本班，且参考程序已通过全部测试。')
        if not p.cases.filter(is_sample=False).exists():
            raise ValidationError('每题至少需要一个正式评测用例。')
    old = assignment.current_version
    if old and assignment.submissions.exists():
        if old.rule.selection != version.rule.selection:
            raise ValidationError('已有提交后不能更改成绩选取模式。')
        old_keys = set(old.questions.values_list('question_key', flat=True))
        if old_keys != {q.question_key for q in questions}:
            raise ValidationError('已有提交后须保留原稳定题号；增删题请新建作业。')
    version.status = 'published'
    version.published_by = actor
    version.published_at = timezone.now()
    version.save()
    assignment.current_version = version
    assignment.save(update_fields=['current_version'])
    audit(actor, 'assignment.publish', f'assignment:{assignment.pk}', {'version': version.number})
    return version


def dispatch(run_id):
    if settings.REDIS_URL:
        try:
            from .tasks import evaluate_run

            evaluate_run.delay(run_id)
            JudgeRun.objects.filter(pk=run_id, status='pending').update(
                status='queued', heartbeat=timezone.now()
            )
        except Exception:
            # 事务中已经保留待派发记录；beat 或 run_judge 可恢复。
            pass


def dispatch_reference(version_id):
    if not settings.REDIS_URL:
        return
    from django.core.cache import cache

    key = f'verify-dispatch:{version_id}'
    try:
        if cache.add(key, True, 600):
            from .tasks import verify_problem

            verify_problem.delay(version_id)
    except Exception:
        try:
            cache.delete(key)
        except Exception:
            pass


@transaction.atomic
def accept_submission(student, question_id, code, request_key, now=None):
    now = now or timezone.now()
    try:
        key = uuid.UUID(str(request_key))
    except (ValueError, AttributeError):
        raise ValidationError('提交标识无效，请刷新页面。')
    locked_student = User.objects.select_for_update().get(pk=student.pk)
    if not locked_student.is_active:
        raise PermissionDenied('账号已停用。')
    existing = Submission.objects.filter(student=student, idempotency_key=key).first()
    if existing:
        if existing.question_id != int(question_id) or existing.code_hash != code_digest(code):
            raise ValidationError('同一提交标识不能用于不同内容。')
        return existing
    question = AssignmentQuestion.objects.select_related(
        'version__assignment__classroom', 'version__rule', 'problem_version'
    ).get(pk=question_id)
    assignment = Assignment.objects.select_for_update().get(pk=question.version.assignment_id)
    classroom = assignment.classroom
    if classroom.archived or not is_member(student, classroom):
        raise PermissionDenied('班级已归档或你不在有效学生名单中。')
    if (
        assignment.current_version_id != question.version_id
        or question.version.status != 'published'
    ):
        raise ValidationError('作业版本已更新，请重新打开题目页面。')
    rule = question.version.rule
    data = code.encode('utf-8')
    if not code.strip() or '\x00' in code or len(data) > rule.max_size_kb * 1024:
        raise ValidationError(f'代码不能为空，须为 UTF-8，且不能超过 {rule.max_size_kb} KB。')
    pending = JudgeRun.objects.filter(
        submission__student=student, status__in=['pending', 'queued', 'running']
    ).count()
    if pending >= rule.max_pending:
        raise ValidationError('待评测任务已达到上限，请等待结果后再提交。')
    last = Submission.objects.filter(student=student).first()
    if last and (now - last.received_at).total_seconds() < rule.interval_seconds:
        raise ValidationError(f'两次提交至少间隔 {rule.interval_seconds} 秒。')
    extension = None
    candidates = ExtensionRequest.objects.filter(
        student=student,
        assignment=assignment,
        status='approved',
        starts_at__lte=now,
        ends_at__gte=now,
    )
    for candidate in candidates:
        if not candidate.question_keys or question.question_key in candidate.question_keys:
            used = Submission.objects.filter(
                extension=candidate, question_key=question.question_key, counted=True
            ).count()
            if used < candidate.extra_attempts:
                extension = candidate
                break
    if extension:
        kind, penalty = 'extension', extension.penalty
    elif rule.opens_at <= now <= rule.deadline:
        kind, penalty = 'normal', Decimal(0)
    elif rule.late_deadline and rule.deadline < now <= rule.late_deadline:
        kind, penalty = 'late', rule.late_penalty
    else:
        raise ValidationError('当前不在可提交时间内，可联系教师或申请补交。')
    history = Submission.objects.filter(
        student=student, assignment=assignment, question_key=question.question_key
    )
    if (
        not extension
        and history.filter(extension__isnull=True, counted=True).count() >= rule.max_attempts
    ):
        raise ValidationError('本题提交次数已用完。')
    path = save_private(code, '.py')
    submission = Submission.objects.create(
        student=student,
        assignment=assignment,
        question=question,
        question_key=question.question_key,
        sequence=(history.aggregate(n=Max('sequence'))['n'] or 0) + 1,
        idempotency_key=key,
        code_path=path,
        code_hash=code_digest(code),
        received_at=now,
        kind=kind,
        extension=extension,
        rule_snapshot={
            'rule_id': rule.pk,
            'selection': rule.selection,
            'penalty': str(penalty),
            'max_score': str(question.max_score),
            'deadline': rule.deadline.isoformat(),
            'version': question.version.number,
        },
    )
    run = JudgeRun.objects.create(submission=submission, question=question)
    transaction.on_commit(lambda: dispatch(run.pk))
    return submission


def final_score(run):
    penalty = Decimal(run.submission.rule_snapshot['penalty'])
    return max(Decimal(0), run.base_score * (1 - penalty)).quantize(
        Decimal('.01'), rounding=ROUND_HALF_UP
    )


@transaction.atomic
def make_revision(actor, assignment, reason='正式成绩计算', rejudge=False):
    assignment = Assignment.objects.select_for_update().get(pk=assignment.pk)
    require_staff(actor, assignment.classroom, 'publish')
    version = assignment.current_version
    if not version:
        raise ValidationError('作业尚未发布。')
    if assignment.grades.filter(status='processing').exists():
        raise ValidationError('已有重评批次正在处理。')
    revision = GradeRevision.objects.create(
        assignment=assignment,
        number=(assignment.grades.aggregate(n=Max('number'))['n'] or 0) + 1,
        version=version,
        reason=reason,
        status='processing' if rejudge else 'ready',
    )
    questions = {q.question_key: q for q in version.questions.all()}
    submissions = assignment.submissions.filter(received_at__lte=revision.cutoff, counted=True)
    roster = User.objects.filter(
        Q(memberships__classroom=assignment.classroom, memberships__active=True)
        | Q(pk__in=submissions.values('student_id'))
    ).distinct()
    revision.roster_snapshot = [
        {'id': u.pk, 'name': u.full_name or u.username, 'number': u.student_no or u.username}
        for u in roster
    ]
    revision.save(update_fields=['roster_snapshot'])
    if rejudge:
        for sub in submissions:
            q = questions.get(sub.question_key)
            if q:
                run = JudgeRun.objects.create(
                    submission=sub,
                    revision=revision,
                    question=q,
                    execution=(sub.runs.aggregate(n=Max('execution'))['n'] or 0) + 1,
                )
                transaction.on_commit(lambda run_id=run.pk: dispatch(run_id))
    else:
        populate_grades(revision)
    audit(
        actor,
        'grades.rejudge' if rejudge else 'grades.calculate',
        f'assignment:{assignment.pk}',
        {'revision': revision.number},
    )
    return revision


def populate_grades(revision):
    questions = list(revision.version.questions.all())
    submissions = Submission.objects.filter(
        assignment=revision.assignment, received_at__lte=revision.cutoff, counted=True
    )
    pending_message = '存在未完成评测或题目版本不一致，请先完成自动重评再计算成绩。'
    for student in revision.roster_snapshot:
        grade = StudentGrade.objects.create(
            revision=revision,
            student_id=student['id'],
            name_snapshot=student['name'],
            number_snapshot=student['number'],
        )
        total = Decimal(0)
        for q in questions:
            candidates = []
            for sub in submissions.filter(student_id=student['id'], question_key=q.question_key):
                runs = sub.runs.filter(
                    question__problem_version=q.problem_version, question__max_score=q.max_score
                )
                if revision.status == 'processing':
                    runs = runs.filter(revision=revision)
                run = runs.order_by('-execution').first()
                if not run or run.status != 'done':
                    raise ValidationError(pending_message)
                candidates.append(run)
            if revision.version.rule.selection == 'latest':
                chosen = max(
                    candidates,
                    key=lambda r: (r.submission.received_at, r.submission_id),
                    default=None,
                )
            else:
                chosen = max(
                    candidates,
                    key=lambda r: (final_score(r), r.submission.received_at),
                    default=None,
                )
            base = chosen.base_score if chosen else Decimal(0)
            score = final_score(chosen) if chosen else Decimal(0)
            StudentQuestionGrade.objects.create(
                grade=grade,
                question_key=q.question_key,
                question=q,
                submission=chosen.submission if chosen else None,
                run=chosen,
                base_score=base,
                deduction=base - score,
                final_score=score,
            )
            total += score
        grade.total = total
        grade.save(update_fields=['total'])


@transaction.atomic
def publish_grades(actor, revision):
    revision = (
        GradeRevision.objects.select_for_update()
        .select_related('assignment__classroom')
        .get(pk=revision.pk)
    )
    require_staff(actor, revision.assignment.classroom, 'publish')
    if revision.status == 'published':
        raise ValidationError('此批次已经发布。')
    assignment = Assignment.objects.select_for_update().get(pk=revision.assignment_id)
    if assignment.current_version_id != revision.version_id:
        raise ValidationError('作业已更新，请按当前版本重新计算或重评。')
    if assignment.current_grade and assignment.current_grade.number >= revision.number:
        raise ValidationError('不能用旧批次覆盖较新的正式成绩。')
    if revision.status == 'processing':
        if revision.runs.exclude(status__in=['done', 'superseded']).exists():
            raise ValidationError('该批次仍有未完成或异常的评测。')
        populate_grades(revision)
    revision.status = 'published'
    revision.published_by = actor
    revision.published_at = timezone.now()
    revision.save()
    assignment.current_grade = revision
    assignment.save(update_fields=['current_grade'])
    for grade in revision.students.all():
        notify(
            grade.student,
            'grade',
            assignment.pk,
            f'“{revision.version.title}”成绩已发布',
            f'grade:{revision.pk}:{grade.student_id}',
        )
    audit(actor, 'grades.publish', f'assignment:{assignment.pk}', {'revision': revision.number})


@transaction.atomic
def decide_extension(
    actor,
    extension,
    approve,
    starts_at=None,
    ends_at=None,
    attempts=3,
    penalty=Decimal(0),
    decision='',
    question_keys=None,
):
    extension = (
        ExtensionRequest.objects.select_for_update()
        .select_related('assignment__classroom')
        .get(pk=extension.pk)
    )
    require_staff(actor, extension.assignment.classroom, 'publish')
    User.objects.select_for_update().get(pk=extension.student_id)
    if extension.status != 'pending':
        raise ValidationError('此申请已经处理。')
    if approve:
        if question_keys is not None:
            valid = (
                set(
                    extension.assignment.current_version.questions.values_list(
                        'question_key', flat=True
                    )
                )
                if extension.assignment.current_version
                else set()
            )
            if not set(question_keys).issubset(valid):
                raise ValidationError('补交题目不属于本作业。')
            extension.question_keys = list(dict.fromkeys(question_keys))
        if (
            not starts_at
            or not ends_at
            or ends_at <= starts_at
            or not 1 <= attempts <= 1000
            or not 0 <= penalty <= 1
        ):
            raise ValidationError('请检查批准时间、次数与扣分比例。')
        overlap = ExtensionRequest.objects.filter(
            student=extension.student,
            assignment=extension.assignment,
            status='approved',
            starts_at__lte=ends_at,
            ends_at__gte=starts_at,
        )
        for old in overlap:
            if (
                not old.question_keys
                or not extension.question_keys
                or set(old.question_keys) & set(extension.question_keys)
            ):
                raise ValidationError('存在重叠补交许可，请先撤销旧许可。')
        extension.starts_at, extension.ends_at = starts_at, ends_at
        extension.extra_attempts, extension.penalty = attempts, penalty
    extension.status = 'approved' if approve else 'rejected'
    extension.decided_by, extension.decision = actor, decision
    extension.save()
    notify(
        extension.student,
        'extension',
        extension.assignment_id,
        f'补交申请{extension.get_status_display()}',
        f'extension:{extension.pk}:decided',
    )
    audit(actor, 'extension.decide', f'extension:{extension.pk}', {'status': extension.status})
