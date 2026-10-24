"""评分量表与打分。

量表优先读取 `data/03评分量表.md`：支持 Markdown 表格（维度 | 权重）和
`- 维度：30%` 两种写法。文件为空或无法识别时，退回内置量表，并在报告
开头明确标注，避免把内置规则说成教师给定的量表。
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

KEYWORDS = {
    models.KNOWLEDGE: ("知识点", "知识", "掌握"),
    models.SYNTAX: ("语法", "静态", "编译"),
    models.BOUNDARY: ("边界", "健壮", "鲁棒", "异常"),
    models.LOGIC: ("逻辑", "题意", "正确性", "一致"),
    models.STYLE: ("规范", "风格", "可读", "命名"),
}

_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*%?")
_BULLET = re.compile(r"^\s*[-*]\s*([^:：]+)[:：]\s*(.+)$")


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


def load_rubric(path: Path) -> tuple[list[models.Dimension], str]:
    if not path.is_file():
        return list(DEFAULT_RUBRIC), f"未找到量表文件 {path.name}，使用内置默认量表"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return list(DEFAULT_RUBRIC), f"{path.name} 为空（0 字节），使用内置默认量表"

    found = _candidates(text)
    merged: dict[str, float] = {}
    for key, weight in found:
        merged.setdefault(key, weight)
    if len(merged) < 3:
        return (
            list(DEFAULT_RUBRIC),
            f"{path.name} 未包含可识别的维度与权重，使用内置默认量表",
        )

    total = sum(merged.values())
    dims = [
        models.Dimension(key, models.DIMENSION_LABELS[key], round(weight / total, 4))
        for key, weight in merged.items()
    ]
    return dims, f"已按 {path.name} 解析出 {len(dims)} 个维度并按比例归一化"


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_student(
    results: list[models.TaskResult],
    lint_counts: dict[str, int],
    dims: list[models.Dimension],
    runnable: bool = True,
) -> dict[str, float]:
    """按维度打分：知识点看覆盖率，其余维度按缺陷密度扣分。

    `runnable=False` 表示文件整体无法解析：即使某个函数单独可读，也无法证明
    它在真实运行中成立，因此知识点按 50% 计，规范维度封顶 50 分。
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

    raw = {
        models.KNOWLEDGE: knowledge,
        models.SYNTAX: syntax,
        models.BOUNDARY: boundary_score,
        models.LOGIC: logic_score,
        models.STYLE: style_score,
    }
    return {dim.key: round(raw.get(dim.key, 0.0), 1) for dim in dims}


def weighted_total(scores: dict[str, float], dims: list[models.Dimension]) -> float:
    return round(sum(scores.get(dim.key, 0.0) * dim.weight for dim in dims), 1)
