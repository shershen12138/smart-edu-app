"""编排入口：发现学生文件 → 执行评测图 → 组装学生报告数据。

各阶段实现在 `stages.py`，执行顺序与条件分支由 `agent_graph` 的 LangGraph
状态图决定；本模块只负责文件发现、临时落盘与最终数据结构组装。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import agent_graph, curriculum, lint, models, rubric
from .config import CourseContext, build_context


@dataclass
class StudentAnalysis:
    name: str
    file_name: str
    results: list[models.TaskResult]
    scores: dict[str, float]
    total: float
    style_notes: list[str] = field(default_factory=list)
    module_note: str | None = None
    metrics: dict = field(default_factory=dict)

    @property
    def grade(self) -> str:
        total = self.total
        if total >= 90:
            return "A"
        if total >= 80:
            return "B"
        if total >= 70:
            return "C"
        if total >= 60:
            return "D"
        return "E"


@dataclass
class Evaluation:
    context: CourseContext
    dimensions: list[models.Dimension]
    rubric_note: str
    students: list[StudentAnalysis]
    lint_note: str | None = None


def _analyze_source(
    source: str,
    lint_path: Path,
    specs: tuple[models.TaskSpec, ...],
    dimensions: list[models.Dimension],
    name: str,
    file_name: str,
    *,
    items: Sequence[tuple[str, str]] = (),
    problem_text: str = "",
    reference_source: str = "",
    points_by_function: dict[str, list[str]] | None = None,
) -> StudentAnalysis:
    """执行 LangGraph 评测图，再把最终状态组装成学生报告数据。

    `specs` 为空时由图中的 `resolve_specs` 节点按题目、题面与参考答案推断考点。
    """
    state = agent_graph.invoke(
        {
            "source": source,
            "lint_path": lint_path,
            "specs": specs,
            "dimensions": dimensions,
            "name": name,
            "file_name": file_name,
            "items": list(items),
            "problem_text": problem_text,
            "reference_source": reference_source,
            "points_by_function": points_by_function or {},
        }
    )
    return StudentAnalysis(
        name=name,
        file_name=file_name,
        results=state["results"],
        scores=state["scores"],
        total=state["total"],
        style_notes=state["style_notes"][:8],
        module_note=state.get("module_error"),
        metrics=state["metrics"],
    )


def _analyze_student(
    path: Path,
    specs: tuple[models.TaskSpec, ...],
    dimensions: list[models.Dimension],
) -> StudentAnalysis:
    source = path.read_text(encoding="utf-8", errors="replace")
    return _analyze_source(source, path, specs, dimensions, path.stem, path.name)


def analyze_text(
    source: str,
    specs: tuple[models.TaskSpec, ...],
    dimensions: list[models.Dimension],
    workdir: Path,
    name: str = "student",
    *,
    items: Sequence[tuple[str, str]] = (),
    problem_text: str = "",
    reference_source: str = "",
    points_by_function: dict[str, list[str]] | None = None,
) -> StudentAnalysis:
    """从内存中的源码分析（数据库提交使用）。pylint 需要真实文件，临时落盘后删除。"""
    workdir.mkdir(parents=True, exist_ok=True)
    lint_path = workdir / f"lint-{name}.py"
    lint_path.write_text(source, encoding="utf-8")
    try:
        return _analyze_source(
            source,
            lint_path,
            specs,
            dimensions,
            name,
            f"{name}.py",
            items=items,
            problem_text=problem_text,
            reference_source=reference_source,
            points_by_function=points_by_function,
        )
    finally:
        try:
            lint_path.unlink()
        except OSError:
            pass


def run(course: str, rubric_path: Path | None = None) -> Evaluation:
    context = build_context(course, rubric_path)
    specs = curriculum.specs_for(course)
    dimensions, rubric_note = rubric.load_rubric(context.rubric_file)

    files = sorted(p for p in context.student_dir.glob("*.py") if p.is_file())
    students = [_analyze_student(path, specs, dimensions) for path in files]
    students.sort(key=lambda item: item.name)

    lint_note = None
    if not lint.pylint_available():
        lint_note = "pylint 不可用，本次报告仅包含语法与 AST 语义分析结果"

    return Evaluation(
        context=context,
        dimensions=dimensions,
        rubric_note=rubric_note,
        students=students,
        lint_note=lint_note,
    )
