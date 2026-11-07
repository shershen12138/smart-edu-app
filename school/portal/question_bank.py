"""分层训练题库（Python题库.md）解析与按弱项关键词选题。

Python题库.md 是团队维护的结构化题库文档（44 题、12 知识域、每题 10 组
实测用例），字段顺序固定，便于机器解析。本模块把它当作"现有题库"的
数据源之一：规则兜底出题时按弱项关键词反查题目标签，挑选现成题，
不凭空编题；解析失败或文件缺失时返回空题库，不阻塞其他出题路径。
"""

from __future__ import annotations

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
_CASE_ROW_RE = re.compile(r'^\|\s*(\d+)\s*\|(.+)\|(.+)\|\s*$')

# 星级 → 难度（与 PracticeProblem.DIFFICULTIES 对齐）与排序权重
_DIFFICULTY_BY_STARS = {'★☆☆': ('基础', 0), '★★☆': ('进阶', 1), '★★★': ('进阶', 2)}


def bank_path() -> Path:
    return Path(settings.BASE_DIR) / BANK_FILENAME


def _clean_cell(raw: str) -> str:
    """用例单元格 → 判题器实际文本：反引号去除，<br> 还原为换行。"""
    text = raw.strip().strip('`').strip().replace('<br>', '\n').replace('`', '')
    return '\n'.join(part.strip() for part in text.split('\n'))


def _parse_case_table(lines: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in lines:
        match = _CASE_ROW_RE.match(line)
        if not match:
            continue
        stdin = _clean_cell(match.group(2))
        expected = _clean_cell(match.group(3))
        if stdin and expected:
            cases.append({'input': stdin, 'output': expected})
    # 题库文档约定第一组为示例；全部用例均经过答案实测。
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

    code_block = re.search(
        r'```python\s*\n(.*?)```', '\n'.join(sections['4']), re.DOTALL
    )
    reference_code = code_block.group(1).strip() if code_block else ''
    cases = _parse_case_table(sections['4'])
    if not cases:
        return None

    return {
        'code': code,
        'title': f'{code} {title.strip()}',
        'statement': statement,
        'tags': tags,
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
