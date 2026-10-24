import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from school.models import Coursework, CourseworkPackageUpdate, User
from school.services import audit
from school.storage import read_private_bytes

from . import teaching_forms as forms
from .access import allowed, classes_for, role
from .common_views import csv_response, form_page, link, page, safe_csv, table, work_for
from .coursework_services import save_work
from .package_update_services import (
    create_package_update,
    package_update_display,
    retry_package_update,
)
from .parsers import manual_member_choices, package_member_choices
from .reporting_services import roster_rows, score_distribution


@login_required
def works(request):
    if role(request.user) == 'student':
        return redirect('dashboard')
    if role(request.user) != 'teacher':
        raise PermissionDenied
    qs = Coursework.objects.filter(
        classroom__in=classes_for(request.user), deleted_at__isnull=True
    ).select_related('classroom')
    selected = request.GET.get('classroom', '')
    if selected.isdigit():
        qs = qs.filter(classroom_id=int(selected))
    rows = []
    for work in qs:
        if not (
            allowed(request.user, work.classroom, 'edit')
            or allowed(request.user, work.classroom, 'view_grades')
        ):
            continue
        actions = [link('查看', 'work', work.pk)]
        if allowed(request.user, work.classroom, 'edit'):
            actions += [link('编辑', 'work_edit', work.pk), link('删除', 'work_delete', work.pk)]
        rows.append(
            {
                'cells': [
                    work.title,
                    work.classroom.name,
                    work.get_grading_mode_display(),
                    timezone.localtime(work.deadline).strftime('%Y-%m-%d %H:%M'),
                    '已截止' if work.deadline < timezone.now() else '可提交',
                ],
                'actions': actions,
            }
        )
    return table(
        request,
        '作业管理',
        ['作业', '教学班', '批阅方式', '截止时间', '状态'],
        rows,
        create=link('上传题目文件', 'work_new')
        if classes_for(request.user, 'edit').exists()
        else None,
    )


@login_required
def work_edit(request, pk=None):
    if role(request.user) != 'teacher':
        raise PermissionDenied
    work = work_for(request.user, pk, 'edit') if pk else None
    form = forms.WorkForm(
        request.POST or None, request.FILES or None, instance=work, user=request.user
    )
    if request.method == 'POST' and form.is_valid():
        try:
            saved = save_work(request.user, form)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, '题目文件和提交时限已保存，学生现在可以查看。')
            return redirect('work', pk=saved.pk)
    return form_page(
        request,
        '修改作业' if pk else '上传题目文件',
        form,
        reverse('works'),
        description='先选择机器批阅或非机器批阅。机器批阅上传机器批阅包；非机器批阅上传包含题目DOCX和数据文件的ZIP。',
        secondary_action=(
            link('更新单个文件', 'work_package_file', work.pk)
            if work
            and (
                (work.grading_mode == 'automatic' and work.package and work.package.archive_path)
                or (work.grading_mode == 'manual' and work.materials_path)
            )
            else None
        ),
    )


@login_required
def work_package_file(request, pk):
    if role(request.user) != 'teacher':
        raise PermissionDenied
    work = work_for(request.user, pk, 'edit')
    automatic = work.grading_mode == 'automatic'
    if automatic and (not work.package or not work.package.archive_path):
        raise PermissionDenied
    if not automatic and not work.materials_path:
        raise PermissionDenied
    try:
        archive_path = work.package.archive_path if automatic else work.materials_path
        archive = read_private_bytes(archive_path)
        choices = package_member_choices(archive) if automatic else manual_member_choices(archive)
    except (OSError, ValidationError) as exc:
        messages.error(request, f'原批阅包无法读取：{exc}')
        return redirect('work', pk=pk)
    form = forms.PackageFileUpdateForm(
        request.POST or None, request.FILES or None, member_choices=choices
    )
    if request.method == 'POST' and form.is_valid():
        try:
            update = create_package_update(
                request.user,
                work,
                form.cleaned_data['package_member'],
                form.cleaned_data['replacement_file'],
            )
        except (OSError, ValidationError) as exc:
            form.add_error(None, exc)
        else:
            if update.status == 'activated' and not update.grading_changed:
                messages.success(
                    request,
                    '单个文件已更新；无需调用 Docker 重新批阅。'
                    if work.grading_mode == 'manual'
                    else '单个文件已更新；仅说明文档变化，无需重新批阅。',
                )
            elif update.status == 'activated':
                messages.success(request, '新版本已生效，已有学生提交已重新加入批阅队列。')
            else:
                messages.success(
                    request,
                    '新文件已暂存，正在等待 Docker 验证；旧版本和旧成绩保持不变。',
                )
            return redirect('work', pk=pk)
    return form_page(
        request,
        '更新批阅包中的单个文件',
        form,
        reverse('work', args=[pk]),
        description=(
            '选择原ZIP中的文件并上传替代文件。系统会生成新版本，不会直接修改原ZIP。'
            + (
                '只有修改Word说明文档不重评；修改sample.py或其他批阅文件时，验证通过后重新批阅已有提交。'
                if automatic
                else '非机器批阅材料更新后直接生效，不调用Docker，也不改动已有人工成绩。'
            )
        ),
    )


