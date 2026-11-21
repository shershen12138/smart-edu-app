# -*- coding: utf-8 -*-
"""《Python教学Tag库》与题库打标文件的统一加载与归一。

数据源（仓库根目录）：
- ``Python教学Tag库_v1.0.md``：唯一考点词表。v2.0 起**大纲直接采用知识图谱的节点树**：

  ``# 图谱一级模块`` → ``## 图谱三级节点`` → ``### 图谱四级节点`` →
  ``- 节点首选 tag``（缩进子项 = 原有细化 tag）。

  每个节点行带 ``@<node_id>``（与 ``school/portal/data/python_graph.json`` 的
  ``node.id`` 相同），每个 tag 行末尾带 ``@Uxx-Mxx``（它原本所属的教学模块），
  因此「知识点 ↔ 图谱节点 ↔ 教学模块」三方都能 join。
- ``qbank-tags-v2.json``：分层题库 44 题的逐题打标（tag/role/weight）。

提供三类能力，供评分标准生成、雷达图考察重点与薄弱点选题共用：
- ``tag_names`` / ``tag_modules``：词表全文与按原教学模块分组的兼容视图；
- ``graph_nodes`` / ``tag_graph_index``：按知识图谱节点分组的视图与 tag → 节点索引；
- ``tag_module_codes``：tag → 原教学模块编号（能力画像的布鲁姆/思维维度仍按它映射）；
- ``normalize_tag``：任意知识点名归一到词表标准名（精确 → 别名 → 包含）；
- ``qbank_by_tag`` / ``questions_for_tag``：tag → 题库题目反查；
- ``top_tags``：按"考察重点"从知识点-题目映射中挑出最主要的几个 tag；
- ``qbank_by_thinking_ability`` / ``questions_for_ability``：计算思维四维 → 题库题目反查。

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

# 布鲁姆认知六维（键 → 中文名），与 school/portal/capability_rules.BLOOM_DIMENSIONS 一致；
# 题库按 ``bloom`` 字段打标，一道题可覆盖多层，首项为主要认知层次。
BLOOM_LABELS: dict[str, str] = {
    'remember': '记忆',
    'understand': '理解',
    'apply': '应用',
    'analyze': '分析',
    'evaluate': '评估',
    'create': '创造',
}
BLOOM_KEYS: tuple[str, ...] = tuple(BLOOM_LABELS)

# v2.0 结构：# 图谱一级 / ## 三级节点 / ### 四级节点 / - tag（缩进为子类 tag）
_SECTION_RE = re.compile(r'^#\s+(.+?)\s*$')
_NODE_RE = re.compile(r'^(#{2,3})\s+(.+?)\s*$')
_TAG_RE = re.compile(r'^(\s*)-\s+(.+?)\s*$')
_CODE_RE = re.compile(r'@(U\d+-M\d+)')
_NODE_ID_RE = re.compile(r'@([A-Za-z_][A-Za-z0-9_]*)')
_TRAIL_CODE_RE = re.compile(r'\s@(U\d+-M\d+)\s*$')
_MODULE_ROW_RE = re.compile(
    r'^\|\s*(U\d+)\s+(?P<unit>[^|]*?)\s*\|\s*(?P<code>U\d+-M\d+)\s*'
    r'\|\s*(?P<name>[^|]*?)\s*\|\s*(?P<node>[^|]*?)\s*\|$'
)


def _parse_tag(text: str) -> tuple[str, str, list[str]]:
    """拆出 tag 名、原模块编号与别名：``名称 @U05-M02 = 旧名1、旧名2``。"""
    body = text
    aliases: list[str] = []
    if ' = ' in body:
        body, _, rest = body.partition(' = ')
        aliases = [item.strip() for item in re.split(r'[、,]', rest) if item.strip()]
    code = ''
    match = _TRAIL_CODE_RE.search(body)
    if match:
        code = match.group(1)
        body = body[:match.start()]
    return body.strip(), code, aliases


@lru_cache(maxsize=1)
def _scan() -> dict:
    """解析词表，得到图谱节点、tag 归属与模块对照表。"""
    nodes: list[dict] = []
    tag_module: dict[str, str] = {}
    tag_node: dict[str, str] = {}
    aliases: dict[str, str] = {}
    module_tags: dict[str, list[str]] = {}
    module_table: dict[str, tuple[str, str, str]] = {}
    order: list[str] = []
    names: dict[str, str] = {}

    if not TAGLIB_MD.exists():
        logger.warning('Tag 库文件缺失 path=%s，知识点归一将退回原始名称', TAGLIB_MD)
        return {'nodes': nodes, 'tag_module': tag_module, 'tag_node': tag_node,
                'aliases': aliases, 'module_tags': module_tags,
                'module_table': module_table, 'order': order}
    try:
        lines = TAGLIB_MD.read_text(encoding='utf-8').splitlines()
    except OSError:
        logger.warning('Tag 库文件读取失败 path=%s', TAGLIB_MD, exc_info=True)
        return {'nodes': nodes, 'tag_module': tag_module, 'tag_node': tag_node,
                'aliases': aliases, 'module_tags': module_tags,
                'module_table': module_table, 'order': order}

    section = ''
    node: dict | None = None
    for line in lines:
        row = _MODULE_ROW_RE.match(line)
        if row:
            code = row.group('code')
            module_table[code] = (f"{row.group(1)} {row.group('unit')}".strip(),
                                  row.group('name'), row.group('node'))
            order.append(code)
            names[code] = row.group('name')
            continue
        match = _SECTION_RE.match(line)
        if match:
            section = match.group(1).strip()
            node = None
            continue
        match = _NODE_RE.match(line)
        if match:
            raw = match.group(2)
            codes = _CODE_RE.findall(raw)
            body = _CODE_RE.sub(' ', raw)
            ids = _NODE_ID_RE.findall(body)
            node_id = ids[0] if ids else ''
            name = _NODE_ID_RE.sub('', body)
            name = re.sub(r'\s+', ' ', name).strip()
            # 说明性章节（0./1./2./附录 B）没有 @ 标记，一律跳过
            if not section or not (codes or node_id):
                node = None
                continue
            node = {'id': node_id, 'name': name, 'section': section,
                    'level': len(match.group(1)), 'codes': codes, 'tags': []}
            nodes.append(node)
            continue
        match = _TAG_RE.match(line)
        if match and node is not None:
            name, code, alias = _parse_tag(match.group(2))
            if not name:
                continue
            node['tags'].append(name)
            if node['id']:
                tag_node.setdefault(name, node['id'])
            if code:
                tag_module.setdefault(name, code)
                bucket = module_tags.setdefault(code, [])
                if name not in bucket:
                    bucket.append(name)
            for item in alias:
                aliases.setdefault(item, name)

    if not order:
        order = sorted(module_tags)
    return {'nodes': nodes, 'tag_module': tag_module, 'tag_node': tag_node,
            'aliases': aliases, 'module_tags': module_tags,
            'module_table': module_table, 'order': order}


def reset_cache() -> None:
    """词表或题库打标文件被改动后清缓存（测试或运维脚本用）。"""
    _scan.cache_clear()
    tag_names.cache_clear()
    tag_aliases.cache_clear()
    tag_modules.cache_clear()
    tag_nodes.cache_clear()
    graph_nodes.cache_clear()
    qbank_questions.cache_clear()
    qbank_by_tag.cache_clear()
    qbank_by_bloom.cache_clear()


@lru_cache(maxsize=1)
def tag_names() -> frozenset[str]:
    """词表中全部 tag 的标准名集合（节点首选 tag + 细化 tag）。"""
    return frozenset(name for node in _scan()['nodes'] for name in node['tags'])


@lru_cache(maxsize=1)
def tag_aliases() -> dict[str, str]:
    """别名 → 标准名（近义合并后保留的旧写法）。"""
    return dict(_scan()['aliases'])


@lru_cache(maxsize=1)
def tag_modules() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """按**原教学模块**聚合的兼容视图：((单元, 'Uxx-Mxx 模块名', (tag...)), ...)。

    用于能力画像的模块级映射；大纲顺序与模块对照表一致。
    """
    scan = _scan()
    table = scan['module_table']
    rows = []
    for code in scan['order']:
        tags = scan['module_tags'].get(code)
        if not tags:
            continue
        unit, name, _node = table.get(code, ('', code, ''))
        rows.append((unit or code.split('-')[0], f'{code} {name}'.strip(), tuple(tags)))
    return tuple(rows)


def tag_module_codes() -> dict[str, str]:
    """tag 标准名 → 原教学模块编号（如 ``U05-M02``）。"""
    return dict(_scan()['tag_module'])


def tag_graph_index() -> dict[str, str]:
    """tag 标准名 → 知识图谱节点 id（未入图的 tag 不在其中）。"""
    return {name: node_id for name, node_id in _scan()['tag_node'].items() if node_id}


@lru_cache(maxsize=1)
def tag_nodes() -> tuple[dict, ...]:
    """按图示大纲组织的词表视图（图谱节点 + 未入图的模块节点）。

    每项含 ``id`` / ``name`` / ``section`` / ``level`` / ``tags`` / ``codes``；
    图谱节点的 ``tags[0]`` 恒为该节点的首选 tag（与节点同名），
    未入图模块节点的 ``id`` 为空串。
    """
    return tuple(
        {'id': node['id'], 'name': node['name'], 'section': node['section'],
         'level': node['level'], 'tags': tuple(node['tags']),
         'codes': tuple(node['codes'])}
        for node in _scan()['nodes']
    )


@lru_cache(maxsize=1)
def graph_nodes() -> tuple[dict, ...]:
    """只保留已与知识图谱节点对齐的条目（排除未入图模块）。"""
    return tuple(node for node in tag_nodes() if node['id'])


def module_node_map() -> dict[str, str]:
    """原教学模块编号 → 图谱节点名称（未入图为空串）。"""
    result = {}
    for code, (_unit, _name, node_name) in _scan()['module_table'].items():
        result[code] = '' if node_name == '未入图' else node_name
    return result


def is_known_tag(name: str) -> bool:
    """精确判断是否是词表标准名或别名（不做包含匹配，避免误命中）。"""
    text = str(name or '').strip()
    return bool(text) and (text in tag_names() or text in tag_aliases())


def normalize_tag(name: str) -> str | None:
    """把自由文本知识点名归一到词表标准名；无法归一时返回 None。

    匹配顺序：标准名精确 → 别名精确 → 包含匹配（取名字中完整包含的最长者）。
    """
    text = str(name or '').strip()
    if not text:
        return None
    names = tag_names()
    if text in names:
        return text
    aliases = tag_aliases()
    if text in aliases:
        return aliases[text]
    best: str | None = None
    best_len = 0
    for tag in names:
        if len(tag) >= 2 and tag in text and len(tag) > best_len:
            best, best_len = tag, len(tag)
    for alias, canonical in aliases.items():
        if len(alias) >= 2 and alias in text and len(alias) > best_len:
            best, best_len = canonical, len(alias)
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
    """tag 标准名 → 命中的题目列表（含 role/weight），供薄弱点组题反查。

    打标文件里的 tag 会先归一到词表标准名再建索引，因此题库写的是旧名
    或别名时依然能被 ``questions_for_tag('标准名')`` 命中；同一题重复命中只留一条。
    """
    index: dict[str, list[dict]] = {}
    seen: set[tuple[str, str]] = set()
    for question in qbank_questions():
        for entry in question.get('tags') or []:
            name = str(entry.get('tag', '')).strip()
            if not name:
                continue
            canonical = normalize_tag(name) or name
            marker = (canonical, question.get('qid', ''))
            if marker in seen:
                continue
            seen.add(marker)
            index.setdefault(canonical, []).append(
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


def bloom_label(key: str) -> str:
    """认知层次键 → 中文名；传入中文名或未知值时原样返回。"""
    text = str(key or '').strip()
    return BLOOM_LABELS.get(text, text)


def normalize_bloom(name: str) -> str | None:
    """把键或中文名归一到布鲁姆标准键（``analyze`` 等）；无法归一返回 None。"""
    text = str(name or '').strip()
    if not text:
        return None
    if text in BLOOM_LABELS:
        return text
    for key, label in BLOOM_LABELS.items():
        if text == label:
            return key
    return None


@lru_cache(maxsize=1)
def qbank_by_bloom() -> dict[str, tuple[dict, ...]]:
    """认知层次键 → 命中的题目列表；首项标注记为 primary，其余为 secondary。"""
    index: dict[str, list[dict]] = {key: [] for key in BLOOM_KEYS}
    for question in qbank_questions():
        basis = str(question.get('bloom_basis', '') or '')
        raw = [str(key).strip() for key in (question.get('bloom') or [])]
        for position, key in enumerate(raw):
            if key not in BLOOM_LABELS:
                logger.warning('题目 %s 的布鲁姆标签不在六维内：%s', question.get('qid'), key)
                continue
            index[key].append(
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


def bloom_for_tag(tag: str) -> tuple[str, ...]:
    """题库中**主要以**该 tag 为考点的题目，所标注的认知层次并集（按出现顺序）。

    训练题大多由某个弱项知识点生成，题库标签是它最近似的能力画像，
    新生成的题若模型没给 bloom，就继承这里的结果。
    """
    target = normalize_tag(tag) or str(tag or '').strip()
    if not target:
        return ()
    keys: list[str] = []
    for question in qbank_questions():
        primary = [
            normalize_tag(str(entry.get('tag', '')).strip())
            or str(entry.get('tag', '')).strip()
            for entry in question.get('tags') or []
            if entry.get('role') == 'primary'
        ]
        if target not in primary:
            continue
        for key in question.get('bloom') or []:
            key = str(key).strip()
            if key in BLOOM_LABELS and key not in keys:
                keys.append(key)
    return tuple(keys)


def questions_for_bloom(name: str, primary_only: bool = False) -> tuple[dict, ...]:
    """返回某个认知层次（键或中文名）命中的题目，主要层次（首项）在前。"""
    key = normalize_bloom(name)
    if not key:
        return ()
    items = qbank_by_bloom().get(key, ())
    if primary_only:
        items = tuple(item for item in items if item.get('role') == 'primary')
    return tuple(sorted(items, key=lambda item: item.get('role') != 'primary'))


def questions_for_blooms(
    names: list[str] | tuple[str, ...] | set[str], require_all: bool = False
) -> tuple[dict, ...]:
    """按多个认知层次组卷：默认取并集（主要层次优先），``require_all`` 取交集。"""
    keys = [key for key in (normalize_bloom(name) for name in names) if key]
    if not keys:
        return ()
    per_key = [questions_for_bloom(key) for key in keys]
    if require_all:
        common = set.intersection(*(set(item['qid'] for item in items) for items in per_key))
        merged = [item for item in per_key[0] if item['qid'] in common]
    else:
        seen: set[str] = set()
        merged = []
        for key in keys:
            for item in questions_for_bloom(key):
                if item['qid'] not in seen:
                    seen.add(item['qid'])
                    merged.append(item)
    return tuple(sorted(merged, key=lambda item: item.get('role') != 'primary'))


def bloom_levels_for_question(qid: str) -> tuple[tuple[str, str, str], ...]:
    """某题的认知层次条目 ((键, 中文名, 判定依据), ...)，首项为主要层次。"""
    target = str(qid or '').strip()
    for question in qbank_questions():
        if question.get('qid') == target:
            basis = str(question.get('bloom_basis', '') or '')
            return tuple(
                (key, BLOOM_LABELS[key], basis)
                for key in (str(item).strip() for item in question.get('bloom') or [])
                if key in BLOOM_LABELS
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
