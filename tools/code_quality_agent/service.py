"""供 Django 调用的服务接口。

与命令行入口的区别：
- 输入是数据库中的函数清单与内存里的学生源码，不依赖 data/ 目录的学生文件；
- 题目标题来自 `CourseworkItem`，知识点模板按函数名匹配已有题库规格，
  未配置的函数只做通用检查，不臆造知识点；
- 雷达图以 PNG 字节返回，由调用方存入私有存储。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterable, Sequence

from . import curriculum, models, pipeline, rubric
from . import specs as spec_parser


def known_specs() -> dict[str, models.TaskSpec]:
    known: dict[str, models.TaskSpec] = {}
    for specs in curriculum.COURSE_SPECS.values():
        for spec in specs:
            known[spec.task_id] = spec
    return known


def build_specs(
    items: Iterable[tuple[str, str]],
    *,
    problem_text: str = "",
    reference_source: str = "",
    points_by_function: dict[str, list[str]] | None = None,
) -> tuple[models.TaskSpec, ...]:
    """items: [(function_name, title)]，按数据库中的题目顺序生成规格。

    考点依次取自：已校准的题库规格 → 数据库确认的考点 → 参考答案 AST →
    题面关键词 → `basic_def` 兜底，保证每道题都有可展示的考点。
    """
    return spec_parser.resolve_specs(
        items,
        problem_text=problem_text,
        reference_source=reference_source,
        points_by_function=points_by_function,
    )


def analyze(
    source: str,
    items: Iterable[tuple[str, str]],
    rubric_path: Path,
    workdir: Path,
    name: str = "student",
    dimensions: Sequence[models.Dimension] | None = None,
    rubric_note: str | None = None,
    problem_text: str = "",
    reference_source: str = "",
    points_by_function: dict[str, list[str]] | None = None,
    specs: Sequence[models.TaskSpec] | None = None,
) -> tuple[pipeline.StudentAnalysis, list[models.Dimension], str]:
    """dimensions 为空时读取 Markdown 量表，否则使用数据库中的作业评分标准。

    specs 非空时直接使用调用方给出的已解析规格，跳过图中的考点解析；
    problem_text / reference_source / points_by_function 用于自动确定考点，
    缺省时按题目函数名回退到题库规格与通用检查。
    """
    rows = list(items)
    resolved = tuple(specs) if specs else ()
    if dimensions:
        active = list(dimensions)
        note = rubric_note or "使用作业评分标准"
    else:
        active, note = rubric.load_rubric(rubric_path)
    # specs 为空时由评测图的 specs 节点解析：题库规格 → 数据库确认 → 参考答案 → 题面 → 兜底。
    analysis = pipeline.analyze_text(
        source,
        resolved,
        active,
        workdir,
        name,
        items=rows,
        problem_text=problem_text,
        reference_source=reference_source,
        points_by_function=points_by_function,
    )
    return analysis, active, note


def radar_png(analysis: pipeline.StudentAnalysis, dimensions: Sequence[models.Dimension]) -> bytes:
    """渲染雷达图；缺少 matplotlib 时返回空字节，由调用方降级展示。"""
    try:
        from . import charts
    except Exception:
        return b""
    with tempfile.TemporaryDirectory() as directory:
        target = charts.render(analysis, list(dimensions), Path(directory) / "radar.png")
        return target.read_bytes()


_SEVERITY_ORDER = {"fatal": 0, "error": 1, "warning": 2, "convention": 3}
_REPORT_LIMIT = 8


def report_issues(result: models.TaskResult) -> tuple[list[dict], int]:
    """报告表格里的缺陷：语义缺陷优先，pylint 规范提示排在后面。

    同一句提示在多行出现时合并行号（例如多个单字母变量各报一次命名），
    合并后超过 8 条的只列前 8 条，其余计入 omitted。
    """
    ranked = sorted(
        result.issues,
        key=lambda issue: (
            _SEVERITY_ORDER.get(issue.severity, 4),
            issue.dimension == models.STYLE,
            issue.line,
        ),
    )
    merged: dict[tuple[str, str], dict] = {}
    for issue in ranked:
        key = (issue.dimension, issue.message)
        if key in merged:
            merged[key]["lines"].append(issue.line)
            continue
        merged[key] = {
            "message": issue.message,
            "advice": issue.advice,
            "severity": issue.severity,
            "dimension": issue.dimension,
            "lines": [issue.line],
        }

    items = list(merged.values())
    for item in items:
        lines = list(dict.fromkeys(item.pop("lines")))
        item["line"] = "、".join(str(line) for line in lines)
        item["count"] = len(lines)
    return items[:_REPORT_LIMIT], max(0, len(items) - _REPORT_LIMIT)


def _display_points(
    result: models.TaskResult,
    knowledge_points: dict[str, Sequence[str]] | None,
) -> list[dict]:
    """逐题明细里“作业考察的知识点”一列的内容。

    优先用作业评分标准（`CourseworkRubric.knowledge_points`）中属于该函数的知识点，
    它才是这份作业真正考察的内容；评分标准缺失时才回退到题库规格的标签。
    名称能与题库标签对应时仍给出 ✓/✗，模型自定义的名称只展示、不做机器判定。
    """
    names = list((knowledge_points or {}).get(result.spec.task_id) or ())
    if not names:
        return [
            {
                "tag": tag,
                "label": curriculum.POINT_LABELS.get(tag, tag),
                "ok": tag in result.covered,
                "judged": True,
            }
            for tag in result.spec.points
        ]
    points = []
    for name in names:
        tag = curriculum.LABEL_TO_POINT.get(name)
        judged = bool(tag and tag in result.spec.points)
        points.append(
            {
                "tag": tag or "",
                "label": name,
                "ok": bool(judged and tag in result.covered),
                "judged": judged,
            }
        )
    return points


def payload(
    analysis: pipeline.StudentAnalysis,
    dimensions: Sequence[models.Dimension],
    rubric_note: str,
    has_radar: bool,
    knowledge_points: dict[str, Sequence[str]] | None = None,
) -> dict:
    tasks = []
    for result in analysis.results:
        issues, omitted = report_issues(result)
        tasks.append(
            {
                "task_id": result.spec.task_id,
                "title": result.spec.title,
                "parsed": result.parsed,
                "points": _display_points(result, knowledge_points),
                "issues": [
                    {
                        "line": issue["line"],
                        "message": issue["message"],
                        "advice": issue["advice"],
                        "severity": issue["severity"],
                        "dimension": issue["dimension"],
                        "count": issue["count"],
                    }
                    for issue in issues
                ],
                "issue_omitted": omitted,
            }
        )
    return {
        "total": analysis.total,
        "grade": analysis.grade,
        "scores": [
            {
                "key": dimension.key,
                "label": dimension.label,
                "weight": round(dimension.weight * 100),
                "score": analysis.scores.get(dimension.key, 0.0),
            }
            for dimension in dimensions
        ],
        "tasks": tasks,
        "style_notes": analysis.style_notes,
        "module_note": analysis.module_note,
        "rubric_note": rubric_note,
        "has_radar": has_radar,
    }


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def markdown(
    analysis: pipeline.StudentAnalysis,
    dimensions: Sequence[models.Dimension],
    rubric_note: str,
    knowledge_points: dict[str, Sequence[str]] | None = None,
) -> str:
    lines = [
        f"# {analysis.name} 代码质量评测报告",
        "",
        f"- 总分：{analysis.total:.1f} / 100（{analysis.grade}）",
        f"- 量表：{rubric_note}",
        "",
        "| 维度 | 权重 | 得分 |",
        "| --- | --- | --- |",
    ]
    for dimension in dimensions:
        lines.append(
            f"| {dimension.label} | {dimension.weight * 100:.0f}% | "
            f"{analysis.scores.get(dimension.key, 0.0):.0f} |"
        )
    lines.extend(
        [
            "",
            "| 题目编号 | 作业考察的知识点 | 缺陷及所在代码行 | 修改建议 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for result in analysis.results:
        display = _display_points(result, knowledge_points)
        if display:
            points = "；".join(
                f"{item['label']} {'✓' if item['ok'] else '✗'}"
                if item["judged"]
                else item["label"]
                for item in display
            )
        else:
            points = "未配置知识点模板（仅通用检查）"
        if not result.parsed:
            points = "语法未通过，未能验证"
        issues, omitted = report_issues(result)
        if issues:
            detail = "<br>".join(
                f"第 {issue['line']} 行：{issue['message']}" for issue in issues
            )
            if omitted:
                detail += f"<br>（另有 {omitted} 条提示未列出）"
            advice = "<br>".join(
                dict.fromkeys(issue["advice"] for issue in issues if issue["advice"])
            )
        else:
            detail, advice = "未发现静态缺陷", "—"
        lines.append(
            f"| `{result.spec.task_id}` | {_cell(points)} | {_cell(detail)} | {_cell(advice)} |"
        )
    if analysis.module_note:
        lines.extend(["", f"> 文件整体解析失败：{analysis.module_note}"])
    return "\n".join(lines) + "\n"
