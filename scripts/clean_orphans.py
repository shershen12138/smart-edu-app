"""清理私有存储里的孤儿文件。

扫描 PRIVATE_STORAGE/objects 下所有文件，删除数据库任何字符字段都
没有引用的文件（测试残留、历史迭代遗留等）。用法：

    python scripts/clean_orphans.py            # 只统计，不删除
    python scripts/clean_orphans.py --delete   # 真正删除
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.db import models as dj  # noqa: E402

PREFIX = 'objects/'


def referenced_keys() -> set[str]:
    """收集数据库里所有以 objects/ 开头的存储键（含 JSON 字段内部）。"""
    import json

    keys: set[str] = set()

    def collect(text: str) -> None:
        start = text.find(PREFIX)
        while start >= 0:
            end = start + len(PREFIX)
            while end < len(text) and (text[end].isalnum() or text[end] in '._-/'):
                end += 1
            keys.add(text[start:end].split('?')[0].strip())
            start = text.find(PREFIX, end)

    for model in apps.get_models():
        for field in model._meta.get_fields():
            if not isinstance(field, (dj.CharField, dj.TextField, dj.JSONField)):
                continue
            column = field.column
            for value in model.objects.values_list(column, flat=True):
                if value is None:
                    continue
                text = (
                    json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(field, dj.JSONField)
                    else str(value)
                )
                collect(text)
    return keys


def main() -> None:
    delete = '--delete' in sys.argv
    storage = settings.PRIVATE_STORAGE / PREFIX
    keys = referenced_keys()
    referenced = {str(storage.parent / key).lower() for key in keys}
    orphans = [
        path
        for path in storage.rglob('*')
        if path.is_file() and str(path).lower() not in referenced
    ]
    print(f'数据库引用文件数: {len(referenced)}')
    print(f'孤儿文件数: {len(orphans)}')
    if not delete:
        print('(预览模式，加 --delete 执行删除)')
        for path in orphans[:10]:
            print('  例:', path.name)
        return
    freed = 0
    for path in orphans:
        freed += path.stat().st_size
        path.unlink()
    print(f'已删除 {len(orphans)} 个文件，释放 {freed / 1024 / 1024:.1f} MB')


if __name__ == '__main__':
    main()
