"""教师端：查看题目评分标准（题目分析智能体）。

评分标准的生成方式由“上传题目文件”时的勾选决定：
勾选 → 上传即调用大模型生成；未勾选 → 上传即用规则兜底生成（离线演示）。
因此本页只负责展示，不再提供生成按钮；历史作业没有评分标准时，
打开本页会按规则兜底自动补一份，保证随时可见。
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, reverse
from django.views.decorators.http import require_http_methods

from school.course_models import Coursework, CourseworkRubric

from . import rubric_agent
from .access import allowed
from .common_views import page


def _work_for_edit(request, pk):
    work = get_object_or_404(
        Coursework.objects.select_related('classroom'), pk=pk, deleted_at__isnull=True
    )
    if not allowed(request.user, work.classroom, 'edit'):
        raise PermissionDenied
    return work


def _ensure_rubric(request, work):
    """历史作业还没有评分标准时，用规则兜底补一份（不调用大模型）。"""
    rubric = CourseworkRubric.objects.filter(coursework=work).first()
    if rubric is None and work.grading_mode == 'automatic':
        try:
            status, _note = rubric_agent.prepare_for_upload(work, request.user, False)
        except rubric_agent.RubricParseError as exc:
            messages.warning(request, f'暂时无法生成评分标准：{exc}')
            return None
        except Exception:  # noqa: BLE001 -- 展示页不应因生成失败而 500
            messages.warning(request, '暂时无法生成评分标准，请重新上传题目文件后再试。')
            return None
        if status == 'rule':
            messages.info(
                request,
                '该作业此前没有评分标准，已按规则兜底生成（离线演示）。'
                '需要大模型版本时，重新上传题目文件并勾选“自动调用大模型生成评分标准”。',
            )
        rubric = CourseworkRubric.objects.filter(coursework=work).first()
    return rubric


@login_required
@require_http_methods(['GET'])
def work_rubric(request, pk):
    work = _work_for_edit(request, pk)
    rubric = _ensure_rubric(request, work)
    return page(
        request,
        'rubric',
        f'{work.title} · 评分标准',
        work=work,
        rubric=rubric,
        llm_configured=rubric_agent.llm_configured(request.user),
        back_url=reverse('work', args=[work.pk]),
        back_label='返回作业',
    )


@login_required
def work_rubric_download(request, pk):
    work = _work_for_edit(request, pk)
    rubric = CourseworkRubric.objects.filter(coursework=work).first()
    if rubric is None:
        raise PermissionDenied
    response = HttpResponse(rubric.markdown, content_type='text/markdown; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="rubric-{work.pk}.md"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
