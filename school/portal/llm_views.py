"""用户级大模型配置：在弹窗里保存自己的服务商、接口地址、模型与 API Key。"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from . import llm_client


def _next_url(request) -> str:
    """保存后回到来源页；拒绝站外跳转。"""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse('dashboard')


def _wants_json(request) -> bool:
    """弹窗用 fetch 提交时返回 JSON，浏览器原生提交时保持重定向。"""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _failure(request, message: str, wants_json: bool):
    messages.error(request, message)
    if wants_json:
        return JsonResponse({'ok': False, 'error': message}, status=400)
    return redirect(_next_url(request))


@login_required
@require_http_methods(['POST'])
def llm_config(request):
    """保存当前用户的模型配置（个人 Key 只写入自己的账号）。

    保存前先发一次最小请求：接口地址写错、Key 无效或端点不可达时不落库，
    通过弹窗把具体原因告诉教师，避免"保存成功但用不了"。
    """
    wants_json = _wants_json(request)
    try:
        values = llm_client.normalize_config(
            request.user,
            request.POST.get('provider', ''),
            request.POST.get('base_url', ''),
            request.POST.get('model', ''),
            request.POST.get('api_key', ''),
        )
        if getattr(settings, 'LLM_VERIFY_ON_SAVE', True):
            llm_client.probe_config(
                values, getattr(settings, 'LLM_VERIFY_TIMEOUT', None)
            )
        config = llm_client.save_values(request.user, values)
    except llm_client.LLMConfigError as exc:
        return _failure(request, f'模型配置未保存：{exc}', wants_json)
    except llm_client.LLMError as exc:
        return _failure(request, f'接口地址或 API Key 校验未通过：{exc}', wants_json)

    message = (
        f'已保存你的模型配置：{config.model} @ {llm_client.host_of(config.base_url)}'
        f'（Key {llm_client.mask_key(config.api_key)}），仅对当前账号生效。'
    )
    messages.success(request, message)
    target = _next_url(request)
    if wants_json:
        return JsonResponse({'ok': True, 'next': target, 'message': message})
    return redirect(target)


@login_required
@require_http_methods(['POST'])
def llm_config_reveal(request):
    """返回当前用户已保存的 API Key（JSON），供弹窗“显示 / 复制”使用。

    仅响应本人请求；接口要求 POST + CSRF Token，Key 不会出现在 URL 或日志里。
    """
    config = llm_client.get_config(request.user)
    return JsonResponse({'api_key': (config.api_key or '') if config else ''})


@login_required
@require_http_methods(['POST'])
def llm_config_clear(request):
    """删除当前用户的配置；之后点“调用大模型”会先要求重新填写。"""
    llm_client.clear_config(request.user)
    messages.info(request, '已删除你的模型配置，再次调用大模型前需要重新填写。')
    return redirect(_next_url(request))
