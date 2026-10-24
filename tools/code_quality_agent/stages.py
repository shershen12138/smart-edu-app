"""评测流水线的阶段函数。

每个函数只做一步，输入输出都是 LangGraph 的状态字典，便于：
- `agent_graph` 把阶段串成状态图并做条件路由；
- 单元测试单独验证某一步（例如只测知识点检测，不跑 pylint）。

阶段顺序：prepare → lint（可选）→ tasks → notes → score。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TypedDict

from . import lint, models, rubric, rules, static_analysis


class ReviewState(TypedDict, total=False):
    """图状态：输入字段由调用方给，其余由各阶段填充。"""

    # 输入
    source: str
    lint_path: Path
    specs: tuple[models.TaskSpec, ...]
    dimensions: list[models.Dimension]
    name: str
    file_name: str

    # prepare
    blocks: list
    by_name: dict
    helper_names: set
    module_ast: ast.AST | None
    module_error: str | None

    # lint
    lint_messages: list

    # tasks
    results: list
    style_from_issues: int
    structure_stats: dict

    # notes
    style_notes: list
    counts: dict

    # score
    metrics: dict
    scores: dict
    total: float


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


def prepare(state: ReviewState) -> dict:
    """切函数块并解析整份文件；整文件解析失败会记入 module_error。"""
    source = state["source"]
    specs = state["specs"]
    blocks = static_analysis.split_functions(source)
    by_name = {block.name: block for block in blocks}
    helper_names = set(by_name) - {spec.task_id for spec in specs}
    module_ast, module_error = static_analysis.parse_whole(source)
    return {
        "blocks": blocks,
        "by_name": by_name,
        "helper_names": helper_names,
        "module_ast": module_ast,
        "module_error": module_error,
    }


def run_lint(state: ReviewState) -> dict:
    """整文件可解析时才跑 pylint；pylint 需要真实文件路径。"""
    if state.get("module_ast") is None:
        return {"lint_messages": []}
    messages, _ = lint.run(state["lint_path"])
    return {"lint_messages": messages}


def build_tasks(state: ReviewState) -> dict:
    """逐题：知识点命中、结构指标、规则缺陷，并把 pylint 消息归到所属题目。"""
    specs = state["specs"]
    by_name = state["by_name"]
    helper_names = state["helper_names"]
    lint_messages = state.get("lint_messages") or []

    results: list[models.TaskResult] = []
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

    return {
        "results": results,
        "style_from_issues": style_from_issues,
        "structure_stats": structure_stats,
    }


def collect_notes(state: ReviewState) -> dict:
    """汇总 pylint 规范提示与扣分计数；命名问题按一类计，避免一次扣光。"""
    lint_messages = state.get("lint_messages") or []
    style_notes: list[str] = []

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
    counts = {
        "style": (6 if naming else 0)
        + (len(style_lint) - len(naming))
        + state.get("style_from_issues", 0),
        "syntax_warning": syntax_warning,
    }
    return {"style_notes": style_notes, "counts": counts}


def score(state: ReviewState) -> dict:
    """按维度扣分并加权求总分。"""
    results = state["results"]
    dimensions = state["dimensions"]
    structure_stats = state["structure_stats"]
    metrics = {
        "long_functions": structure_stats["long"],
        "deep_functions": structure_stats["deep"],
        "dense_functions": structure_stats["dense"],
        "functions": len(results),
    }
    scores = rubric.score_student(
        results,
        state["counts"],
        dimensions,
        runnable=state.get("module_ast") is not None,
        metrics=metrics,
    )
    total = rubric.weighted_total(scores, dimensions)
    return {"metrics": metrics, "scores": scores, "total": total}
