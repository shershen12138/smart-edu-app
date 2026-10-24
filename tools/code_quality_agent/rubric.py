"""评分量表与打分。

量表优先读取 `data/03评分量表.md`：支持 Markdown 表格（维度 | 权重，可附带
5～1 分描述）和 `- 维度：30%` 两种写法，表格只识别“量表”小节内的，避免把
知识点表当成评分维度。文件为空或无法识别时，退回内置量表，并在报告开头
明确标注，避免把内置规则说成教师给定的量表。
"""

from __future__ import annotations

import re
from pathlib import Path

from . import models

DEFAULT_RUBRIC: tuple[models.Dimension, ...] = (
    models.Dimension(models.KNOWLEDGE, models.DIMENSION_LABELS[models.KNOWLEDGE], 0.30),
    models.Dimension(models.SYNTAX, models.DIMENSION_LABELS[models.SYNTAX], 0.20),
    models.Dimension(models.BOUNDARY, models.DIMENSION_LABELS[models.BOUNDARY], 0.15),
    models.Dimension(models.LOGIC, models.DIMENSION_LABELS[models.LOGIC], 0.25),
    models.Dimension(models.STYLE, models.DIMENSION_LABELS[models.STYLE], 0.10),
)

# 匹配顺序即优先级：例如“语法与规范”必须先命中语法，不能被“规范”抢走。
KEYWORDS = {
    models.KNOWLEDGE: ("知识点", "知识", "掌握"),
    models.SYNTAX: ("语法", "静态", "编译"),
    models.BOUNDARY: ("边界", "健壮", "鲁棒", "异常"),
    models.LOGIC: ("逻辑", "题意", "正确性", "一致"),
    models.STRUCTURE: ("结构", "拆分", "组织"),
    models.READABILITY: ("可读", "易读", "阅读", "命名", "风格"),
    models.STYLE: ("规范", "样式"),
}

_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*%?")
_BULLET = re.compile(r"^\s*[-*]\s*([^:：]+)[:：]\s*(.+)$")
_SEPARATOR = re.compile(r"^[-: ]+$")


def _match_dimension(text: str) -> str | None:
    for key, words in KEYWORDS.items():
        if any(word in text for word in words):
            return key
    return None


def _parse_weight(text: str) -> float | None:
    match = _NUMBER.search(text)
    if not match:
        return None
    value = float(match.group(1))
    if value > 1:
        value /= 100
    return value if 0 < value <= 1 else None


def _candidates(text: str) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) < 2:
                continue
            key = _match_dimension(cells[0])
            weight = _parse_weight(cells[1])
            if key and weight is not None:
                found.append((key, weight))
            continue
        bullet = _BULLET.match(stripped)
        if bullet:
            key = _match_dimension(bullet.group(1))
            weight = _parse_weight(bullet.group(2))
            if key and weight is not None:
                found.append((key, weight))
    return found


_HEADING = re.compile(r"^(#{1,6})\s*(.*)$")


def _is_fence(line: str) -> bool:
    return line.startswith("```") or line.startswith("~~~")


def _section_lines(text: str, keyword: str) -> list[str]:
    """取包含 keyword 的标题下的正文，避免把“知识点表”误当成量表。

    代码围栏内的 `#` 是注释或示例，不能当成标题，否则会提前截断正文。
    """
    lines = text.splitlines()
    fenced = False
    start = -1
    level = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _is_fence(stripped):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = _HEADING.match(stripped)
        if not heading:
            continue
        depth = len(heading.group(1))
        if start < 0:
            if keyword in heading.group(2):
                start, level = index, depth
            continue
        if depth <= level:
            return lines[start + 1 : index]
    return lines[start + 1 :] if start >= 0 else []


def parse_markdown(
    text: str, source_label: str = "量表"
) -> tuple[list[models.Dimension], str] | None:
    """解析 Markdown 量表表格：维度 | 权重 | 5 分 | 4 分 | 3 分 | 2 分 | 1 分。

    只在“量表”一节内查找，避免把知识点表误读成评分维度；权重按合计归一化。
    """
    section = _section_lines(text, "量表") or text.splitlines()
    merged: dict[str, float] = {}
    for line in section:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        # 分隔行（| --- | --- |）没有维度名也没有权重，直接跳过。
        if all(_SEPARATOR.match(cell) for cell in cells if cell):
            continue
        if "维度" in cells[0]:
            continue
        key = _match_dimension(cells[0])
        weight = _parse_weight(cells[1])
        if key and weight is not None:
            merged.setdefault(key, weight)
    if len(merged) < 3:
        return None

    total = sum(merged.values())
    dims = [
        models.Dimension(key, models.DIMENSION_LABELS[key], round(weight / total, 4))
        for key, weight in merged.items()
    ]
    return (
        dims,
        f"已按 {source_label} 的量表表格解析出 {len(dims)} 个维度并按比例归一化",
    )


