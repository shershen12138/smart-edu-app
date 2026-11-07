"""把学生提交的源码接入代码质量评测智能体，生成并缓存个性化报告。

边界：
- 只处理机器批阅作业的单文件提交（教师端上传的题目包决定函数清单）；
- 分析与评分在本机完成，不执行学生代码；
- 报告与雷达图写入私有存储，数据库只保存元数据与结构化明细。
"""

from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

from school import storage
from school.course_models import PrivateFileCleanup, QualityReport

from tools.code_quality_agent import models as agent_models
from tools.code_quality_agent import rubric as agent_rubric
from tools.code_quality_agent import service as agent

from . import rubric_agent

# 雷达图几何版本：坐标算法调整后，旧报告自动重算，避免页面回退到静态图片。
RADAR_VERSION = 'radar-v1'

def ensure_rubric(coursework):
    """确保该作业有一份自己的评分标准，返回它（可能为 None）。

    评分标准按任务存库，学生报告不再共用仓库里的通用量表：
    - 已有结构化维度时直接使用（可能是教师用大模型生成的）；
    - 没有时按该作业的题目自动生成一份规则版并存库，每个任务的
      知识点、量表与六主能力都只属于自己。
    这里只做规则兜底，不调用大模型，避免学生打开报告时等待网络请求。
    """
    stored = getattr(coursework, 'rubric', None)
    if stored:
        # 结构化维度、知识点或可解析的量表 Markdown，任一存在就算已有评分标准，
        # 不能因为维度暂时为空就覆盖教师已生成的内容。
        parsed = agent_rubric.dimensions_from_text(
            stored.markdown or '', '作业评分标准'
        )
        if stored.dimensions or stored.knowledge_points or parsed:
            return stored
    try:
        return rubric_agent.generate_for(coursework, offline=True, force=True)
    except Exception:
        return stored


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


def dimensions_for(coursework, stored=None) -> tuple[list[agent_models.Dimension], str]:
    """取该任务的评分标准：结构化维度优先，其次解析数据库中的量表 Markdown。

    两者都不可用时用智能体的内置 6 维量表，不再读取仓库里的通用量表文件。
    """
    if stored is None:
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
    dimensions = rubric_agent.default_dimensions()
    return dimensions, f'使用内置 6 维量表（{len(dimensions)} 维，该任务尚未生成评分标准）'


def knowledge_points_for(coursework, items, stored=None) -> dict[str, tuple[str, ...]]:
    """评分标准（CourseworkRubric）里的“作业考察的知识点”，按函数名分组。

    报告逐题明细的知识点列直接使用这份清单，而不是评测器按题库规格推断的标签；
    作业还没有评分标准时返回空，由评测器回退到题库规格。
    `tasks` 为空的知识点视为覆盖该作业的全部题目。
    """
    if stored is None:
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


def abilities_for(coursework, stored=None) -> list[dict]:
    """评分标准里的 6 个主能力，作为雷达图的 6 根轴。

    新数据由题目分析智能体与大模型一起产出并存库；旧评分标准没有该字段时，
    用规则把知识点归类补算，不调用模型，保证旧作业也能出图。
    """
    if stored is None:
        stored = getattr(coursework, 'rubric', None)
    if not stored:
        return []
    abilities = [
        item
        for item in (stored.abilities or [])
        if isinstance(item, dict) and item.get('label') and item.get('dimension')
    ]
    if len(abilities) == 6:
        return abilities
    return rubric_agent.rule_abilities(stored.knowledge_points or [])


def display_dimensions(dimensions, abilities) -> list[agent_models.Dimension]:
    """把评分维度换成主能力名称，分数仍取所绑定维度的分数。

    维度数量与主能力对不上时（例如只用内置 5 维量表）保持原样，避免少轴或错配。
    """
    if len(abilities) != 6:
        return list(dimensions)
    by_key = {dimension.key: dimension for dimension in dimensions}
    shown: list[agent_models.Dimension] = []
    for ability in abilities:
        base = by_key.get(str(ability.get('dimension', '')))
        if base is None:
            return list(dimensions)
        shown.append(agent_models.Dimension(base.key, str(ability['label']), base.weight))
    if len(shown) != len(dimensions):
        return list(dimensions)
    return shown


