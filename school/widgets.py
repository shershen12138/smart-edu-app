"""带“显示 / 隐藏”按钮的密码输入框。

Django 默认的 ``PasswordInput`` 在表单校验失败时不会回填密码，用户需要
重新输入一遍。教学场景下密码规则较多，重输成本高，因此这里默认回填，
并在输入框右侧输出一个可切换到明文的小按钮（脚本见 static/portal.js）。
"""

from __future__ import annotations

from django import forms
from django.utils.safestring import mark_safe


_EYE_OPEN = (
    '<svg class="eye-open" viewBox="0 0 24 24" width="16" height="16" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">'
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12Z"/>'
    '<circle cx="12" cy="12" r="3"/></svg>'
)
_EYE_OFF = (
    '<svg class="eye-off" viewBox="0 0 24 24" width="16" height="16" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">'
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12Z"/>'
    '<circle cx="12" cy="12" r="3"/><path d="m3 3 18 18"/></svg>'
)


class TogglePasswordInput(forms.PasswordInput):
    """密码框 + 右侧小眼睛按钮；``render_value`` 控制失败后是否保留输入。"""

    def __init__(self, attrs=None, render_value: bool = True):
        super().__init__(attrs=attrs, render_value=render_value)

    def render(self, name, value, attrs=None, renderer=None):
        rendered = super().render(name, value, attrs, renderer)
        toggle = (
            '<button type="button" class="password-toggle" data-password-toggle '
            'aria-label="显示密码" aria-pressed="false" title="显示密码">'
            f'{_EYE_OPEN}{_EYE_OFF}</button>'
        )
        return mark_safe(f'<span class="password-field">{rendered}{toggle}</span>')