def dimensions_from_text(
    text: str, source_label: str = "量表"
) -> tuple[list[models.Dimension], str] | None:
    """从量表文本提取维度；表格优先，其次 `- 维度：30%` 列表。

    识别不到至少 3 个维度时返回 None，由调用方决定回退策略（文件用内置量表，
    数据库中的题目评分标准则回退到其他来源）。
    """
    parsed = parse_markdown(text, source_label)
    if parsed:
        return parsed

    merged: dict[str, float] = {}
    for key, weight in _candidates(text):
        merged.setdefault(key, weight)
    if len(merged) < 3:
        return None

    total = sum(merged.values())
    dims = [
        models.Dimension(key, models.DIMENSION_LABELS[key], round(weight / total, 4))
        for key, weight in merged.items()
    ]
    return dims, f"已按 {source_label} 解析出 {len(dims)} 个维度并按比例归一化"


def load_rubric(path: Path) -> tuple[list[models.Dimension], str]:
    if not path.is_file():
        return list(DEFAULT_RUBRIC), f"未找到量表文件 {path.name}，使用内置默认量表"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return list(DEFAULT_RUBRIC), f"{path.name} 为空（0 字节），使用内置默认量表"

    result = dimensions_from_text(text, path.name)
    if result:
        return result
    return (
        list(DEFAULT_RUBRIC),
        f"{path.name} 未包含可识别的维度与权重，使用内置默认量表",
    )


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_student(
    results: list[models.TaskResult],
    lint_counts: dict[str, int],
    dims: list[models.Dimension],
    runnable: bool = True,
    metrics: dict | None = None,
) -> dict[str, float]:
    """按维度打分：知识点看覆盖率，其余维度按缺陷密度扣分。

    `runnable=False` 表示文件整体无法解析：即使某个函数单独可读，也无法证明
    它在真实运行中成立，因此知识点按 50% 计，规范维度封顶 50 分。
    `metrics` 提供函数长度、嵌套深度等结构指标，用于“代码结构”维度。
    """
    total_points = sum(len(r.spec.points) for r in results) or 1
    covered_points = sum(len(r.covered) for r in results)

    errors = 0
    boundary = 0
    logic = 0
    style = lint_counts.get("style", 0)
    for result in results:
        for issue in result.issues:
            if issue.severity in {"fatal", "error"}:
                errors += 1
            elif issue.dimension == models.BOUNDARY:
                boundary += 1
            elif issue.dimension == models.LOGIC:
                logic += 1
            elif issue.dimension == models.STYLE and issue.source != "pylint":
                style += 1

    coverage = covered_points / total_points * 100
    knowledge = _clamp(coverage * (1.0 if runnable else 0.5))
    syntax = _clamp(100 - 40 * errors - 5 * lint_counts.get("syntax_warning", 0))
    boundary_score = _clamp(100 - 25 * boundary)
    logic_score = _clamp(100 - 25 * logic)
    style_score = _clamp(100 - 3 * style)
    if not runnable:
        style_score = min(style_score, 50.0)

    metrics = metrics or {}
    structure_score = _clamp(
        100
        - 10 * int(metrics.get("long_functions", 0))
        - 10 * int(metrics.get("deep_functions", 0))
        - 5 * int(metrics.get("dense_functions", 0))
    )

    raw = {
        models.KNOWLEDGE: knowledge,
        models.SYNTAX: syntax,
        models.BOUNDARY: boundary_score,
        models.LOGIC: logic_score,
        models.STYLE: style_score,
        models.READABILITY: style_score,
        models.STRUCTURE: structure_score,
    }
    return {dim.key: round(raw.get(dim.key, 0.0), 1) for dim in dims}


def weighted_total(scores: dict[str, float], dims: list[models.Dimension]) -> float:
    return round(sum(scores.get(dim.key, 0.0) * dim.weight for dim in dims), 1)
