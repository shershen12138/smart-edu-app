import csv
import io
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Avg, Max
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import AssignmentForm, ExtensionDecisionForm, ProblemForm
from .models import (
    Assignment,
    AssignmentVersion,
    Classroom,
    ExtensionRequest,
    GradeRevision,
    Problem,
    ProblemVersion,
    StudentGrade,
    TestCase,
    User,
)
from .permissions import is_admin, is_member, permitted, require_staff
from .services import (
    audit,
    decide_extension,
    dispatch_reference,
    make_revision,
    publish_assignment,
    publish_grades,
)
from .teaching import edit_token, latest_problems, readiness_error, save_assignment
from .web import form_page


@login_required
def problem_list(request, pk):
    classroom = get_object_or_404(Classroom, pk=pk)
    require_staff(request.user, classroom, 'edit')
    return render(
        request,
        'school/problems.html',
        {
            'title': '题库',
            'classroom': classroom,
            'versions': latest_problems(classroom),
            'back_url': reverse('class_detail', args=[pk]),
            'back_label': '返回教学班',
        },
    )


@login_required
def problem_edit(request, pk, version_id=None):
    classroom = get_object_or_404(Classroom, pk=pk)
    require_staff(request.user, classroom, 'edit')
    old = (
        get_object_or_404(ProblemVersion, pk=version_id, problem__classroom=classroom)
        if version_id
        else None
    )
    if old and request.method == 'GET':
        latest = old.problem.versions.order_by('-number').first()
        if latest.pk != old.pk:
            return redirect('problem_edit', pk=pk, version_id=latest.pk)
    initial = {field: getattr(old, field) for field in ProblemForm._meta.fields} if old else None
    form = ProblemForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                problem = (
                    Problem.objects.select_for_update().get(pk=old.problem_id)
                    if old
                    else (
                        Problem.objects.create(
                            code='P' + uuid.uuid4().hex[:10].upper(),
                            classroom=classroom,
                            created_by=request.user,
                        )
                    )
                )
                if old and problem.versions.order_by('-number').first().pk != old.pk:
                    raise ValidationError('题目已被更新，请返回题库重新打开编辑。')
                version = form.save(commit=False)
                version.problem = problem
                version.number = (problem.versions.aggregate(n=Max('number'))['n'] or 0) + 1
                # Existing judge assets remain private and immutable while the new adapter is pending.
                version.reference_path = old.reference_path if old else ''
                version.runtime = old.runtime if old else settings.JUDGE_IMAGE
                judge_unchanged = old and all(
                    getattr(version, field) == getattr(old, field)
                    for field in ('time_ms', 'memory_mb', 'output_kb', 'comparison')
                )
                version.reference_verified = bool(judge_unchanged and old.reference_verified)
                version.verification_error = old.verification_error if judge_unchanged else ''
                version.save()
                if old:
                    TestCase.objects.bulk_create(
                        [
                            TestCase(
                                version=version,
                                order=c.order,
                                input_path=c.input_path,
                                output_path=c.output_path,
                                is_sample=c.is_sample,
                                hidden=c.hidden,
                                description=c.description,
                            )
                            for c in old.cases.all()
                        ]
                    )
                audit(
                    request.user,
                    'problem.save',
                    f'problem:{problem.pk}',
                    {'snapshot': version.number},
                )
                if version.evaluation_configured and not version.reference_verified:
                    transaction.on_commit(lambda: dispatch_reference(version.pk))
            messages.success(
                request,
                '题目已保存。样例与批阅程序预留，待接入。'
                if not version.evaluation_configured
                else '题目内容已更新。',
            )
            return redirect('problems', pk=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        'school/problem_form.html',
        {
            'title': '编辑题目' if old else '新建题目',
            'form': form,
            'classroom': classroom,
            'back_url': reverse('problems', args=[pk]),
            'back_label': '返回题库',
        },
    )


@login_required
@require_POST
def problem_retry(request, pk):
    version = get_object_or_404(ProblemVersion, pk=pk)
    require_staff(request.user, version.problem.classroom, 'edit')
    if not version.evaluation_configured:
        messages.info(request, '评测待接入，当前无需校验。')
    elif not version.reference_verified:
        version.verification_error = ''
        version.save(update_fields=['verification_error'])
        dispatch_reference(pk)
        messages.success(request, '参考程序已进入校验队列。')
    return redirect('problems', pk=version.problem.classroom_id)


