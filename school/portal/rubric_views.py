"""教师端：查看题目评分标准（题目分析智能体）。

评分标准的生成方式由“上传题目文件”时的勾选决定：
勾选 → 上传即调用大模型生成；未勾选 → 上传即用规则兜底生成（离线演示）。
本页以展示为主；只有当前内容是**规则兜底**（例如上传时大模型校验失败、
未配置或调用异常）时，才额外给一个“重新生成”按钮，
让教师修好大模型配置后不必重新上传题目文件也能换成大模型版本。
历史作业没有评分标准时，打开本页仍会按规则兜底自动补一份。
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, reverse
from django.views.decorators.http import require_http_methods, require_POST

from school.course_models import Coursework, CourseworkRubric

from . import rubric_agent
from .access import allowed
from .common_views import page
from .navigation import back_target


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
                '需要大模型版本时，可点本页右上角“重新生成”。',
            )
        rubric = CourseworkRubric.objects.filter(coursework=work).first()
    return rubric


@login_required
@require_http_methods(['GET'])
def work_rubric(request, pk):
    work = _work_for_edit(request, pk)
    rubric = _ensure_rubric(request, work)
    # 只有规则兜底（或还没有标准）才给“重新生成”：大模型版本不需要重复生成
    can_regenerate = work.grading_mode == 'automatic' and (
        rubric is None or rubric.source != 'llm'
    )
    return page(
        request,
        'rubric',
        f'{work.title} · 评分标准',
        work=work,
        rubric=rubric,
        can_regenerate=can_regenerate,
        llm_configured=rubric_agent.llm_configured(request.user),
        back_url=back_target(request, reverse('work', args=[work.pk])),
        back_label='返回作业',
    )


@login_required
@require_POST
def work_rubric_regenerate(request, pk):
    """用当前教师自己的大模型重生成评分标准；失败保留原标准并提示原因。"""
    work = _work_for_edit(request, pk)
    if work.grading_mode != 'automatic':
        messages.info(request, '非机器批阅作业不使用评分标准。')
        return redirect('work_rubric', pk=work.pk)
    try:
        rubric_agent.generate_for(work, force=True, user=request.user)
    except rubric_agent.LLMNotConfigured:
        messages.error(
            request,
            '当前账号还没有配置大模型：请先点击侧边栏“大模型配置”填写自己的 API Key，再重新生成。',
        )
    except (rubric_agent.LLMError, rubric_agent.RubricParseError) as exc:
        messages.error(request, f'重新生成评分标准失败，已保留原有内容：{exc}')
    else:
        messages.success(request, '已使用你的大模型重新生成评分标准。')
    return redirect('work_rubric', pk=work.pk)


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
