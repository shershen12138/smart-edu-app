import csv
import io
from functools import wraps

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
from . import rubric_agent
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


def role_required(*roles):
    """装饰器模式：把各视图重复的角色检查收敛到一个装饰器。"""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if role(request.user) not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


teacher_required = role_required('teacher')


def _filtered_by_classroom(request, queryset):
    """works 与 results 共用的班级筛选；返回 (过滤后的查询集, 选中班级ID)。"""
    selected = request.GET.get('classroom', '')
    if selected.isdigit():
        queryset = queryset.filter(classroom_id=int(selected))
    return queryset, selected


@login_required
def works(request):
    # 学生访问时跳转仪表盘，因此不能用 teacher_required 装饰器
    if role(request.user) == 'student':
        return redirect('dashboard')
    if role(request.user) != 'teacher':
        raise PermissionDenied
    qs, selected = _filtered_by_classroom(
        request,
        Coursework.objects.filter(
            classroom__in=classes_for(request.user), deleted_at__isnull=True
        ).select_related('classroom'),
    )
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


def _prepare_rubric(request, work, auto_llm: bool) -> None:
    """按上传时“自动调用大模型生成评分标准”的勾选结果生成评分标准。

    勾选：用当前教师自己的大模型配置生成；未勾选（或未配置、调用失败）：
    直接用规则兜底生成（离线演示），保证打开“评分标准”页就能看到内容。
    """
    try:
        status, note = rubric_agent.prepare_for_upload(work, request.user, auto_llm)
    except Exception:  # noqa: BLE001 -- 生成失败不能回滚已保存的作业
        messages.warning(request, '评分标准生成失败，可稍后重新上传题目文件重试。')
        return
    if not note:
        return
    if status == 'llm':
        messages.success(request, note)
    elif status == 'rule':
        messages.warning(request, note)
    else:
        messages.info(request, note)


@login_required
@teacher_required
def work_edit(request, pk=None):
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
            _prepare_rubric(request, saved, bool(form.cleaned_data.get('auto_rubric')))
            return redirect('work', pk=saved.pk)
    return form_page(
        request,
        '修改作业' if pk else '上传题目文件',
        form,
        reverse('works'),
        template='work_form',
        work=work,
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


class AutomaticPackageStrategy:
    """策略模式：机器批阅作业的单文件更新差异点。"""

    def archive_path(self, work):
        if not work.package or not work.package.archive_path:
            raise PermissionDenied
        return work.package.archive_path

    def member_choices(self, archive):
        return package_member_choices(archive)

    def description(self):
        return '只有修改Word说明文档不重评；修改sample.py或其他批阅文件时，验证通过后重新批阅已有提交。'

    def success_message(self, update):
        if update.status == 'activated':
            return (
                '单个文件已更新；仅说明文档变化，无需重新批阅。'
                if not update.grading_changed
                else '新版本已生效，已有学生提交已重新加入批阅队列。'
            )
        return '新文件已暂存，正在等待 Docker 验证；旧版本和旧成绩保持不变。'


class ManualPackageStrategy:
    """策略模式：非机器批阅作业的单文件更新差异点。"""

    def archive_path(self, work):
        if not work.materials_path:
            raise PermissionDenied
        return work.materials_path

    def member_choices(self, archive):
        return manual_member_choices(archive)

    def description(self):
        return '非机器批阅材料更新后直接生效，不调用Docker，也不改动已有人工成绩。'

    def success_message(self, update):
        if update.status == 'activated' and not update.grading_changed:
            return '单个文件已更新；无需调用 Docker 重新批阅。'
        if update.status == 'activated':
            return '新版本已生效，已有学生提交已重新加入批阅队列。'
        return '新文件已暂存，正在等待 Docker 验证；旧版本和旧成绩保持不变。'


def package_strategy(work):
    """按批阅方式选择对应的单文件更新策略。"""
    return AutomaticPackageStrategy() if work.grading_mode == 'automatic' else ManualPackageStrategy()


@login_required
@teacher_required
def work_package_file(request, pk):
    work = work_for(request.user, pk, 'edit')
    strategy = package_strategy(work)
    archive_path = strategy.archive_path(work)
    try:
        archive = read_private_bytes(archive_path)
        choices = strategy.member_choices(archive)
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
            messages.success(request, strategy.success_message(update))
            if work.grading_mode == 'manual':
                # 非机器批阅材料直接生效，立即后台重建评分标准；
                # 机器批阅由 activate_package_update 在验证生效后触发。
                rubric_agent.schedule_regeneration(work.pk)
                messages.info(request, '材料已更新，正在后台重新生成评分标准。')
            elif update.status != 'activated':
                messages.info(request, '新批阅包验证生效后将自动重建评分标准。')
            return redirect('work', pk=pk)
    return form_page(
        request,
        '更新批阅包中的单个文件',
        form,
        reverse('work', args=[pk]),
        description='选择原ZIP中的文件并上传替代文件。系统会生成新版本，不会直接修改原ZIP。'
        + strategy.description(),
    )


@login_required
@require_POST
@teacher_required
def work_package_retry(request, pk):
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
@teacher_required
def work_delete(request, pk):
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
@role_required('teacher', 'admin')
def results(request):
    works, selected = _filtered_by_classroom(
        request,
        Coursework.objects.filter(
            classroom__in=classes_for(request.user, 'view_grades'), deleted_at__isnull=True
        ).select_related('classroom'),
    )
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


EXPORT_HEADERS = ['教学班', '作业', '学号', '姓名', '提交状态', '得分', '提交时题目总分', '提交时间']


def _export_row(work, row):
    """把一行名册数据转成 CSV 单元格；未提交学生的字段用占位值。"""
    user, entry = row['student'], row['entry']
    return [
        work.classroom.name,
        work.title,
        user.student_no,
        user.full_name,
        entry.get_status_display() if entry else '未提交',
        f'{entry.total:.1f}' if entry and entry.total is not None else '',
        entry.snapshot['max_score'] if entry else work.max_score,
        timezone.localtime(entry.submitted_at).strftime('%Y-%m-%d %H:%M:%S') if entry else '',
    ]


def _results_csv(request, work, rows):
    """单一职责：班级结果导出只在这里组装 CSV，其他视图不关心格式。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPORT_HEADERS)
    for row in rows:
        writer.writerow(safe_csv(v) for v in _export_row(work, row))
    audit(request.user, 'portal.results.export', str(work.pk))
    return csv_response(output.getvalue(), f'coursework-{work.pk}-results.csv')


@login_required
def work_results(request, pk, export=False):
    work = work_for(request.user, pk, 'view_grades')
    rows, stats = roster_rows(work)
    if export:
        if not allowed(request.user, work.classroom, 'export'):
            raise PermissionDenied
        return _results_csv(request, work, rows)
    distribution, graded_count = score_distribution(work, rows)
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
