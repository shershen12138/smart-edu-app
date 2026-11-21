"""大模型客户端：算法端统一配置优先，个人配置只在显式允许时覆盖。

设计边界：
- 默认使用部署环境里的 ``LLM_BASE_URL`` / ``LLM_MODEL`` / ``LLM_API_KEY``
  （算法端配置），Key 不落库、不进页面、不写日志；
- 页面不提供个人模型配置入口；``UserLLMConfig`` 仅作为旧环境或本地开发的
  后端兜底，不再向学生、教师或管理员展示表单；
- 算法端未配置时（本地开发、离线演示）回退到 ``UserLLMConfig``，旧环境照常可用；
- 端点必须是 OpenAI 兼容的 ``/chat/completions`` 接口；
- 无可用配置时抛 ``LLMNotConfigured``，调用方必须显式走规则兜底并标注来源。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, NamedTuple
from urllib.parse import urlparse

from django.conf import settings

from school.models import UserLLMConfig

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


class ServerConfig(NamedTuple):
    """算法端（部署环境）提供的大模型配置，字段与 UserLLMConfig 对齐，便于统一取用。"""

    provider: str
    base_url: str
    model: str
    api_key: str


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


def server_config() -> ServerConfig | None:
    """读取部署环境里的算法端配置；三项缺一即视为未配置，避免半套配置被误用。"""
    base_url = str(getattr(settings, 'LLM_BASE_URL', '') or '').strip().rstrip('/')
    model = str(getattr(settings, 'LLM_MODEL', '') or '').strip()
    api_key = str(getattr(settings, 'LLM_API_KEY', '') or '').strip()
    if not (base_url and model and api_key):
        return None
    provider = str(getattr(settings, 'LLM_PROVIDER', '') or '').strip() or 'custom'
    if provider not in PROVIDERS:
        provider = 'custom'
    return ServerConfig(provider=provider, base_url=base_url, model=model, api_key=api_key)


def user_override_allowed() -> bool:
    """是否允许个人 Key 覆盖算法端配置；默认关闭。"""
    return bool(getattr(settings, 'LLM_ALLOW_USER_OVERRIDE', False))


def personal_config_enabled() -> bool:
    """个人配置在后端是否可用：算法端未配置，或显式允许覆盖。

    页面已不再提供个人配置入口，此函数仅用于保留旧数据的读取与写入校验。
    """
    return server_config() is None or user_override_allowed()


def _usable(config) -> bool:
    return bool(config and config.base_url and config.api_key and config.model)


def resolve_config(user=None):
    """按「算法端优先」取一份可用配置。

    - 算法端已配置且未允许覆盖 → 算法端配置（不查库，生产默认路径）；
    - 允许覆盖且个人配置完整 → 个人配置；
    - 算法端未配置 → 回退个人配置（本地开发、离线演示）。
    """
    server = server_config()
    if server is not None and not user_override_allowed():
        return server
    personal = get_config(user)
    if server is not None and not _usable(personal):
        return server
    if _usable(personal):
        return personal
    return server


def active_model(user=None) -> str:
    """当前生效的模型名，用于结果来源标注与画像签名。"""
    config = resolve_config(user)
    return config.model if config is not None else ''


def configured(user=None) -> bool:
    """是否存在可用配置（算法端或允许的个人配置）。"""
    return resolve_config(user) is not None


def unconfigured_message() -> str:
    """未配置时的统一提示：由算法端统一补充，不引导用户填写个人 Key。"""
    return (
        '大模型尚未配置：算法端未提供 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY，当前只能走规则兜底。'
        '请联系管理员在服务器环境补充。'
    )


def mask_key(key: str) -> str:
    """只显示尾部 4 位，避免页面回显完整 Key。"""
    text = (key or '').strip()
    if len(text) <= 8:
        return '***' if text else ''
    return f'{text[:4]}***{text[-4:]}'


def host_of(base_url: str) -> str:
    parsed = urlparse(base_url or '')
    return parsed.netloc or (base_url or '')


def status_text(user=None) -> str:
    """页面展示用的配置来源说明：算法端统一配置或允许的个人覆盖。"""
    server = server_config()
    if server is not None and not user_override_allowed():
        return (
            f'由算法端统一配置：{server.model} @ {host_of(server.base_url)}'
            '（全班共用，页面不显示 Key）'
        )
    personal = get_config(user)
    if _usable(personal):
        return (
            f'当前使用你的个人配置：{personal.model} @ {host_of(personal.base_url)}'
            f'（Key {mask_key(personal.api_key)}）'
        )
    if server is not None:
        return (
            f'由算法端统一配置：{server.model} @ {host_of(server.base_url)}'
            '（全班共用，页面不显示 Key）'
        )
    return unconfigured_message()


def normalize_config(
    user, provider: str, base_url: str, model: str, api_key: str
) -> dict[str, str]:
    """校验并归一化一份待保存的配置，返回可直接落库的字段字典。

    只做字段级校验，不写库、不联网，方便调用方先验证再保存。
    """
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

    return {'provider': provider, 'base_url': base_url, 'model': model, 'api_key': api_key}


def save_values(user, values: dict[str, str]) -> UserLLMConfig:
    """把 normalize_config 的结果写入当前用户的配置行。

    算法端已配置且未允许覆盖时拒绝写入，避免页面上出现“保存成功但不生效”。
    """
    if not personal_config_enabled():
        raise LLMConfigError('大模型由算法端统一配置，当前不允许修改个人配置。')
    config, _ = UserLLMConfig.objects.update_or_create(user=user, defaults=values)
    return config


def save_config(user, provider: str, base_url: str, model: str, api_key: str) -> UserLLMConfig:
    """保存/更新当前用户的大模型配置，字段做基本校验。"""
    return save_values(user, normalize_config(user, provider, base_url, model, api_key))


def clear_config(user) -> None:
    UserLLMConfig.objects.filter(user=user).delete()


def endpoint_of(base_url: str) -> str:
    """把用户填写的接口地址补全成对话补全端点。"""
    base = (base_url or '').rstrip('/')
    return base if base.endswith('/chat/completions') else base + '/chat/completions'


def _request_json(
    base_url: str, api_key: str, body: dict[str, Any], timeout_seconds: float | None = None
) -> Any:
    """向 OpenAI 兼容端点发一次 POST，把网络/HTTP 故障统一转成 LLMError。"""
    request = urllib.request.Request(
        endpoint_of(base_url),
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds or timeout()) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:200]
        if exc.code in (401, 403):
            raise LLMError(
                f'API Key 无效或没有该模型的调用权限（HTTP {exc.code}），请核对后重新填写。{detail}'
            ) from exc
        if exc.code == 404:
            raise LLMError(
                '接口地址不正确（HTTP 404）：请填写 OpenAI 兼容端点，'
                f'例如 https://api.deepseek.com 或 https://api.openai.com/v1。{detail}'
            ) from exc
        raise LLMError(f'大模型返回 HTTP {exc.code}：{detail}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f'无法连接大模型端点：{exc}') from exc


def probe_config(values: dict[str, str], timeout_seconds: float | None = None) -> None:
    """保存前用一次最小请求确认接口地址与 API Key 真的可用。

    只发一个 ``max_tokens=1`` 的问候语，成本可忽略；失败抛 ``LLMError``，
    调用方据此拒绝保存并提示具体原因。
    """
    payload = _request_json(
        values['base_url'],
        values['api_key'],
        {
            'model': values['model'],
            'messages': [{'role': 'user', 'content': 'ping'}],
            'temperature': 0,
            'max_tokens': 1,
        },
        timeout_seconds,
    )
    if not isinstance(payload, dict) or 'choices' not in payload:
        raise LLMError(
            '端点返回内容不是对话补全格式，请确认接口地址是 OpenAI 兼容端点（通常以 /v1 结尾）。'
        )


def chat(messages: list[dict[str, str]], user=None, temperature: float = 0.2) -> str:
    """调用当前生效配置（算法端优先，其次允许的个人配置）的对话补全端点。"""
    config = resolve_config(user)
    if config is None:
        raise LLMNotConfigured(unconfigured_message())
    payload = _request_json(
        config.base_url,
        config.api_key,
        {'model': config.model, 'messages': messages, 'temperature': temperature},
    )
    try:
        return payload['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError('大模型返回格式不符合对话补全约定。') from exc
