"""考点解析：让每份作业都有可展示的考点，不再依赖手工登记题库。

每题独立按以下优先级确定考点：

1. `curriculum.COURSE_SPECS`：已按题库参考答案校准的规格，精度最高；
2. 数据库确认的考点（`points_by_function`，来自教师或大模型生成的知识点）；
3. 参考答案 `gold.py` 的 AST 检测：参考答案用到的语法就是该题的考点；
4. 题面关键词推断：没有参考答案时从题目说明里识别；
5. `basic_def` 兜底：函数定义与返回值，保证报告永远有具体考点。

第 2～5 步都不需要改代码，新增 05、06、07 等作业时自动生效。
"""

from __future__ import annotations

import ast
import re
from typing import Iterable, Mapping, Sequence

from . import curriculum, models, static_analysis

_FUNCTION = re.compile(r"func\d+")

# 题面关键词 → 考点标签。只收强特征词，避免“列表”“如果”这类到处出现的词误判。
_KEYWORDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("二进制", "十进制", "十六进制", "进制转换"), ("while_loop", "modulo", "floor_div")),
    (("奇数", "偶数"), ("modulo", "if_else")),
    (("整除", "余数", "取余", "因子", "质数", "素数"), ("modulo",)),
    (("循环", "遍历", "反复"), ("loop",)),
    (("while",), ("while_loop",)),
    (("范围", "区间内", "1-n", "[1,n)", "1~n"), ("range_loop",)),
    (("双重", "嵌套", "各种组合", "所有组合", "方案数"), ("nested_loop",)),
    (("break", "continue", "跳出", "结束循环"), ("loop_control",)),
    (("排序", "升序", "降序", "从小到大", "从大到小"), ("sort_builtin",)),
    (("比较", "较大", "较小", "最大值", "最小值", "最大", "最小"), ("compare",)),
    (("判断", "是否"), ("if_else",)),
    (("分档", "多条件", "等级", "折扣", "票价", "优秀", "及格"), ("elif_chain",)),
    (("字典", "键值", "键值对"), ("dict_access",)),
    (("集合", "去重"), ("set_op",)),
    (("大写", "小写", "大小写", "字符串方法"), ("str_method",)),
    (("拼接", "连接", "字符串形式"), ("str_join",)),
    (("逆序", "反转"), ("slice_reverse",)),
    (("切片",), ("slice_bounds",)),
    (("长度", "几位", "位数"), ("len", "int_str_convert")),
    (("每一位", "每位", "数位", "各位数字"), ("int_str_convert",)),
    (("递归",), ("recursion",)),
    (("异常", "错误处理", "try"), ("try_except",)),
    (("文件", "读取文件", "写入文件"), ("file_open",)),
    (("类定义", "对象", "继承"), ("class_def",)),
    (("enumerate", "zip"), ("enumerate_zip",)),
    (("计数", "统计", "个数", "求和", "累加", "总分", "得分"), ("counter",)),
    (("推导式",), ("comprehension",)),
    (("二维", "矩阵"), ("nested_list", "double_loop")),
    (("lambda",), ("lambda",)),
)

_FALLBACK = ("basic_def",)
_MAX_TAGS = 6


def normalize_tags(tags: Iterable[str], limit: int = _MAX_TAGS) -> tuple[str, ...]:
    """只保留已注册的标签，去重保序。未注册标签不会进入报告，避免永远判 ✗。"""
    result: list[str] = []
    for tag in tags:
        text = str(tag).strip()
        if text in curriculum.POINT_LABELS and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def split_problem_text(text: str) -> dict[str, str]:
    """按 `funcXXX` 把题目说明切成每题一段。

    题目包里的写法是“描述 … 其它要求 将代码写入函数func401”，描述在函数名之前，
    所以一段的结束位置就是该函数名出现的位置。
    """
    if not text:
        return {}
    segments: dict[str, str] = {}
    start = 0
    for match in _FUNCTION.finditer(text):
        segments[match.group(0)] = text[start : match.end()]
        start = match.end()
    return segments


def infer_from_text(segment: str) -> tuple[str, ...]:
    """从题面段落推断考点；无命中返回空元组。"""
    if not segment:
        return ()
    tags: list[str] = []
    for words, mapped in _KEYWORDS:
        if any(word in segment for word in words):
            tags.extend(mapped)
    return normalize_tags(tags)


def infer_from_reference(
    source: str, function_names: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    """用参考答案的 AST 推断每题考点。

    参考答案是该题的示范实现，它用到的语法就是出题人期望的写法，比题面关键词更准。
    """
    if not source.strip():
        return {}
    tree, _ = static_analysis.parse_whole(source)
    if tree is None:
        return {}
    wanted = set(function_names)
    known = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    }
    helpers = known - wanted
    found: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
            continue
        detected = static_analysis.detect_points(node, helpers)
        # basic_def 是所有有效实现都成立的兜底项，不作为参考答案推导出的考点。
        tags = [tag for tag in detected if tag != "basic_def"]
        found[node.name] = normalize_tags(tags)
    return found


def resolve_specs(
    items: Iterable[tuple[str, str]],
    *,
    problem_text: str = "",
    reference_source: str = "",
    points_by_function: Mapping[str, Sequence[str]] | None = None,
) -> tuple[models.TaskSpec, ...]:
    """按优先级为每道题确定考点，保证返回的 spec 都有非空 points。"""
    known = {
        spec.task_id: spec
        for specs in curriculum.COURSE_SPECS.values()
        for spec in specs
    }
    rows = list(items)
    names = [name for name, _ in rows]
    segments = split_problem_text(problem_text)
    reference = infer_from_reference(reference_source, names)
    confirmed = points_by_function or {}

    resolved: list[models.TaskSpec] = []
    for function_name, title in rows:
        base = known.get(function_name)
        if base is not None:
            tags = tuple(base.points)
            label = title or base.title
        else:
            tags = normalize_tags(confirmed.get(function_name, ()))
            if not tags:
                tags = reference.get(function_name, ())
            if not tags:
                tags = infer_from_text(segments.get(function_name, ""))
            if not tags:
                tags = _FALLBACK
            label = title or function_name
        resolved.append(
            models.TaskSpec(task_id=function_name, title=label, points=tags)
        )
    return tuple(resolved)
