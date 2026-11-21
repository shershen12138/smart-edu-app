"""学生端：综合能力分析（布鲁姆认知水平 + 计算思维水平）。

原来这段内容挂在「弱项练习」页顶部，和训练题生成混在一起；
现在独立成左侧导航的一级模块，弱项练习只负责训练题。
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import capability_service
from .access import require_role
from .common_views import page
from .navigation import back_target

logger = logging.getLogger(__name__)


def capability_context(student) -> dict:
    """综合能力画像失败时降级为空态，不能让整页 500。"""
    try:
        return capability_service.view_model(student)
    except Exception:
        logger.warning('综合能力画像生成失败 student=%s', student.pk, exc_info=True)
        return {
            'ready': False,
            'refreshing': False,
            'llm_ready': False,
            'empty_reason': '综合能力分析暂时不可用，请稍后刷新重试。',
        }


@login_required
@require_http_methods(['GET'])
def capability_analysis(request):
    require_role(request.user, 'student')
    return page(
        request,
        'capability',
        '综合能力分析',
        capability=capability_context(request.user),
        back_url=back_target(request, reverse('dashboard')),
    )
