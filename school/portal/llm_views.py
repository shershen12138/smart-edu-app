"""用户级大模型配置：在弹窗里保存自己的服务商、接口地址、模型与 API Key。"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
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


@login_required
@require_http_methods(['POST'])
def llm_config(request):
    """保存当前用户的大模型配置（个人 Key 只写入自己的账号）。"""
    try:
        config = llm_client.save_config(
            request.user,
            request.POST.get('provider', ''),
            request.POST.get('base_url', ''),
            request.POST.get('model', ''),
            request.POST.get('api_key', ''),
        )
    except llm_client.LLMConfigError as exc:
        messages.error(request, f'大模型配置未保存：{exc}')
    else:
        messages.success(
            request,
            f'已保存你的大模型配置：{config.model} @ {llm_client.host_of(config.base_url)}'
            f'（Key {llm_client.mask_key(config.api_key)}），仅对当前账号生效。',
        )
    return redirect(_next_url(request))


@login_required
@require_http_methods(['POST'])
def llm_config_clear(request):
    """删除当前用户的配置；之后点“调用大模型”会先要求重新填写。"""
    llm_client.clear_config(request.user)
    messages.info(request, '已删除你的大模型配置，再次调用大模型前需要重新填写。')
    return redirect(_next_url(request))
