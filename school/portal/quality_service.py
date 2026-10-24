"""把学生提交的源码接入代码质量评测智能体，生成并缓存个性化报告。

边界：
- 只处理机器批阅作业的单文件提交（教师端上传的题目包决定函数清单）；
- 分析与评分在本机完成，不执行学生代码；
- 报告与雷达图写入私有存储，数据库只保存元数据与结构化明细。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

from school import storage
from school.course_models import PrivateFileCleanup, QualityReport

from tools.code_quality_agent import service as agent

RUBRIC_FILENAME = '03评分量表.md'


def rubric_path() -> Path:
    return Path(settings.BASE_DIR) / 'data' / RUBRIC_FILENAME


def supported(entry) -> bool:
    """该提交是否可以生成代码质量报告。"""
    return (
        entry.coursework.grading_mode == 'automatic'
        and entry.source_path.endswith('.py')
    )


def generate(entry, force: bool = False) -> QualityReport:
    if not supported(entry):
        raise ValidationError('非机器批阅作业不生成代码质量报告。')

    source = storage.read_private(entry.source_path)
    digest = entry.source_hash or storage.code_digest(source)

    existing = QualityReport.objects.filter(submission=entry).first()
    if existing and not force and existing.source_sha256 == digest:
        return existing

    items = [
        (item.function_name, item.title) for item in entry.coursework.items.all()
    ]
    display_name = entry.student.get_full_name() or entry.student.username
    workdir = Path(settings.PRIVATE_STORAGE) / 'quality-tmp'
    analysis, dimensions, rubric_note = agent.analyze(
        source, items, rubric_path(), workdir, name=display_name
    )
    radar = agent.radar_png(analysis, dimensions)
    markdown = agent.markdown(analysis, dimensions, rubric_note)
    payload = agent.payload(analysis, dimensions, rubric_note, bool(radar))

    markdown_key = storage.save_private(markdown, '.md')
    radar_key = storage.save_private(radar, '.png') if radar else ''

    if existing:
        for key in (existing.markdown_key, existing.radar_key):
            if key:
                PrivateFileCleanup.objects.get_or_create(path=key)

    report, _ = QualityReport.objects.update_or_create(
        submission=entry,
        defaults={
            'source_sha256': digest,
            'total': Decimal(str(round(analysis.total, 1))),
            'payload': payload,
            'markdown_key': markdown_key,
            'radar_key': radar_key,
        },
    )
    return report