@login_required
def assignment_edit(request, pk, assignment_id=None):
    classroom = get_object_or_404(Classroom, pk=pk)
    require_staff(request.user, classroom, 'edit')
    assignment = (
        get_object_or_404(Assignment, pk=assignment_id, classroom=classroom)
        if assignment_id
        else None
    )
    old = assignment.versions.order_by('-number').first() if assignment else None
    initial = {
        'opens_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'deadline': timezone.localtime(timezone.now() + timedelta(days=7)).strftime(
            '%Y-%m-%dT%H:%M'
        ),
        'edit_token': edit_token(old),
    }
    if old:
        selected = old.questions.values_list('problem_version__problem_id', flat=True)
        initial.update(
            {
                'title': old.title,
                'description': old.description,
                'max_attempts': old.rule.max_attempts,
                'selection': old.rule.selection,
                'late_penalty': old.rule.late_penalty,
                'problems': list(
                    latest_problems(classroom)
                    .filter(problem_id__in=selected)
                    .values_list('pk', flat=True)
                ),
            }
        )
        for field in ('opens_at', 'deadline', 'late_deadline'):
            value = getattr(old.rule, field)
            initial[field] = timezone.localtime(value).strftime('%Y-%m-%dT%H:%M') if value else ''
    form = AssignmentForm(request.POST or None, classroom=classroom, version=old, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            version, pending = save_assignment(
                request.user, classroom, assignment, form.cleaned_data
            )
            if version.status == 'published':
                messages.success(
                    request,
                    '作业已更新，学生打开作业即可看到当前内容。已发布成绩保持原值，如需更新请重新计算或重评。',
                )
            elif pending:
                messages.warning(request, '内容已保存。' + pending)
            else:
                messages.success(request, '草稿已保存，等待负责教师发布。')
            return redirect('assignment', pk=version.assignment_id)
        except ValidationError as exc:
            form.add_error(None, exc)
    return form_page(
        request,
        '编辑作业' if old else '创建作业',
        form,
        description='保存会更新当前内容。教师修改已发布作业后自动生效；助教修改由教师发布。选择题目时使用题库的最新内容。评测未就绪时先保存草稿。',
        back_url=reverse('assignment', args=[assignment.pk])
        if assignment
        else reverse('class_detail', args=[pk]),
        back_label='返回作业' if assignment else '返回教学班',
    )


def assignment_access(user, assignment):
    return (
        is_member(user, assignment.classroom)
        or permitted(user, assignment.classroom)
        or is_admin(user)
    )


@login_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.select_related('classroom', 'current_version__rule'), pk=pk
    )
    if not assignment_access(request.user, assignment):
        raise PermissionDenied
    version = assignment.current_version
    if permitted(request.user, assignment.classroom, 'edit'):
        version = assignment.versions.order_by('-number').first()
    if not version:
        raise Http404
    return assignment_render(request, version)


@login_required
def assignment_version(request, pk):
    version = get_object_or_404(AssignmentVersion, pk=pk)
    require_staff(request.user, version.assignment.classroom, 'edit')
    return redirect('assignment', pk=version.assignment_id)


def assignment_render(request, version):
    assignment = version.assignment
    return render(
        request,
        'school/assignment.html',
        {
            'title': version.title,
            'back_url': reverse('class_detail', args=[assignment.classroom_id]),
            'back_label': '返回教学班',
            'pending_evaluation': readiness_error(version),
            'edit_token': edit_token(version),
            'assignment': assignment,
            'version': version,
            'questions': version.questions.select_related('problem_version__problem'),
            'can_edit': permitted(request.user, assignment.classroom, 'edit'),
            'can_publish': permitted(request.user, assignment.classroom, 'publish'),
            'can_grades': permitted(request.user, assignment.classroom, 'grades'),
            'can_submit': is_member(request.user, assignment.classroom)
            and not assignment.classroom.archived
            and assignment.current_version_id == version.pk,
        },
    )


@login_required
@require_POST
def assignment_action(request, pk):
    version = get_object_or_404(AssignmentVersion, pk=pk)
    try:
        if request.POST.get('action') == 'publish':
            require_staff(request.user, version.assignment.classroom, 'publish')
            with transaction.atomic():
                Assignment.objects.select_for_update().get(pk=version.assignment_id)
                version = AssignmentVersion.objects.select_for_update().get(pk=pk)
                if request.POST.get('edit_token') != edit_token(version):
                    raise ValidationError('作业已更新，请重新打开并检查当前内容后发布。')
                publish_assignment(request.user, version)
            messages.success(request, '作业已发布。')
        elif request.POST.get('action') == 'points':
            require_staff(request.user, version.assignment.classroom, 'edit')
            with transaction.atomic():
                Assignment.objects.select_for_update().get(pk=version.assignment_id)
                version = AssignmentVersion.objects.select_for_update().get(pk=pk)
                if version.status != 'draft':
                    raise ValidationError('只能调整草稿分值。')
                if version.assignment.versions.order_by(
                    '-number'
                ).first().pk != version.pk or request.POST.get('edit_token') != edit_token(version):
                    raise ValidationError('作业已更新，请刷新后再调整分值。')
                for q in version.questions.all():
                    points = Decimal(request.POST.get(f'points_{q.pk}', ''))
                    if (
                        not points.is_finite()
                        or not 1 <= points <= 1000
                        or points.as_tuple().exponent < -2
                    ):
                        raise ValidationError('分值须为 1～1000，最多两位小数。')
                    q.max_score = points
                    q.save(update_fields=['max_score'])
                audit(request.user, 'assignment.points', f'version:{pk}')
            messages.success(request, '草稿分值已更新。')
    except (ValidationError, InvalidOperation) as exc:
        messages.error(
            request,
            '；'.join(exc.messages) if isinstance(exc, ValidationError) else '分值格式不正确。',
        )
    return redirect('assignment', pk=version.assignment_id)


