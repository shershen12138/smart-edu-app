"""字段级加密：API Key、口令恢复副本等敏感数据不再明文落库（8.1.4.7）。

密钥优先读取 ``FIELD_ENCRYPTION_KEY``；未配置时由 ``SECRET_KEY`` 派生，
升级后无需额外配置即可工作。密钥一旦更换，历史密文将无法解密，
因此生产环境应把 ``FIELD_ENCRYPTION_KEY`` 固定保存在密钥管理系统中。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

_FERNET_PREFIX = 'gAAAAA'


def _fernet() -> Fernet:
    configured = (getattr(settings, 'FIELD_ENCRYPTION_KEY', '') or '').strip()
    material = f'{configured or settings.SECRET_KEY}:field-encryption'.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def encrypt_value(raw) -> str:
    if raw in (None, ''):
        return ''
    return _fernet().encrypt(str(raw).encode()).decode()


def decrypt_value(stored) -> str:
    if stored in (None, ''):
        return ''
    text = str(stored)
    if not text.startswith(_FERNET_PREFIX):
        # 兼容升级前的明文数据；下次保存时会自动重新加密
        return text
    try:
        return _fernet().decrypt(text.encode()).decode()
    except (InvalidToken, ValueError):
        return text


class EncryptedTextField(models.TextField):
    """透明加解密的文本字段：代码读写仍是明文，数据库保存密文。"""

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value)

    def to_python(self, value):
        if value is None:
            return value
        return decrypt_value(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        if str(value).startswith(_FERNET_PREFIX):
            return value
        return encrypt_value(value)


class EncryptedCharField(models.CharField):
    """透明加解密的短文本字段，用于 API Key 等有长度上限的数据。"""

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value)

    def to_python(self, value):
        if value is None:
            return value
        return decrypt_value(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        if str(value).startswith(_FERNET_PREFIX):
            return value
        return encrypt_value(value)