@login_required
@require_POST
def work_package_retry(request, pk):
    if role(request.user) != 'teacher':
        raise PermissionDenied
    work = work_for(request.user, pk, 'edit')
    update = CourseworkPackageUpdate.objects.filter(
        coursework=work, previous_package=work.package, status='error'
    ).first()
    if not update:
        raise PermissionDenied
    try:
        retry_package_update(request.user, update)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, '已重新加入 Docker 验证队列，旧版本和旧成绩保持不变。')
    return redirect('work', pk=pk)


@login_required
def work_delete(request, pk):
    if role(request.user) != 'teacher':
        raise PermissionDenied
    work = work_for(request.user, pk, 'edit')
    if request.method == 'POST':
        with transaction.atomic():
            work.delete()
            audit(request.user, 'portal.work.delete', str(pk))
        messages.success(request, '作业、提交、成绩及对应文件已永久删除。')
        return redirect('works')
    return page(
        request,
        'confirm',
        '删除作业',
        object=work.title,
        back_url=reverse('work', args=[pk]),
        description='永久删除本作业、所有学生提交、批阅结果和相关文件，无法恢复。其他作业仍在使用的批阅包会保留。',
    )


@login_required
def results(request):
    if role(request.user) not in ('teacher', 'admin'):
        raise PermissionDenied
    works = Coursework.objects.filter(
        classroom__in=classes_for(request.user, 'view_grades'), deleted_at__isnull=True
    ).select_related('classroom')
    selected = request.GET.get('classroom', '')
    if selected.isdigit():
        works = works.filter(classroom_id=int(selected))
    rows = []
    for work in works:
        _, stats = roster_rows(work)
        actions = [link('班级学生结果', 'work_results', work.pk)]
        if allowed(request.user, work.classroom, 'export'):
            actions.append(link('导出报表', 'work_export', work.pk))
        rows.append(
            {
                'cells': [
                    work.classroom.name,
                    work.title,
                    f'{stats[1][1]} / {stats[0][1]}',
                    stats[2][1],
                    stats[3][1],
                    stats[4][1],
                    stats[5][1],
                ],
                'actions': actions,
            }
        )
    return table(
        request,
        '统计汇总与报表',
        ['教学班', '作业', '已交 / 应交', '已批阅', '均分/总分', '最高分', '最低分'],
        rows,
        classrooms=classes_for(request.user, 'view_grades'),
        filter_class=True,
        selected_class=selected,
        description='统计当前在班学生的最后一次提交。未提交、等待批阅及服务异常不计入均分；成绩无需再次发布。',
    )


@login_required
def work_results(request, pk, export=False):
    work = work_for(request.user, pk, 'view_grades')
    rows, stats = roster_rows(work)
    distribution, graded_count = score_distribution(work, rows)
    if export:
        if not allowed(request.user, work.classroom, 'export'):
            raise PermissionDenied
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ['教学班', '作业', '学号', '姓名', '提交状态', '得分', '提交时题目总分', '提交时间']
        )
        for row in rows:
            user, entry = row['student'], row['entry']
            writer.writerow(
                [
                    safe_csv(v)
                    for v in [
                        work.classroom.name,
                        work.title,
                        user.student_no,
                        user.full_name,
                        entry.get_status_display() if entry else '未提交',
                        f'{entry.total:.1f}' if entry and entry.total is not None else '',
                        entry.snapshot['max_score'] if entry else work.max_score,
                        timezone.localtime(entry.submitted_at).strftime('%Y-%m-%d %H:%M:%S')
                        if entry
                        else '',
                    ]
                ]
            )
        audit(request.user, 'portal.results.export', str(pk))
        return csv_response(output.getvalue(), f'coursework-{pk}-results.csv')
    package_update_alert, _ = package_update_display(work)
    return page(
        request,
        'results',
        work.title + ' · 班级结果',
        work=work,
        rows=rows,
        stats=stats,
        score_distribution=distribution,
        distribution_graded_count=graded_count,
        package_update_alert=package_update_alert,
        export=allowed(request.user, work.classroom, 'export'),
        back_url=reverse('results'),
    )


@login_required
def student_results(request, class_id, student_id):
    classroom = get_object_or_404(classes_for(request.user, 'view_grades'), pk=class_id)
    student = get_object_or_404(
        User,
        pk=student_id,
        memberships__classroom=classroom,
        memberships__active=True,
        deleted_at__isnull=True,
    )
    rows = []
    for work in Coursework.objects.filter(classroom=classroom, deleted_at__isnull=True):
        entry = work.entries.filter(student=student).first()
        rows.append(
            {
                'cells': [
                    work.title,
                    entry.get_status_display() if entry else '未提交',
                    f'{entry.total:.1f}' if entry and entry.total is not None else '—',
                ],
                'actions': [link('按题目 / 用例查看', 'entry', entry.pk)] if entry else [],
            }
        )
    return table(
        request,
        f'{student.full_name} · {student.student_no}',
        ['作业', '状态', '得分'],
        rows,
        back_url=reverse('class_detail', args=[class_id]),
    )