@login_required
def grades_view(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    require_staff(request.user, assignment.classroom, 'grades')
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            if action in ('calculate', 'rejudge'):
                revision = make_revision(
                    request.user,
                    assignment,
                    '教师发起自动重评' if action == 'rejudge' else '正式成绩计算',
                    action == 'rejudge',
                )
                messages.success(request, f'成绩批次 {revision.number} 已建立。')
            elif action == 'publish':
                revision = get_object_or_404(
                    GradeRevision, pk=request.POST.get('revision'), assignment=assignment
                )
                publish_grades(request.user, revision)
                messages.success(request, '成绩已发布，学生可查看。')
        except ValidationError as exc:
            messages.error(request, '；'.join(exc.messages))
        return redirect('grades', pk=pk)
    revisions = assignment.grades.order_by('-number')
    selected = (
        revisions.filter(pk=request.GET.get('revision')).first()
        if request.GET.get('revision', '').isdigit()
        else revisions.first()
    )
    grades = (
        selected.students.prefetch_related('questions').order_by('number_snapshot')
        if selected
        else StudentGrade.objects.none()
    )
    return render(
        request,
        'school/grades.html',
        {
            'title': '成绩与统计',
            'back_url': reverse('assignment', args=[assignment.pk]),
            'back_label': '返回作业',
            'assignment': assignment,
            'revisions': revisions,
            'selected': selected,
            'grades': grades,
            'average': grades.aggregate(n=Avg('total'))['n'],
            'can_publish': permitted(request.user, assignment.classroom, 'publish'),
            'can_export': permitted(request.user, assignment.classroom, 'export'),
            'recent_submissions': assignment.submissions.select_related(
                'student', 'question__problem_version'
            )[:40],
        },
    )


def safe_csv(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text


@login_required
def grades_export(request, pk):
    revision = get_object_or_404(
        GradeRevision.objects.select_related('assignment__classroom'), pk=pk
    )
    require_staff(request.user, revision.assignment.classroom, 'export')
    if revision.status != 'published':
        raise PermissionDenied('仅允许导出正式发布批次。')
    output = io.StringIO()
    writer = csv.writer(output)
    keys = list(revision.version.questions.values_list('question_key', flat=True))
    writer.writerow(['学工号', '姓名', *keys, '总分', '成绩批次'])
    for g in revision.students.prefetch_related('questions').order_by('number_snapshot'):
        points = {q.question_key: q.final_score for q in g.questions.all()}
        writer.writerow(
            [
                safe_csv(g.number_snapshot),
                safe_csv(g.name_snapshot),
                *[points.get(k, 0) for k in keys],
                g.total,
                revision.number,
            ]
        )
    audit(request.user, 'grades.export', f'revision:{pk}')
    response = HttpResponse('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="grades-{revision.assignment_id}-v{revision.number}.csv"'
    )
    return response


@login_required
def extension_decide(request, pk):
    extension = get_object_or_404(ExtensionRequest, pk=pk)
    require_staff(request.user, extension.assignment.classroom, 'grades')
    can_publish = permitted(request.user, extension.assignment.classroom, 'publish')
    form = ExtensionDecisionForm(
        request.POST or None,
        assignment=extension.assignment,
        initial={
            'starts_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            'ends_at': timezone.localtime(timezone.now() + timedelta(days=2)).strftime(
                '%Y-%m-%dT%H:%M'
            ),
        },
    )
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'note':
                extension.assistant_note = request.POST.get('note', '')[:1000]
                extension.save(update_fields=['assistant_note'])
                audit(request.user, 'extension.note', f'extension:{pk}')
                return redirect('extensions', pk=extension.assignment_id)
            elif request.POST.get('action') == 'revoke':
                require_staff(request.user, extension.assignment.classroom, 'publish')
                with transaction.atomic():
                    User.objects.select_for_update().get(pk=extension.student_id)
                    ExtensionRequest.objects.filter(pk=pk, status='approved').update(
                        status='revoked', revoked_at=timezone.now()
                    )
                    audit(request.user, 'extension.revoke', f'extension:{pk}')
                return redirect('extensions', pk=extension.assignment_id)
            elif can_publish and form.is_valid():
                data = dict(form.cleaned_data)
                data['approve'] = data['approve'] == 'yes'
                decide_extension(request.user, extension, **data)
                return redirect('extensions', pk=extension.assignment_id)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        'school/extension_decide.html',
        {
            'title': '处理补交申请',
            'extension': extension,
            'form': form,
            'can_publish': can_publish,
            'back_url': reverse('extensions', args=[extension.assignment_id]),
            'back_label': '返回补交申请',
        },
    )
