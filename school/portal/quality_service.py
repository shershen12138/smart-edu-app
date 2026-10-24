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

from tools.code_quality_agent import models as agent_models
from tools.code_quality_agent import rubric as agent_rubric
from tools.code_quality_agent import service as agent

RUBRIC_FILENAME = '03评分量表.md'


def rubric_path() -> Path:
    return Path(settings.BASE_DIR) / 'data' / RUBRIC_FILENAME


def _stored_dimensions(stored) -> list[agent_models.Dimension]:
    dimensions = []
    for item in stored.dimensions or []:
        key = str(item.get('key', '')).strip()
        label = str(item.get('label', '')).strip() or key
        try:
            weight = float(item.get('weight', 0))
        except (TypeError, ValueError):
            weight = 0.0
        if key and weight > 0:
            dimensions.append(agent_models.Dimension(key, label, weight / 100))
    if len(dimensions) < 5:
        return []
    total = sum(dimension.weight for dimension in dimensions) or 1
    return [
        agent_models.Dimension(
            dimension.key, dimension.label, round(dimension.weight / total, 4)
        )
        for dimension in dimensions
    ]


def dimensions_for(coursework) -> tuple[list[agent_models.Dimension], str]:
    """取该题目的评分标准：结构化维度优先，其次解析数据库中的量表 Markdown。

    两者都不可用时才回退 `data/` 下的通用量表文件或内置默认量表。
    """
    stored = getattr(coursework, 'rubric', None)
    if stored:
        dimensions = _stored_dimensions(stored)
        if dimensions:
            return (
                dimensions,
                f'使用作业评分标准（{stored.get_source_display()}，{len(dimensions)} 维）',
            )
        parsed = agent_rubric.dimensions_from_text(
            stored.markdown or '', '作业评分标准'
        )
        if parsed:
            dimensions, _ = parsed
            return (
                dimensions,
                f'使用作业评分标准（{stored.get_source_display()}，'
                f'{len(dimensions)} 维，取自评分标准 Markdown）',
            )
    return agent_rubric.load_rubric(rubric_path())


def knowledge_points_for(coursework, items) -> dict[str, tuple[str, ...]]:
    """评分标准（CourseworkRubric）里的“作业考察的知识点”，按函数名分组。

    报告逐题明细的知识点列直接使用这份清单，而不是评测器按题库规格推断的标签；
    作业还没有评分标准时返回空，由评测器回退到题库规格。
    `tasks` 为空的知识点视为覆盖该作业的全部题目。
    """
    stored = getattr(coursework, 'rubric', None)
    if not stored:
        return {}
    functions = [name for name, _ in items]
    known = set(functions)
    grouped: dict[str, list[str]] = {}
    for point in stored.knowledge_points or []:
        if not isinstance(point, dict):
            continue
        name = str(point.get('name', '')).strip()
        if not name:
            continue
        raw_tasks = point.get('tasks') or []
        if isinstance(raw_tasks, str):
            raw_tasks = [raw_tasks]
        tasks = [str(task).strip() for task in raw_tasks if str(task).strip()]
        targets = [task for task in tasks if task in known] if tasks else functions
        for function in targets:
            names = grouped.setdefault(function, [])
            if name not in names:
                names.append(name)
    return {function: tuple(names) for function, names in grouped.items()}


def supported(entry) -> bool:
    """该提交是否可以生成代码质量报告。"""
    return (
        entry.coursework.grading_mode == 'automatic'
        and entry.source_path.endswith('.py')
    )


def _specs_signature(items) -> str:
    """题库考点的指纹：补齐某门课的规格后，旧报告要自动重算。"""
    known = agent.known_specs()
    return '|'.join(
        f'{name}:{",".join(known[name].points)}' for name, _ in items if name in known
    )


def _knowledge_signature(points: dict[str, tuple[str, ...]]) -> str:
    """评分标准知识点的指纹：重新生成评分标准后，旧报告要自动重算。"""
    return '|'.join(
        f'{function}:{",".join(names)}' for function, names in sorted(points.items())
    )


def generate(entry, force: bool = False) -> QualityReport:
    if not supported(entry):
        raise ValidationError('非机器批阅作业不生成代码质量报告。')

    source = storage.read_private(entry.source_path)
    digest = entry.source_hash or storage.code_digest(source)
    items = [
        (item.function_name, item.title) for item in entry.coursework.items.all()
    ]
    dimensions, rubric_note = dimensions_for(entry.coursework)
    knowledge_points = knowledge_points_for(entry.coursework, items)
    # 量表维度、题库考点或评分标准知识点变了都要重算，不能只比源码摘要。
    signature = (
        '|'.join(
            f'{dimension.key}:{dimension.label}:{dimension.weight}'
            for dimension in dimensions
        )
        + '#'
        + _specs_signature(items)
        + '#'
        + _knowledge_signature(knowledge_points)
    )

    existing = QualityReport.objects.filter(submission=entry).first()
    if (
        existing
        and not force
        and existing.source_sha256 == digest
        and (existing.payload or {}).get('rubric_signature') == signature
    ):
        return existing
    display_name = entry.student.get_full_name() or entry.student.username
    workdir = Path(settings.PRIVATE_STORAGE) / 'quality-tmp'
    analysis, dimensions, rubric_note = agent.analyze(
        source,
        items,
        rubric_path(),
        workdir,
        name=display_name,
        dimensions=dimensions,
        rubric_note=rubric_note,
    )
    radar = agent.radar_png(analysis, dimensions)
    markdown = agent.markdown(analysis, dimensions, rubric_note, knowledge_points)
    payload = agent.payload(
        analysis, dimensions, rubric_note, bool(radar), knowledge_points
    )
    payload['rubric_signature'] = signature

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
