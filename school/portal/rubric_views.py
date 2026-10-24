"""教师端：查看与生成题目评分标准（题目分析智能体）。"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, reverse
from django.views.decorators.http import require_http_methods

from school.course_models import Coursework

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


@login_required
@require_http_methods(['GET', 'POST'])
def work_rubric(request, pk):
    work = _work_for_edit(request, pk)
    rubric = getattr(work, 'rubric', None)

    if request.method == 'POST':
        offline = request.POST.get('mode') == 'offline'
        try:
            rubric = rubric_agent.generate_for(work, offline=offline)
        except rubric_agent.LLMNotConfigured as exc:
            messages.error(request, str(exc))
        except (rubric_agent.LLMError, rubric_agent.RubricParseError) as exc:
            messages.error(request, f'生成失败：{exc}')
        else:
            if offline:
                messages.warning(request, '已使用规则兜底生成，结果标注为“规则兜底”，不是大模型结论。')
            else:
                messages.success(request, '已调用大模型生成评分标准并保存到数据库。')
        return redirect('work_rubric', pk=work.pk)

    return page(
        request,
        'rubric',
        f'{work.title} · 评分标准',
        work=work,
        rubric=rubric,
        llm_status=rubric_agent.llm_status(),
        llm_ready=rubric_agent.llm_configured(),
        back_url=reverse('work', args=[work.pk]),
        back_label='返回作业',
    )


@login_required
def work_rubric_download(request, pk):
    work = _work_for_edit(request, pk)
    rubric = getattr(work, 'rubric', None)
    if rubric is None:
        raise PermissionDenied
    response = HttpResponse(rubric.markdown, content_type='text/markdown; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="rubric-{work.pk}.md"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
