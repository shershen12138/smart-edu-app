"""口令复杂度校验：按三级等保要求同时约束长度与字符种类。

规则为“大写字母、小写字母、数字、特殊字符四类中至少包含三类”，
比强制四类更易用，同时仍能挡住纯数字、纯字母等常见弱口令。
注册到 ``AUTH_PASSWORD_VALIDATORS`` 后，修改密码、管理员重置密码、
批量导入初始密码和命令行创建账号都会走同一套规则。
"""

from __future__ import annotations

import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

MIN_LENGTH = 8
MIN_CHARACTER_CLASSES = 3

HELP_TEXT = (
    '密码至少 8 位，且必须包含大写字母、小写字母、数字、特殊字符'
    '（如 _ ! @ #）中的至少三类，不能包含空格。'
)

_CATEGORY_PATTERNS = (
    ('大写字母', r'[A-Z]'),
    ('小写字母', r'[a-z]'),
    ('数字', r'\d'),
    ('特殊字符', r'[^A-Za-z0-9]'),
)


class PasswordComplexityValidator:
    """四类字符中至少出现 ``min_character_classes`` 类（默认三类）。"""

    def __init__(
        self,
        min_length: int = MIN_LENGTH,
        min_character_classes: int = MIN_CHARACTER_CLASSES,
    ):
        self.min_length = min_length
        self.min_character_classes = min_character_classes

    def validate(self, password: str, user=None) -> None:
        if re.search(r'\s', password):
            raise ValidationError(
                f'密码设置失败：不能包含空格。{HELP_TEXT}',
                code='password_too_weak',
            )
        problems = []
        if len(password) < self.min_length:
            problems.append(f'长度（至少 {self.min_length} 位）')
        present = [
            name for name, pattern in _CATEGORY_PATTERNS if re.search(pattern, password)
        ]
        if len(present) < self.min_character_classes:
            problems.append(
                '字符种类（需在大写字母、小写字母、数字、特殊字符中至少包含三类，'
                f'当前只有 {len(present)} 类）'
            )
        if problems:
            raise ValidationError(
                f'密码设置失败：{"；".join(problems)}。{HELP_TEXT}',
                code='password_too_weak',
            )

    def get_help_text(self) -> str:
        return HELP_TEXT

    def deconstruct(self):
        return (
            'school.password_policy.PasswordComplexityValidator',
            [],
            {
                'min_length': self.min_length,
                'min_character_classes': self.min_character_classes,
            },
        )


def needs_upgrade(password: str, user=None) -> bool:
    """登录成功后判断已有口令是否仍满足当前策略。

    只有在拿到登录明文口令时才能判断（库里存的是哈希），
    因此这里只在登录视图调用一次，不作为每次请求的中间件检查。
    """
    try:
        validate_password(password, user)
    except ValidationError:
        return True
    return False
