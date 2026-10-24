"""Markdown 报告渲染。表头固定为需求要求的四项。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from . import curriculum, models
from .pipeline import Evaluation


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>").strip()


def _points_cell(result: models.TaskResult) -> str:
    labels = [curriculum.POINT_LABELS.get(tag, tag) for tag in result.spec.points]
    if not result.parsed:
        return "；".join(labels) + "（语法未通过，未能验证）"
    parts = []
    for tag, label in zip(result.spec.points, labels):
        mark = "✓" if tag in result.covered else "✗"
        parts.append(f"{label} {mark}")
    return "；".join(parts)


def _defect_cell(result: models.TaskResult) -> str:
    defects = result.defects
    if not defects:
        return "未发现静态缺陷"
    shown = defects[:4]
    text = "<br>".join(issue.as_cell_text() for issue in shown)
    if len(defects) > len(shown):
        text += f"<br>…另有 {len(defects) - len(shown)} 条"
    return text


def _advice_cell(result: models.TaskResult) -> str:
    defects = result.defects
    if not defects:
        return "—"
    advices = list(dict.fromkeys(issue.advice for issue in defects[:4] if issue.advice))
    return "<br>".join(advices) if advices else "按题目要求核对实现"


def _overview(evaluation: Evaluation) -> list[str]:
    header = "| 学生 | 总分 | 等级 | " + " | ".join(
        dim.label for dim in evaluation.dimensions
    ) + " | 缺陷条数 |"
    divider = "| --- | --- | --- | " + " | ".join("---" for _ in evaluation.dimensions) + " | --- |"
    rows = [header, divider]
    for student in evaluation.students:
        score_cells = " | ".join(
            f"{student.scores.get(dim.key, 0):.0f}" for dim in evaluation.dimensions
        )
        defects = sum(len(result.defects) for result in student.results)
        rows.append(
            f"| {student.name} | {student.total:.1f} | {student.grade} | "
            f"{score_cells} | {defects} |"
        )
    return rows


def _student_section(student, chart_relative: str) -> list[str]:
    lines = [
        f"### {student.name} · 总分 {student.total:.1f} / 100（{student.grade}）",
        "",
        f"![{student.name} 代码完成度]({chart_relative})",
        "",
        "| 作业编号 | 该题目需要用到的python基础知识点 | 缺陷及所在代码行 | 修改建议 |",
        "| --- | --- | --- | --- |",
    ]
    for result in student.results:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{result.spec.task_id}`",
                    _cell(_points_cell(result)),
                    _cell(_defect_cell(result)),
                    _cell(_advice_cell(result)),
                ]
            )
            + " |"
        )
    lines.append("")
    if student.module_note:
        lines.append(f"> 文件整体解析失败：{student.module_note}；pylint 已跳过，缺陷来自逐函数语法检查。")
        lines.append("")
    if student.style_notes:
        lines.append("**pylint 规范提示（不计入缺陷列，影响“代码规范”维度）**")
        lines.append("")
        for note in student.style_notes:
            lines.append(f"- {note}")
        lines.append("")
    return lines


def _summary(evaluation: Evaluation) -> list[str]:
    counter: Counter[str] = Counter()
    for student in evaluation.students:
        for result in student.results:
            for issue in result.defects:
                counter[issue.message.split("：")[0]] += 1

    lines = ["## 四、共性缺陷与教学建议", ""]
    if not counter:
        lines.append("本次样本未发现共性缺陷。")
        lines.append("")
        return lines

    lines.append("| 出现次数 | 缺陷类型 |")
    lines.append("| --- | --- |")
    for message, count in counter.most_common(8):
        lines.append(f"| {count} | {_cell(message)} |")
    lines.append("")

    suggestions: list[str] = []
    if any("语法错误" in key for key in counter):
        suggestions.append("先做语法专项：函数定义与 if 语句的冒号、`=` 与 `==` 的区别、缩进一致性。")
    if any(keyword in key for key in counter for keyword in ("越界", "range", "边界")):
        suggestions.append("用空列表、单元素、偶数长度、上界元素四类数据练习边界推演，特别是 range 右端不包含。")
    if any(keyword in key for key in counter for keyword in ("返回", "切片", "分支", "排序", "类型")):
        suggestions.append("要求学生先用题目给的样例手工走一遍分支和返回值，再写代码，减少“能跑但意思反了”的错误。")
    if any(keyword in key for key in counter for keyword in ("未使用", "命名", "覆盖")):
        suggestions.append("统一变量命名并清理未使用变量，把 pylint 的规范提示纳入平时作业自查。")
    if not suggestions:
        suggestions.append("按题目知识点逐个补练，优先保证每个函数都有明确的返回值。")

    lines.append("**建议**")
    lines.append("")
    for item in suggestions:
        lines.append(f"- {item}")
    lines.append("")
    return lines


def build(evaluation: Evaluation, chart_paths: dict[str, str]) -> str:
    context = evaluation.context
    dimensions = evaluation.dimensions
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = [
        f"# {context.course} 学生代码质量评测报告",
        "",
        f"- 生成时间：{now}",
        f"- 课程 / 题量：{context.course} / {len(curriculum.specs_for(context.course))} 题",
        f"- 学生样本：{len(evaluation.students)} 人（{context.student_dir.name}）",
        "- 作业编号沿用题库函数名（func301 表示第 3 章第 1 题）",
        f"- 分析链路：pylint 静态检查 + AST 知识点检测 + 题库语义规则 + 评分量表加权",
        "",
        "## 一、评测口径",
        "",
        "| 维度 | 权重 | 判定方式 |",
        "| --- | --- | --- |",
    ]
    for dim in dimensions:
        lines.append(f"| {dim.label} | {dim.weight * 100:.0f}% | {_dimension_method(dim.key)} |")
    lines.extend(
        [
            "",
            f"**量表来源**：{evaluation.rubric_note}。",
            "",
        ]
    )
    if evaluation.lint_note:
        lines.extend([f"> {evaluation.lint_note}", ""])
    lines.extend(
        [
            "**边界说明**：本次为静态评测，学生代码没有被执行（本机 Docker Linux 引擎不可用，"
            "按项目约定不在主机直接运行学生代码），因此缺陷是静态推断，"
            "“疑似”项需要教师用样例数据复核；报告不把静态推断写成运行通过或运行失败。",
            "",
            "## 二、总览",
            "",
        ]
    )
    lines.extend(_overview(evaluation))
    lines.extend(["", "## 三、分学生报告", ""])

    for student in evaluation.students:
        lines.extend(
            _student_section(student, chart_paths.get(student.name, ""))
        )

    lines.extend(_summary(evaluation))
    return "\n".join(lines).rstrip() + "\n"


def _dimension_method(key: str) -> str:
    return {
        models.KNOWLEDGE: "题目要求的知识点命中率（AST 检测）；文件整体无法解析时按 50% 计",
        models.SYNTAX: "语法错误与 lint error 逐条扣分（每条 40 分）",
        models.BOUNDARY: "越界、上界等边界缺陷扣分（每条 25 分）",
        models.LOGIC: "与题意冲突的写法（返回码、方向、类型）扣分（每条 25 分）",
        models.STYLE: "pylint 规范提示扣分（命名问题按一类计）",
    }.get(key, "按缺陷密度扣分")
