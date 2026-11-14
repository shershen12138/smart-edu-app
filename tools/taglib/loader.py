# -*- coding: utf-8 -*-
"""《Python教学Tag库》与题库打标文件的统一加载与归一。

数据源（仓库根目录）：
- ``Python教学Tag库_v1.0.md``：唯一考点词表，结构为
  ``# Uxx 单元名`` → ``## Uxx-Mxx 模块名`` → ``- 标签``；
- ``qbank-tags-v2.json``：分层题库 44 题的逐题打标（tag/role/weight）。

提供三类能力，供评分标准生成、雷达图考察重点与薄弱点选题共用：
- ``tag_names`` / ``tag_modules``：词表全文与按模块分组视图；
- ``normalize_tag``：任意知识点名归一到词表标准名（精确 → 包含）；
- ``qbank_by_tag`` / ``questions_for_tag``：tag → 题库题目反查；
- ``top_tags``：按"考察重点"从知识点-题目映射中挑出最主要的几个 tag。

重要程度不等于出现频次：既看覆盖题数，也看题目分值——
``importance(tag) = Σ(覆盖题目的 1 + 分值/10)``，覆盖越多、题目分值越重，
该 tag 越是这份作业的考察重点。
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data'
TAGLIB_MD = DATA_DIR / 'Python教学Tag库_v1.0.md'
QBANK_TAGS = DATA_DIR / 'qbank-tags-v2.json'

_UNIT_RE = re.compile(r'^#\s+(U\d+.*)$')
_MODULE_RE = re.compile(r'^##\s+(U\d+-M\d+)\s+(.*)$')
_TAG_RE = re.compile(r'^-\s+(.+?)\s*$')


@lru_cache(maxsize=1)
def tag_modules() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """解析词表，返回 ((单元标题, 模块标题, (tag...)), ...)；文件缺失返回空。"""
    if not TAGLIB_MD.exists():
        logger.warning('Tag 库文件缺失 path=%s，知识点归一将退回原始名称', TAGLIB_MD)
        return ()
    modules: list[tuple[str, str, tuple[str, ...]]] = []
    unit = ''
    module = ''
    tags: list[str] = []
    try:
        lines = TAGLIB_MD.read_text(encoding='utf-8').splitlines()
    except OSError:
        logger.warning('Tag 库文件读取失败 path=%s', TAGLIB_MD, exc_info=True)
        return ()
    for line in lines:
        unit_match = _UNIT_RE.match(line)
        if unit_match:
            unit = unit_match.group(1).strip()
            continue
        module_match = _MODULE_RE.match(line)
        if module_match:
            if module and tags:
                modules.append((unit, module, tuple(tags)))
            module = f'{module_match.group(1)} {module_match.group(2).strip()}'.strip()
            tags = []
            continue
        tag_match = _TAG_RE.match(line)
        if tag_match and module:
            name = tag_match.group(1).strip()
            if name and '|' not in name and '`' not in name:
                tags.append(name)
    if module and tags:
        modules.append((unit, module, tuple(tags)))
    return tuple(modules)


@lru_cache(maxsize=1)
def tag_names() -> frozenset[str]:
    """词表中全部三级 tag 的标准名集合。"""
    return frozenset(tag for _, _, tags in tag_modules() for tag in tags)


def normalize_tag(name: str) -> str | None:
    """把自由文本知识点名归一到词表标准名；无法归一时返回 None。

    匹配顺序：去除空白后精确匹配 → 包含匹配（名字里完整包含某个 tag，
    取最长者，如“列表切片与反转”归一到“列表切片”）。
    """
    text = str(name or '').strip()
    if not text:
        return None
    names = tag_names()
    if text in names:
        return text
    best = None
    for tag in names:
        if len(tag) >= 2 and tag in text:
            if best is None or len(tag) > len(best):
                best = tag
    return best


@lru_cache(maxsize=1)
def qbank_questions() -> tuple[dict, ...]:
    """题库打标文件中的题目列表；文件缺失或解析失败返回空。"""
    if not QBANK_TAGS.exists():
        logger.warning('题库打标文件缺失 path=%s，Tag 选题将退回关键词匹配', QBANK_TAGS)
        return ()
    try:
        data = json.loads(QBANK_TAGS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        logger.warning('题库打标文件解析失败 path=%s', QBANK_TAGS, exc_info=True)
        return ()
    questions = data.get('questions') or []
    return tuple(item for item in questions if isinstance(item, dict))


@lru_cache(maxsize=1)
def qbank_by_tag() -> dict[str, tuple[dict, ...]]:
    """tag 标准名 → 命中的题目列表（含 role/weight），供薄弱点组题反查。"""
    index: dict[str, list[dict]] = {}
    for question in qbank_questions():
        for entry in question.get('tags') or []:
            name = str(entry.get('tag', '')).strip()
            if not name:
                continue
            index.setdefault(name, []).append(
                {
                    'qid': question.get('qid', ''),
                    'func': question.get('func', ''),
                    'title': question.get('title', ''),
                    'star': question.get('star', ''),
                    'role': entry.get('role', ''),
                    'weight': float(entry.get('weight', 0) or 0),
                }
            )
    return {tag: tuple(items) for tag, items in index.items()}


def questions_for_tag(tag: str) -> tuple[dict, ...]:
    """返回某个 tag 命中的题库题目，主要考点（primary）在前。"""
    items = qbank_by_tag().get(str(tag or '').strip(), ())
    return tuple(sorted(items, key=lambda item: item.get('role') != 'primary'))


def top_tags(
    tag_tasks: dict[str, list[str]],
    task_weights: dict[str, float] | None = None,
    limit: int = 6,
) -> list[tuple[str, float]]:
    """按考察重点挑出最主要的 limit 个 tag。

    tag_tasks: tag → 覆盖的题目（函数名）列表；task_weights: 函数名 → 分值。
    重要度 = Σ(1 + 分值/10)，兼顾覆盖广度与题目分量；返回
    [(tag, 归一化权重), ...]，权重合计为 1，供雷达图与考察重点表使用。
    """
    weights = task_weights or {}
    scored: list[tuple[str, float]] = []
    for tag, tasks in tag_tasks.items():
        if not tag or not tasks:
            continue
        importance = sum(
            1.0 + float(weights.get(task, 10.0)) / 10.0 for task in tasks
        )
        scored.append((tag, importance))
    scored.sort(key=lambda item: (-item[1], item[0]))
    top = scored[:limit]
    total = sum(value for _, value in top) or 1.0
    return [(tag, round(value / total, 4)) for tag, value in top]
