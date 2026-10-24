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


def known_specs() -> dict[str, models.TaskSpec]:
    known: dict[str, models.TaskSpec] = {}
    for specs in curriculum.COURSE_SPECS.values():
        for spec in specs:
            known[spec.task_id] = spec
    return known


def build_specs(items: Iterable[tuple[str, str]]) -> tuple[models.TaskSpec, ...]:
    """items: [(function_name, title)]，按数据库中的题目顺序生成规格。"""
    known = known_specs()
    specs: list[models.TaskSpec] = []
    for function_name, title in items:
        base = known.get(function_name)
        if base is None:
            specs.append(
                models.TaskSpec(
                    task_id=function_name,
                    title=title or function_name,
                    points=(),
                )
            )
        else:
            specs.append(
                models.TaskSpec(
                    task_id=base.task_id,
                    title=title or base.title,
                    points=base.points,
                )
            )
    return tuple(specs)


def analyze(
    source: str,
    items: Iterable[tuple[str, str]],
    rubric_path: Path,
    workdir: Path,
    name: str = "student",
) -> tuple[pipeline.StudentAnalysis, list[models.Dimension], str]:
    specs = build_specs(items)
    dimensions, rubric_note = rubric.load_rubric(rubric_path)
    analysis = pipeline.analyze_text(source, specs, dimensions, workdir, name)
    return analysis, dimensions, rubric_note


def radar_png(analysis: pipeline.StudentAnalysis, dimensions: Sequence[models.Dimension]) -> bytes:
    """渲染雷达图；缺少 matplotlib 时返回空字节，由调用方降级展示。"""
    try:
        from . import charts
    except Exception:
        return b""
    with tempfile.TemporaryDirectory() as directory:
        target = charts.render(analysis, list(dimensions), Path(directory) / "radar.png")
        return target.read_bytes()


def payload(
    analysis: pipeline.StudentAnalysis,
    dimensions: Sequence[models.Dimension],
    rubric_note: str,
    has_radar: bool,
) -> dict:
    tasks = []
    for result in analysis.results:
        tasks.append(
            {
                "task_id": result.spec.task_id,
                "title": result.spec.title,
                "parsed": result.parsed,
                "points": [
                    {
                        "tag": tag,
                        "label": curriculum.POINT_LABELS.get(tag, tag),
                        "ok": tag in result.covered,
                    }
                    for tag in result.spec.points
                ],
                "issues": [
                    {
                        "line": issue.line,
                        "message": issue.message,
                        "advice": issue.advice,
                        "severity": issue.severity,
                        "dimension": issue.dimension,
                    }
                    for issue in result.defects
                ],
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
            "| 作业编号 | 该题目需要用到的python基础知识点 | 缺陷及所在代码行 | 修改建议 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for result in analysis.results:
        if result.spec.points:
            points = "；".join(
                f"{curriculum.POINT_LABELS.get(tag, tag)} {'✓' if tag in result.covered else '✗'}"
                for tag in result.spec.points
            )
        else:
            points = "未配置知识点模板（仅通用检查）"
        if not result.parsed:
            points = "语法未通过，未能验证"
        defects = result.defects
        if defects:
            detail = "<br>".join(f"第 {issue.line} 行：{issue.message}" for issue in defects)
            advice = "<br>".join(
                dict.fromkeys(issue.advice for issue in defects if issue.advice)
            )
        else:
            detail, advice = "未发现静态缺陷", "—"
        lines.append(
            f"| `{result.spec.task_id}` | {_cell(points)} | {_cell(detail)} | {_cell(advice)} |"
        )
    if analysis.module_note:
        lines.extend(["", f"> 文件整体解析失败：{analysis.module_note}"])
    return "\n".join(lines) + "\n"
