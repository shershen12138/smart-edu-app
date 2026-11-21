"""TOTP 动态口令（RFC 6238），作为口令之外的第二鉴别因素。

不引入第三方依赖，便于离线部署；密钥按字段加密保存，备份码只存哈希。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

from django.contrib.auth.hashers import check_password, make_password

from .models import TOTPDevice

DIGITS = 6
STEP = 30
BACKUP_CODE_COUNT = 8
MAX_FAILED_ATTEMPTS = 5


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def _code(secret: str, counter: int, digits: int = DIGITS) -> str:
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def current_code(secret: str, at: float | None = None) -> str:
    return _code(secret, int((at or time.time()) // STEP))


def verify_code(secret: str, code: str, window: int = 1, at: float | None = None) -> bool:
    """允许前后各一个时间窗，容忍客户端时钟偏差。"""
    code = (code or '').strip().replace(' ', '')
    if not code.isdigit():
        return False
    now = int((at or time.time()) // STEP)
    return any(
        hmac.compare_digest(_code(secret, now + offset), code)
        for offset in range(-window, window + 1)
    )


def provisioning_uri(username: str, secret: str) -> str:
    label = f'coursejudge:{username}'
    return (
        f'otpauth://totp/{label}?secret={secret}'
        f'&issuer=coursejudge&digits={DIGITS}&period={STEP}'
    )


def issue_backup_codes(user) -> list[str]:
    codes = [
        f'{secrets.token_hex(3)}-{secrets.token_hex(3)}' for _ in range(BACKUP_CODE_COUNT)
    ]
    TOTPDevice.objects.filter(user=user).update(
        backup_codes=[make_password(code) for code in codes]
    )
    return codes


def consume_backup_code(device: TOTPDevice, code: str) -> bool:
    code = (code or '').strip().lower()
    for index, encoded in enumerate(device.backup_codes or []):
        if check_password(code, encoded):
            remaining = list(device.backup_codes)
            remaining.pop(index)
            device.backup_codes = remaining
            device.save(update_fields=['backup_codes'])
            return True
    return False
