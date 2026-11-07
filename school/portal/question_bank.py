"""分层训练题库（Python题库.md）解析与按弱项关键词选题。

Python题库.md 是团队维护的结构化题库文档，v2 起改为"函数式批阅包"：
每题给出函数框架（学生起始代码）、标准答案与 10 组字面量用例，
判题只认函数返回值（类型 + 值严格比对，浮点容差 1e-6）。

本模块把它当作"现有题库"的数据源之一：
- 解析出题目、函数签名、框架代码、参考答案与用例；
- 用例的期望返回值统一转成判题器的打包 JSON（与 school.portal.grading
  的 PACKER 约定一致），学生返回值经同一打包流程后逐值比对；
- 按弱项关键词反查考点标签选题；文件缺失或解析异常时返回空题库。
"""

from __future__ import annotations

import ast
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

from .knowledge_profile import weak_keywords

BANK_FILENAME = 'Python题库.md'

_HEADER_RE = re.compile(
    r'^###\s*1、题目标题：(Q\d+-\d+)\s*(.+?)（(★[☆★]*)｜(\d+)\s*分）\s*$'
)
_SECTION_RE = re.compile(r'^\*\*([234])、')
_SUBSECTION_RE = re.compile(r'^\*\*4\.\d')
_CASE_ROW_RE = re.compile(r'^\|\s*(\d+)\s*\|(.+)\|(.+)\|\s*$')
_DEF_RE = re.compile(r'^def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:', re.MULTILINE)

# 星级 → 难度（与 PracticeProblem.DIFFICULTIES 对齐）与排序权重
_DIFFICULTY_BY_STARS = {'★☆☆': ('基础', 0), '★★☆': ('进阶', 1), '★★★': ('进阶', 2)}


def bank_path() -> Path:
    return Path(settings.BASE_DIR) / BANK_FILENAME


def _clean_cell(raw: str) -> str:
    """用例单元格 → 字面量文本：反引号去除、行内换行还原。"""
    return raw.strip().strip('`').strip().replace('<br>', '\n').replace('`', '')


def _code_block(text: str) -> str:
    match = re.search(r'```python\s*\n(.*?)```', text, re.DOTALL)
    return match.group(1).strip() if match else ''


def _parse_signature(framework: str) -> tuple[str, int]:
    """从函数框架解析函数名与位置参数个数（带默认值的参数也计入）。"""
    match = _DEF_RE.search(framework)
    if not match:
        return '', 1
    name, params = match.group(1), match.group(2).strip()
    if not params:
        return name, 0
    argc = 0
    for part in params.split(','):
        part = part.strip()
        if not part or part.startswith('*'):
            continue
        argc += 1
    return name, max(argc, 1)


def pack_value(value: Any) -> dict[str, Any]:
    """把 Python 返回值打包成判题器的类型化 JSON（与 grading.PACKER_SOURCE 一致）。"""
    kind = type(value)
    if value is None:
        return {'type': 'none'}
    if kind is bool:
        return {'type': 'bool', 'value': value}
    if kind is int:
        return {'type': 'int', 'value': value}
    if kind is float:
        return {'type': 'float', 'value': value}
    if kind is complex:
        return {'type': 'complex', 'real': value.real, 'imag': value.imag}
    if kind is str:
        return {'type': 'str', 'value': value}
    if kind is list:
        return {'type': 'list', 'items': [pack_value(item) for item in value]}
    if kind is tuple:
        return {'type': 'tuple', 'items': [pack_value(item) for item in value]}
    if kind is set:
        items = [pack_value(item) for item in value]
        return {'type': 'set', 'items': sorted(items, key=lambda x: json.dumps(x, sort_keys=True))}
    if kind is dict:
        items = [[pack_value(key), pack_value(item)] for key, item in value.items()]
        items.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True))
        return {'type': 'dict', 'items': items}
    raise TypeError('unsupported return type: ' + kind.__name__)


