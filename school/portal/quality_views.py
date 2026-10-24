"""学生代码质量报告的查看、雷达图与 Markdown 下载。"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, reverse
from django.views.decorators.http import require_GET

from school import storage
from school.course_models import CourseworkSubmission, QualityReport

from . import quality_service
from .access import allowed, role
from .common_views import page, private_download


def _entry_for(request, pk):
    entry = get_object_or_404(
        CourseworkSubmission.objects.select_related('student', 'coursework__classroom'),
        pk=pk,
    )
    if role(request.user) == 'student':
        if entry.student_id != request.user.pk:
            raise PermissionDenied
    elif not allowed(request.user, entry.coursework.classroom, 'view_grades'):
        raise PermissionDenied
    return entry


@login_required
@require_GET
def quality_report(request, pk):
    entry = _entry_for(request, pk)
    work = entry.coursework
    if not quality_service.supported(entry):
        messages.error(request, '只有机器批阅的单文件提交才提供代码质量报告。')
        return redirect('entry', pk=entry.pk)

    try:
        report = quality_service.generate(entry)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if exc.messages else '无法生成代码质量报告。')
        return redirect('entry', pk=entry.pk)
    except Exception:
        messages.error(request, '代码质量报告生成失败，请稍后重试或联系教师。')
        return redirect('entry', pk=entry.pk)

    return page(
        request,
        'quality',
        f'{entry.student.get_full_name() or entry.student.username} 的代码评测报告',
        entry=entry,
        work=work,
        report=report,
        detail=report.payload,
        radar_url=reverse('quality_radar', args=[entry.pk]) if report.radar_key else '',
        back_url=reverse('work', args=[work.pk]),
        back_label='返回作业',
    )


@login_required
@require_GET
def quality_radar(request, pk):
    entry = _entry_for(request, pk)
    report = get_object_or_404(QualityReport, submission=entry)
    if not report.radar_key:
        raise Http404('该报告没有雷达图。')
    data = storage.read_private_bytes(report.radar_key)
    response = HttpResponse(data, content_type='image/png')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=600'
    return response


@login_required
@require_GET
def quality_markdown(request, pk):
    entry = _entry_for(request, pk)
    report = get_object_or_404(QualityReport, submission=entry)
    if not report.markdown_key:
        raise Http404('该报告没有 Markdown 文件。')
    name = f'{entry.student.student_no or entry.student.username}_第{entry.sequence}次_代码评测报告.md'
    return private_download(report.markdown_key, name)
