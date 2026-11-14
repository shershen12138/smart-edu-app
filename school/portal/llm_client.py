"""用户自备大模型客户端：评分标准智能体与训练题智能体共用。

设计边界：
- 只使用**当前操作用户**在“大模型配置”弹窗里填写的服务商 / 接口地址 /
  模型名 / API Key（存放在 ``UserLLMConfig``），不读取任何项目级全局 Key；
- 端点必须是 OpenAI 兼容的 ``/chat/completions`` 接口；
- 未配置时抛 ``LLMNotConfigured``，调用方必须显式走规则兜底并标注来源，
  不能把兜底结果当成模型结论。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

from school.models import User, UserLLMConfig

# 常用 OpenAI 兼容服务商预设，选择后自动带出接口地址与默认模型
PROVIDERS: dict[str, dict[str, str]] = {
    'deepseek': {
        'label': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'model': 'deepseek-chat',
    },
    'qwen': {
        'label': '通义千问（DashScope）',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen-plus',
    },
    'moonshot': {
        'label': 'Kimi（月之暗面）',
        'base_url': 'https://api.moonshot.cn/v1',
        'model': 'moonshot-v1-8k',
    },
    'openai': {
        'label': 'OpenAI',
        'base_url': 'https://api.openai.com/v1',
        'model': 'gpt-4o-mini',
    },
    'custom': {'label': '自定义（OpenAI 兼容）', 'base_url': '', 'model': ''},
}

DEFAULT_TIMEOUT = 60.0


class LLMConfigError(ValueError):
    """用户提交的大模型配置不合法。"""


class LLMNotConfigured(RuntimeError):
    """当前用户还没有配置自己的大模型端点。"""


class LLMError(RuntimeError):
    """调用大模型失败（网络、HTTP 状态、返回格式等）。"""


def timeout() -> float:
    try:
        return float(getattr(settings, 'LLM_TIMEOUT', DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def get_config(user) -> UserLLMConfig | None:
    if user is None or not getattr(user, 'pk', None):
        return None
    return UserLLMConfig.objects.filter(user=user).first()


def configured(user) -> bool:
    config = get_config(user)
    return bool(config and config.base_url and config.api_key and config.model)


def mask_key(key: str) -> str:
    """只显示尾部 4 位，避免页面回显完整 Key。"""
    text = (key or '').strip()
    if len(text) <= 8:
        return '***' if text else ''
    return f'{text[:4]}***{text[-4:]}'


def host_of(base_url: str) -> str:
    parsed = urlparse(base_url or '')
    return parsed.netloc or (base_url or '')


def status_text(user) -> str:
    config = get_config(user)
    if not config:
        return (
            '当前账号尚未配置大模型：点击“大模型配置”选择服务商并填写你自己的 API Key，'
            '之后评分标准智能体与训练题智能体都会使用这份个人配置。'
        )
    if not configured(user):
        return '大模型配置不完整（缺少接口地址、模型名或 API Key），请重新填写。'
    return (
        f'当前使用你的个人配置：{config.model} @ {host_of(config.base_url)}'
        f'（Key {mask_key(config.api_key)}）'
    )


def save_config(user, provider: str, base_url: str, model: str, api_key: str) -> UserLLMConfig:
    """保存/更新当前用户的大模型配置，字段做基本校验。"""
    provider = (provider or '').strip() or 'custom'
    if provider not in PROVIDERS:
        provider = 'custom'
    base_url = (base_url or '').strip().rstrip('/')
    model = (model or '').strip()
    api_key = (api_key or '').strip()

    if not base_url:
        raise LLMConfigError('请填写接口地址（OpenAI 兼容端点，如 https://api.deepseek.com）。')
    if not base_url.startswith(('http://', 'https://')):
        raise LLMConfigError('接口地址必须以 http:// 或 https:// 开头。')
    if not model:
        raise LLMConfigError('请填写模型名，例如 deepseek-chat。')
    if not api_key:
        existing = get_config(user)
        if existing is None:
            raise LLMConfigError('请填写你自己的 API Key。')
        api_key = existing.api_key

    config, _ = UserLLMConfig.objects.update_or_create(
        user=user,
        defaults={
            'provider': provider,
            'base_url': base_url,
            'model': model,
            'api_key': api_key,
        },
    )
    return config


def clear_config(user) -> None:
    UserLLMConfig.objects.filter(user=user).delete()


def chat(messages: list[dict[str, str]], user, temperature: float = 0.2) -> str:
    """调用当前用户配置的 OpenAI 兼容对话补全端点。"""
    config = get_config(user)
    if not configured(user):
        raise LLMNotConfigured(
            '当前账号还没有配置大模型。请点击“大模型配置”，选择服务商并填写你自己的 API Key。'
        )
    base = config.base_url
    url = base if base.endswith('/chat/completions') else base + '/chat/completions'
    body = json.dumps(
        {
            'model': config.model,
            'messages': messages,
            'temperature': temperature,
        }
    ).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config.api_key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout()) as response:
            payload: Any = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:200]
        if exc.code in (401, 403):
            raise LLMError(
                f'大模型返回 HTTP {exc.code}：API Key 无效或无权限，请重新配置。{detail}'
            ) from exc
        raise LLMError(f'大模型返回 HTTP {exc.code}：{detail}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f'无法连接大模型端点：{exc}') from exc
    try:
        return payload['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError('大模型返回格式不符合对话补全约定。') from exc
