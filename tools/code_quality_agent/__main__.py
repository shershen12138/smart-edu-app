"""代码质量评测智能体（静态分析版）。

用法：
    python -m tools.code_quality_agent --course 03-列表
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import charts, pipeline, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="code_quality_agent",
        description="用 pylint 与 AST 规则评测学生代码质量，输出 Markdown 报告与雷达图",
    )
    parser.add_argument("--course", default="03-列表", help="课程目录名，默认 03-列表")
    parser.add_argument(
        "--rubric",
        type=Path,
        default=None,
        help="评分量表 Markdown 路径，默认取 data/<课程>评分量表.md",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="报告输出目录，默认 reports/<课程>",
    )
    args = parser.parse_args(argv)

    evaluation = pipeline.run(args.course, args.rubric)
    output_dir = args.out or evaluation.context.report_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    chart_paths: dict[str, str] = {}
    for index, student in enumerate(evaluation.students, start=1):
        slug = charts.student_slug(student.name, index)
        relative = f"radar/{slug}.png"
        charts.render(student, evaluation.dimensions, output_dir / relative)
        chart_paths[student.name] = relative

    report_file = output_dir / "评测报告.md"
    report_file.write_text(report.build(evaluation, chart_paths), encoding="utf-8")

    print(f"课程：{evaluation.context.course}")
    print(f"量表：{evaluation.rubric_note}")
    print(f"学生：{len(evaluation.students)} 人")
    for student in evaluation.students:
        print(f"  {student.name}: {student.total:.1f} 分（{student.grade}）")
    print(f"报告：{report_file}")
    print(f"图表：{output_dir / 'radar'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
