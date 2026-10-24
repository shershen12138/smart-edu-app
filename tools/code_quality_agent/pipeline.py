"""编排：发现学生文件 -> 静态分析 -> 规则校验 -> 打分。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import curriculum, lint, models, rubric, rules, static_analysis
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


def _task_issue(
    task_id: str,
    line: int,
    message: str,
    advice: str,
    dimension: str,
    severity: str = "warning",
    source: str = "rule",
) -> models.Issue:
    return models.Issue(
        task_id=task_id,
        line=max(1, line),
        message=message,
        dimension=dimension,
        severity=severity,
        source=source,
        advice=advice,
    )


def _analyze_source(
    source: str,
    lint_path: Path,
    specs: tuple[models.TaskSpec, ...],
    dimensions: list[models.Dimension],
    name: str,
    file_name: str,
) -> StudentAnalysis:
    blocks = static_analysis.split_functions(source)
    by_name = {block.name: block for block in blocks}
    helper_names = set(by_name) - {spec.task_id for spec in specs}

    module_ast, module_error = static_analysis.parse_whole(source)
    lint_messages: list[lint.LintMessage] = []
    if module_ast is not None:
        lint_messages, _ = lint.run(lint_path)

    results: list[models.TaskResult] = []
    style_notes: list[str] = []
    style_from_issues = 0
    structure_stats = {"long": 0, "deep": 0, "dense": 0}

    for spec in specs:
        result = models.TaskResult(spec=spec, parsed=False)
        block = by_name.get(spec.task_id)
        if block is None:
            result.issues.append(
                _task_issue(
                    spec.task_id,
                    1,
                    f"未找到函数 {spec.task_id} 的定义",
                    "按题目要求补上函数定义并返回结果",
                    models.KNOWLEDGE,
                    severity="error",
                    source="ast",
                )
            )
        elif block.syntax_error:
            result.issues.append(
                _task_issue(
                    spec.task_id,
                    block.error_line or block.start_line,
                    f"语法错误：{block.syntax_error}",
                    "先修正该函数的语法，使其可以独立解析，再检查逻辑",
                    models.SYNTAX,
                    severity="error",
                    source="syntax",
                )
            )
        else:
            result.parsed = True
            node = block.node
            assert node is not None
            detected = set(static_analysis.detect_points(node, helper_names))
            result.covered = [tag for tag in spec.points if tag in detected]
            result.missing = [tag for tag in spec.points if tag not in detected]

            metric = static_analysis.function_metrics(node)
            if metric["lines"] > 40:
                structure_stats["long"] += 1
            if metric["depth"] > 3:
                structure_stats["deep"] += 1
            if metric["statements"] > 25:
                structure_stats["dense"] += 1

            findings = list(rules.evaluate_task(spec.task_id, node, helper_names))
            findings.extend(rules.common_rules(node))
            for relative_line, message, advice, dimension in findings:
                result.issues.append(
                    _task_issue(
                        spec.task_id,
                        block.start_line + relative_line - 1,
                        message,
                        advice,
                        dimension,
                    )
                )

        for message in lint_messages:
            if not (block and block.start_line <= message.line <= block.end_line):
                continue
            if message.symbol == "syntax-error":
                continue
            issue = _task_issue(
                spec.task_id,
                message.line,
                message.message,
                message.advice,
                message.dimension,
                severity=message.severity,
                source="pylint",
            )
            result.issues.append(issue)

        result.issues.sort(key=lambda item: (item.line, item.message))
        style_from_issues += sum(
            1
            for issue in result.issues
            if issue.dimension == models.STYLE and issue.source != "pylint"
        )
        results.append(result)

    style_lint = [
        message
        for message in lint_messages
        if message.dimension == models.STYLE and message.symbol != "syntax-error"
    ]
    naming = [message for message in style_lint if message.symbol == "invalid-name"]
    if naming:
        lines = list(dict.fromkeys(message.line for message in naming))[:6]
        preview = "、".join(str(line) for line in lines)
        style_notes.append(
            f"命名不规范共 {len(naming)} 处（第 {preview} 行等），"
            "单字母变量名会降低可读性"
        )
    for message in style_lint:
        if message.symbol == "invalid-name":
            continue
        note = f"第 {message.line} 行：{message.message}"
        if note not in style_notes:
            style_notes.append(note)

    syntax_warning = sum(
        1
        for message in lint_messages
        if message.dimension == models.SYNTAX and message.severity == "warning"
    )
    # 命名问题按"一类问题"计分，避免大量单字母变量把规范分一次扣光。
    counts = {
        "style": (6 if naming else 0) + (len(style_lint) - len(naming)) + style_from_issues,
        "syntax_warning": syntax_warning,
    }
    runnable = module_ast is not None
    metrics = {
        "long_functions": structure_stats["long"],
        "deep_functions": structure_stats["deep"],
        "dense_functions": structure_stats["dense"],
        "functions": len(results),
    }
    scores = rubric.score_student(
        results, counts, dimensions, runnable=runnable, metrics=metrics
    )
    total = rubric.weighted_total(scores, dimensions)

    return StudentAnalysis(
        name=name,
        file_name=file_name,
        results=results,
        scores=scores,
        total=total,
        style_notes=style_notes[:8],
        module_note=module_error,
        metrics=metrics,
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
) -> StudentAnalysis:
    """从内存中的源码分析（数据库提交使用）。pylint 需要真实文件，临时落盘后删除。"""
    workdir.mkdir(parents=True, exist_ok=True)
    lint_path = workdir / f"lint-{name}.py"
    lint_path.write_text(source, encoding="utf-8")
    try:
        return _analyze_source(source, lint_path, specs, dimensions, name, f"{name}.py")
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
