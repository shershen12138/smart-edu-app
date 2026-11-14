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
- ``top_tags``：按"考察重点"从知识点-题目映射中挑出最主要的几个 tag；
- ``qbank_by_thinking_ability`` / ``questions_for_ability``：计算思维四维
  （分解问题、模式识别、抽象、算法设计）→ 题库题目反查，供按能力组卷与
  弱项训练使用；能力标签与知识点标签正交（考什么内容 vs 考察什么思维）。

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

# 计算思维四维（键 → 中文名），与知识点标签正交；顺序即默认主次声明顺序
THINKING_ABILITY_LABELS: dict[str, str] = {
    'decomposition': '分解问题',
    'pattern': '模式识别',
    'abstraction': '抽象',
    'algorithm': '算法设计',
}

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


@lru_cache(maxsize=1)
def thinking_abilities() -> tuple[str, ...]:
    """题库声明的考察能力键（按声明顺序）；文件缺失时退回四维默认顺序。"""
    keys: list[str] = []
    if QBANK_TAGS.exists():
        try:
            data = json.loads(QBANK_TAGS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            logger.warning('题库打标文件解析失败 path=%s', QBANK_TAGS, exc_info=True)
            data = {}
        meta = data.get('meta') if isinstance(data, dict) else None
        declared = (meta or {}).get('thinking_abilities') if isinstance(meta, dict) else None
        for key in declared or []:
            if key in THINKING_ABILITY_LABELS and key not in keys:
                keys.append(key)
    return tuple(keys) or tuple(THINKING_ABILITY_LABELS)


def thinking_ability_label(key: str) -> str:
    """能力键 → 中文名；传入中文名或未知值时原样返回。"""
    text = str(key or '').strip()
    return THINKING_ABILITY_LABELS.get(text, text)


def normalize_thinking_ability(name: str) -> str | None:
    """把能力键或中文名归一到标准键（``decomposition`` 等）；无法归一返回 None。"""
    text = str(name or '').strip()
    if not text:
        return None
    if text in THINKING_ABILITY_LABELS:
        return text
    for key, label in THINKING_ABILITY_LABELS.items():
        if text == label:
            return key
    return None


def _ability_basis(basis: str, label: str) -> str:
    """从整串判定依据（如「抽象：…；算法设计：…」）中取出某项的说明。

    未按「标签：说明」分段书写时，整串作为该题唯一能力的依据返回。
    """
    text = str(basis or '').strip()
    if not text:
        return ''
    if '：' not in text:
        return text
    for part in re.split(r'[；;]', text):
        head, sep, rest = part.partition('：')
        if sep and head.strip() == label:
            return rest.strip()
    return ''


def _question_ability_entries(question: dict) -> tuple[tuple[str, str], ...]:
    """题目的能力条目 ((键, 判定依据), ...)，首项为主能力。"""
    entries: list[tuple[str, str]] = []
    basis = str(question.get('thinking_basis', '') or '')
    for key in question.get('thinking_abilities') or []:
        key = str(key).strip()
        if key not in THINKING_ABILITY_LABELS:
            continue
        entries.append((key, _ability_basis(basis, THINKING_ABILITY_LABELS[key])))
    return tuple(entries)


@lru_cache(maxsize=1)
def qbank_by_thinking_ability() -> dict[str, tuple[dict, ...]]:
    """能力键 → 命中的题目列表；首项能力记为 primary，其余为 secondary。"""
    index: dict[str, list[dict]] = {}
    for question in qbank_questions():
        for position, (key, basis) in enumerate(_question_ability_entries(question)):
            index.setdefault(key, []).append(
                {
                    'qid': question.get('qid', ''),
                    'func': question.get('func', ''),
                    'title': question.get('title', ''),
                    'star': question.get('star', ''),
                    'role': 'primary' if position == 0 else 'secondary',
                    'basis': basis,
                }
            )
    return {key: tuple(items) for key, items in index.items()}


def questions_for_ability(name: str, primary_only: bool = False) -> tuple[dict, ...]:
    """返回某个考察能力（键或中文名）命中的题目，主能力（首项）在前。"""
    key = normalize_thinking_ability(name)
    if not key:
        return ()
    items = qbank_by_thinking_ability().get(key, ())
    if primary_only:
        items = tuple(item for item in items if item.get('role') == 'primary')
    return tuple(sorted(items, key=lambda item: item.get('role') != 'primary'))


def questions_for_abilities(
    names: list[str] | tuple[str, ...] | set[str], require_all: bool = False
) -> tuple[dict, ...]:
    """按多个能力组卷：默认取并集（主能力优先），``require_all`` 时取同时具备的题。"""
    keys = [key for key in (normalize_thinking_ability(name) for name in names) if key]
    if not keys:
        return ()
    per_key = [questions_for_ability(key) for key in keys]
    if require_all:
        common = set.intersection(*(set(item['qid'] for item in items) for items in per_key))
        merged = [item for item in per_key[0] if item['qid'] in common]
    else:
        seen: set[str] = set()
        merged = []
        for key in keys:
            for item in questions_for_ability(key):
                if item['qid'] not in seen:
                    seen.add(item['qid'])
                    merged.append(item)
    return tuple(sorted(merged, key=lambda item: item.get('role') != 'primary'))


def thinking_abilities_for_question(qid: str) -> tuple[tuple[str, str, str], ...]:
    """某题的能力条目 ((键, 中文名, 判定依据), ...)，首项为主能力；未知题号返回空。"""
    target = str(qid or '').strip()
    for question in qbank_questions():
        if question.get('qid') == target:
            return tuple(
                (key, THINKING_ABILITY_LABELS[key], basis)
                for key, basis in _question_ability_entries(question)
            )
    return ()


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
