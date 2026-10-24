import hashlib
import uuid
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError


def save_private(content, suffix='.txt'):
    data = content.encode('utf-8') if isinstance(content, str) else content
    key = f'objects/{uuid.uuid4().hex}{suffix}'
    path = settings.PRIVATE_STORAGE / key
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(data)
    return key


def read_private(key):
    path = (settings.PRIVATE_STORAGE / key).resolve()
    if not path.is_relative_to(settings.PRIVATE_STORAGE.resolve()):
        raise ValidationError('无效文件路径。')
    with path.open('r', encoding='utf-8', newline='') as handle:
        return handle.read()


def read_private_bytes(key):
    path = (settings.PRIVATE_STORAGE / key).resolve()
    if not path.is_relative_to(settings.PRIVATE_STORAGE.resolve()):
        raise ValidationError('无效文件路径。')
    return path.read_bytes()


def code_digest(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()