def radar_geometry(scores, width: int = 480, height: int = 360, radius: float = 104) -> dict:
    """把主能力得分换算成 SVG 极坐标，供前端绘制可交互的雷达图。

    Django 模板做不了三角函数，这里一次算好网格、轴线、数据多边形与标签位置，
    页面只负责画；悬停提示由 portal.js 根据 data-label / data-score 填充。
    """
    center_x = width / 2
    center_y = height / 2
    count = len(scores) or 1
    axes = []
    for index, item in enumerate(scores):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        score = min(100.0, max(0.0, float(item.get('score') or 0)))
        distance = radius * score / 100
        cos_v, sin_v = math.cos(angle), math.sin(angle)
        axes.append(
            {
                'label': str(item.get('label', '')),
                'score': round(score, 1),
                'weight': item.get('weight', 0),
                'x': round(center_x + distance * cos_v, 1),
                'y': round(center_y + distance * sin_v, 1),
                'label_x': round(center_x + (radius + 24) * cos_v, 1),
                'label_y': round(center_y + (radius + 24) * sin_v, 1),
                'value_y': round(center_y + (radius + 24) * sin_v + 15, 1),
                'anchor': 'start' if cos_v > 0.3 else ('end' if cos_v < -0.3 else 'middle'),
            }
        )
    rings = []
    for ratio in (0.25, 0.5, 0.75, 1.0):
        points = []
        for index in range(count):
            angle = -math.pi / 2 + 2 * math.pi * index / count
            points.append(
                f"{center_x + radius * ratio * math.cos(angle):.1f},"
                f"{center_y + radius * ratio * math.sin(angle):.1f}"
            )
        rings.append(' '.join(points))
    return {
        'width': width,
        'height': height,
        'center_x': round(center_x, 1),
        'center_y': round(center_y, 1),
        'radius': radius,
        'rings': rings,
        'axes': axes,
        'polygon': ' '.join(f"{axis['x']},{axis['y']}" for axis in axes),
    }


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


def _abilities_signature(abilities: list[dict]) -> str:
    """主能力的指纹：重新生成评分标准后，旧报告要自动重算。"""
    return '|'.join(
        f"{ability.get('dimension', '')}:{ability.get('label', '')}"
        for ability in abilities
    )


def generate(entry, force: bool = False) -> QualityReport:
    if not supported(entry):
        raise ValidationError('非机器批阅作业不生成代码质量报告。')

    source = storage.read_private(entry.source_path)
    digest = entry.source_hash or storage.code_digest(source)
    items = [
        (item.function_name, item.title) for item in entry.coursework.items.all()
    ]
    # 每个任务使用自己的评分标准：缺失时按该任务的题目自动生成并存库。
    stored = ensure_rubric(entry.coursework)
    dimensions, rubric_note = dimensions_for(entry.coursework, stored)
    abilities = abilities_for(entry.coursework, stored)
    knowledge_points = knowledge_points_for(entry.coursework, items, stored)
    # 量表维度、题库考点、知识点或主能力变了都要重算，不能只比源码摘要。
    signature = (
        '|'.join(
            f'{dimension.key}:{dimension.label}:{dimension.weight}'
            for dimension in dimensions
        )
        + '#'
        + _specs_signature(items)
        + '#'
        + _knowledge_signature(knowledge_points)
        + '#'
        + _abilities_signature(abilities)
        + '#'
        + RADAR_VERSION
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
        workdir,
        name=display_name,
        dimensions=dimensions,
        rubric_note=rubric_note,
    )
    # 雷达图与得分表换成 6 个主能力，分数仍是所绑定评分维度的分数。
    shown = display_dimensions(dimensions, abilities)
    uses_abilities = [item.label for item in shown] != [item.label for item in dimensions]
    radar = agent.radar_png(analysis, shown)
    markdown = agent.markdown(analysis, shown, rubric_note, knowledge_points)
    payload = agent.payload(analysis, shown, rubric_note, bool(radar), knowledge_points)
    payload['axis_label'] = '主能力' if uses_abilities else '评分维度'
    payload['radar'] = radar_geometry(payload['scores'])
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
