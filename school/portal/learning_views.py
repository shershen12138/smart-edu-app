import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from school.models import CourseworkSubmission
from school.services import audit
from school.storage import read_private_bytes

from . import learning_forms as forms
from . import quality_service
from .access import allowed, role
from .common_views import page, private_download, work_for
from .package_update_services import package_update_display
from .parsers import parse_manual_submission_archive
from .result_display import result_text
from .submission_services import review_manual_submission, submit


@login_required
def work_detail(request, pk):
    work = work_for(request.user, pk)
    student = role(request.user) == 'student'
    can_edit = role(request.user) == 'teacher' and allowed(request.user, work.classroom, 'edit')
    package_update_alert, package_update_history = (
        package_update_display(work) if can_edit else (None, [])
    )
    required_files = [f'{item.function_name}.py' for item in work.items.all()]
    form = (
        forms.SubmitForm(
            request.POST or None,
            request.FILES or None,
            initial={'request_id': uuid.uuid4()},
            grading_mode=work.grading_mode,
            required_files=required_files,
        )
        if student
        else None
    )
    if request.method == 'POST':
        if not student:
            raise PermissionDenied
        if form.is_valid():
            try:
                entry = submit(request.user, pk, form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                return redirect('entry', pk=entry.pk)
    entries = list(work.entries.filter(student=request.user)) if student else []
    for entry in entries:
        entry.coursework = work
        entry.can_report = quality_service.supported(entry)
    return page(
        request,
        'work',
        work.title,
        work=work,
        form=form,
        entries=entries,
        can_edit=can_edit,
        package_update_alert=package_update_alert,
        package_update_history=package_update_history,
        can_results=allowed(request.user, work.classroom, 'view_grades'),
        open=work.opens_at <= timezone.now() <= work.deadline,
        back_url=reverse('dashboard' if student else 'works'),
    )


@login_required
def work_file(request, pk, kind):
    work = work_for(request.user, pk)
    if kind == 'document':
        return private_download(work.document_path, work.document_name)
    if kind == 'template' and work.package:
        return private_download(work.package.template_path, 'sample.py')
    if kind == 'materials' and work.grading_mode == 'manual':
        return private_download(work.materials_path, work.materials_name or '作业材料.zip')
    raise PermissionDenied


@login_required
def entry_detail(request, pk, download=False):
    entry = get_object_or_404(
        CourseworkSubmission.objects.select_related('student', 'coursework__classroom'), pk=pk
    )
    work = work_for(
        request.user,
        entry.coursework_id,
        None if role(request.user) == 'student' else 'view_grades',
    )
    if role(request.user) == 'student' and entry.student_id != request.user.pk:
        raise PermissionDenied
    if download:
        extension = '.zip' if work.grading_mode == 'manual' else '.py'
        return private_download(
            entry.source_path,
            f'{entry.student.student_no or entry.student.username}_{entry.sequence}{extension}',
        )
    questions = list(entry.questions.prefetch_related('cases'))
    snapshot_items = {item.get('function'): item for item in entry.snapshot.get('items', [])}
    show_answers = role(request.user) in ('teacher', 'admin')
    for question in questions:
        inputs = snapshot_items.get(question.function_name, {}).get('inputs', [])
        expected = snapshot_items.get(question.function_name, {}).get('expected', [])
        for case in question.cases.all():
            if show_answers:
                case.expected_output = (
                    result_text(expected[case.order - 1])
                    if 0 < case.order <= len(expected)
                    else '历史参考结果未记录'
                )
                case.actual_display = (
                    result_text(case.actual_output)
                    if case.actual_output
                    else '未记录返回结果（历史提交或运行未完成）'
                )
            case.input_value = (
                inputs[case.order - 1] if 0 < case.order <= len(inputs) else f'用例 {case.order}'
            )
    can_grade = (
        work.grading_mode == 'manual'
        and role(request.user) in ('teacher', 'admin')
        and allowed(request.user, work.classroom, 'view_grades')
    )
    grade_form = (
        forms.ManualReviewForm(request.POST or None, questions=questions) if can_grade else None
    )
    if request.method == 'POST':
        if not can_grade:
            raise PermissionDenied
        if grade_form.is_valid():
            review_manual_submission(request.user, entry.pk, grade_form.reviews())
            messages.success(request, '人工批阅成绩和评语已保存。')
            return redirect('entry', pk=entry.pk)
    manual_files = []
    if work.grading_mode == 'manual':
        required = entry.snapshot.get('required_files', [])
        parsed = parse_manual_submission_archive(
            read_private_bytes(entry.source_path), 'submission.zip', required
        )
        manual_files = [{'name': name, 'source': parsed['sources'][name]} for name in required]
    return page(
        request,
        'entry',
        '批阅结果',
        entry=entry,
        questions=questions,
        show_answers=show_answers,
        grade_history=entry.grade_history.select_related('package_update') if show_answers else [],
        manual_files=manual_files,
        grade_form=grade_form,
        can_grade=can_grade,
        can_report=quality_service.supported(entry),
        back_url=reverse('work', args=[entry.coursework_id])
        if role(request.user) == 'student'
        else reverse('work_results', args=[entry.coursework_id]),
        can_retry=role(request.user) in ('teacher', 'admin')
        and entry.status == 'error'
        and allowed(request.user, entry.coursework.classroom, 'edit'),
    )


@login_required
@require_POST
def entry_retry(request, pk):
    entry = get_object_or_404(CourseworkSubmission, pk=pk)
    work_for(request.user, entry.coursework_id, 'edit')
    if entry.status == 'error':
        CourseworkSubmission.objects.filter(pk=pk, status='error').update(
            status='pending', error='', total=None
        )
        audit(request.user, 'portal.retry', str(pk))
    return redirect('entry', pk=pk)