def _expected_packed(repr_text: str) -> str:
    """文档里的期望返回值是 repr 字面量，转成判题器的打包 JSON。"""
    value = ast.literal_eval(repr_text)
    return json.dumps(pack_value(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _parse_cases(lines: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in lines:
        match = _CASE_ROW_RE.match(line)
        if not match:
            continue
        args_text = _clean_cell(match.group(2))
        try:
            expected = _expected_packed(_clean_cell(match.group(3)))
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        if args_text and expected:
            cases.append({'input': args_text, 'output': expected})
    for index, case in enumerate(cases):
        case['is_sample'] = index == 0
    return cases


def _parse_question(lines: list[str]) -> dict[str, Any] | None:
    header = _HEADER_RE.match(lines[0].strip())
    if not header:
        return None
    code, title, stars, points = header.groups()
    difficulty, rank = _DIFFICULTY_BY_STARS.get(stars, ('进阶', 1))

    sections: dict[str, list[str]] = {'2': [], '3': [], '4': []}
    current = '2'
    for line in lines[1:]:
        marker = _SECTION_RE.match(line)
        if marker:
            current = marker.group(1)
            continue
        sections[current].append(line)

    tags = re.findall(r'`([^`\s]+)`', '\n'.join(sections['3']))
    statement = '\n'.join(sections['2']).strip()
    if not statement or not tags:
        return None

    # 4.x 小节：4.1 函数框架、4.2 标准答案、4.3 测试用例
    framework_lines: list[str] = []
    answer_lines: list[str] = []
    case_lines: list[str] = []
    target = framework_lines
    for line in sections['4']:
        if _SUBSECTION_RE.match(line):
            if line.startswith('**4.2'):
                target = answer_lines
            elif line.startswith('**4.3'):
                target = case_lines
            continue
        target.append(line)
    framework = _code_block('\n'.join(framework_lines))
    reference_code = _code_block('\n'.join(answer_lines))
    function_name, function_argc = _parse_signature(framework)
    cases = _parse_cases(case_lines)
    if not framework or not reference_code or not cases or not function_name:
        return None

    return {
        'code': code,
        'title': f'{code} {title.strip()}',
        'statement': statement,
        'tags': tags,
        'function_name': function_name,
        'function_argc': function_argc,
        'template_code': framework,
        'reference_code': reference_code,
        'explanation': '',
        'difficulty': difficulty,
        'difficulty_rank': rank,
        'points': int(points),
        'cases': cases,
    }


@lru_cache(maxsize=1)
def load_bank() -> tuple[dict[str, Any], ...]:
    """解析题库文档；文件缺失或解析异常时返回空元组，不抛错。"""
    path = bank_path()
    if not path.exists():
        return ()
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return ()
    questions: list[dict[str, Any]] = []
    starts = [i for i, line in enumerate(lines) if _HEADER_RE.match(line.strip())]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        question = _parse_question(lines[start:end])
        if question:
            questions.append(question)
    return tuple(questions)


def _match_score(question: dict[str, Any], tokens: list[str]) -> int:
    """弱项关键词与题目标签的相关度得分（标签如 `列表/切片`）。

    每个关键词取其在标签各分段（含去掉 `/` 的整体）中的最大匹配长度，
    命中越具体得分越高；双向包含（弱项名 ⊆ 标签 或 标签 ⊆ 弱项名）都算。
    """
    total = 0
    for token in tokens:
        best = 0
        for tag in question['tags']:
            segments = [part.strip().lower() for part in tag.split('/') if part.strip()]
            segments.append(tag.replace('/', '').lower())
            for segment in segments:
                if len(segment) < 2:
                    continue
                if token in segment:
                    best = max(best, len(token))
                elif segment in token:
                    best = max(best, len(segment))
        if best > 0:
            total += best
    return total


def find_questions(
    name: str, limit: int = 2, exclude: set[str] | None = None
) -> list[dict[str, Any]]:
    """按弱项名称的关键词反查题库，返回相关度最高、难度递增的前 limit 题。"""
    tokens = weak_keywords(name)
    if not tokens:
        return []
    excluded = exclude or set()
    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    for question in load_bank():
        if question['code'] in excluded:
            continue
        score = _match_score(question, tokens)
        if score <= 0:
            continue
        scored.append((score, question['difficulty_rank'], question['code'], question))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [question for _score, _rank, _code, question in scored[:limit]]


def has_matches(weak: list[dict]) -> bool:
    """任一弱项能在题库中按关键词找到相关题目即为 True。"""
    return any(find_questions(item['name'], limit=1) for item in weak)


def bank_size() -> int:
    return len(load_bank())
