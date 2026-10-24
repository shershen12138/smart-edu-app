"""静态分析：按顶层函数切块、逐块解析、检测知识点是否落地。

只做 AST 层面的判断，不执行学生代码。任何"运行期才知道"的结论都不在
这里下判断，避免把猜测写成事实。
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass

_DEF_RE = re.compile(r"^def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)


@dataclass
class FunctionBlock:
    name: str
    start_line: int  # 1 起始，相对源文件
    end_line: int
    node: ast.FunctionDef | None = None
    syntax_error: str | None = None
    error_line: int | None = None


def split_functions(source: str) -> list[FunctionBlock]:
    """按顶层 def 切块。带语法错误的文件也能逐块分析其余函数。"""
    matches = list(_DEF_RE.finditer(source))
    if not matches:
        return []
    lines = source.splitlines()
    blocks: list[FunctionBlock] = []
    for index, match in enumerate(matches):
        start = source.count("\n", 0, match.start()) + 1
        end = (
            source.count("\n", 0, matches[index + 1].start())
            if index + 1 < len(matches)
            else len(lines)
        )
        chunk = "\n".join(lines[start - 1 : end])
        block = FunctionBlock(match.group(1), start, end)
        try:
            module = ast.parse(textwrap.dedent(chunk))
            for node in module.body:
                if isinstance(node, ast.FunctionDef):
                    block.node = node
                    break
            if block.node is None:
                block.syntax_error = "未解析出函数定义"
        except SyntaxError as exc:
            block.syntax_error = _syntax_message(exc)
            relative = exc.lineno or 1
            block.error_line = min(start + relative - 1, end)
        blocks.append(block)
    return blocks


def _syntax_message(exc: SyntaxError) -> str:
    raw = (exc.msg or "语法错误").strip()
    hint = {
        "expected ':'": "缺少冒号",
        "invalid syntax": "语法不合法（常见于 if / def 缺少冒号，或把 == 写成 =）",
        "was never closed": "括号或引号没有闭合",
        "invalid decimal literal": "数字字面量不合法",
        "unexpected indent": "缩进不一致",
    }.get(raw, raw)
    return hint


def parse_whole(source: str) -> tuple[ast.Module | None, str | None]:
    try:
        return ast.parse(source), None
    except SyntaxError as exc:
        return None, f"第 {exc.lineno} 行：{_syntax_message(exc)}"


# --------------------------------------------------------------------------
# 知识点检测器：tag -> 判定函数
# --------------------------------------------------------------------------


def _walk(node: ast.AST):
    return ast.walk(node)


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in _walk(node):
        if isinstance(item, ast.Call):
            if isinstance(item.func, ast.Name):
                names.add(item.func.id)
            elif isinstance(item.func, ast.Attribute):
                names.add(item.func.attr)
    return names


def _has_listcomp(node: ast.AST) -> bool:
    return any(isinstance(item, ast.ListComp) for item in _walk(node))


def _slice_steps(node: ast.AST) -> list[int | None]:
    steps: list[int | None] = []
    for item in _walk(node):
        if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Slice):
            step = item.slice.step
            if _is_minus_one(step):
                steps.append(-1)
            elif isinstance(step, ast.Constant) and isinstance(step.value, int):
                steps.append(step.value)
            else:
                steps.append(None)
    return steps


_LOOP_NODES = (ast.For, ast.While)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def _has_nested_loop(node: ast.AST) -> bool:
    """嵌套 for/while，或循环体内使用推导式（推导式本身即一层循环）。"""
    for outer in _walk(node):
        if isinstance(outer, _LOOP_NODES):
            for inner in ast.walk(outer):
                if inner is not outer and isinstance(inner, _LOOP_NODES):
                    return True
                if isinstance(inner, _COMPREHENSIONS):
                    return True
    return False


def _has_break(node: ast.AST) -> bool:
    return any(isinstance(item, ast.Break) for item in _walk(node))


def _is_minus_one(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and node.operand.value == 1
    )


def d_list_concat(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Add):
            if isinstance(item.left, (ast.Name, ast.Subscript, ast.List)):
                return True
    return "extend" in _call_names(fn)


def d_slice_bounds(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Slice):
            if item.slice.lower is not None or item.slice.upper is not None:
                return True
    return False


def d_slice_reverse(fn, helpers) -> bool:
    return -1 in _slice_steps(fn)


def d_len(fn, helpers) -> bool:
    return "len" in _call_names(fn)


def d_index_arith(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.Subscript) and isinstance(
            item.slice, (ast.BinOp, ast.UnaryOp)
        ):
            return True
    return False


def d_floor_div(fn, helpers) -> bool:
    return any(
        isinstance(item, ast.BinOp) and isinstance(item.op, ast.FloorDiv)
        for item in _walk(fn)
    )


def d_compare(fn, helpers) -> bool:
    return any(isinstance(item, ast.Compare) for item in _walk(fn))


def d_if_else(fn, helpers) -> bool:
    return any(isinstance(item, ast.If) and item.orelse for item in _walk(fn))


def d_elif_chain(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.If) and any(isinstance(x, ast.If) for x in item.orelse):
            return True
    return False


def d_loop(fn, helpers) -> bool:
    return any(isinstance(item, ast.For) for item in _walk(fn))


def d_while_loop(fn, helpers) -> bool:
    return any(isinstance(item, ast.While) for item in _walk(fn))


def d_nested_loop(fn, helpers) -> bool:
    return _has_nested_loop(fn)


def d_negative_index(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.Subscript) and _is_minus_one(item.slice):
            return True
        if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.UnaryOp):
            return True
    return False


def d_list_mutation(fn, helpers) -> bool:
    if _call_names(fn) & {"append", "insert", "extend", "pop", "remove"}:
        return True
    return any(isinstance(item, ast.Delete) for item in _walk(fn))


def d_del_or_rebuild(fn, helpers) -> bool:
    if any(isinstance(item, ast.Delete) for item in _walk(fn)):
        return True
    return _has_listcomp(fn)


def d_comprehension(fn, helpers) -> bool:
    return _has_listcomp(fn)


def d_type_check(fn, helpers) -> bool:
    return bool(_call_names(fn) & {"type", "isinstance"})


def d_helper_function(fn, helpers) -> bool:
    calls = _call_names(fn)
    return bool(calls & set(helpers))


def d_counter(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.AugAssign) and isinstance(item.op, ast.Add):
            return True
        if (
            isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and isinstance(item.value, ast.BinOp)
            and isinstance(item.value.op, ast.Add)
        ):
            target = item.targets[0].id
            if isinstance(item.value.left, ast.Name) and item.value.left.id == target:
                return True
    return False


def d_nested_list(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.Subscript) and isinstance(item.value, ast.Subscript):
            return True
        if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Tuple):
            return True
    return False


def d_sort_key(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
            if item.func.attr in {"sort", "sorted"}:
                if any(kw.arg == "key" for kw in item.keywords):
                    return True
    return False


def d_lambda(fn, helpers) -> bool:
    return any(isinstance(item, ast.Lambda) for item in _walk(fn))


def d_range_loop(fn, helpers) -> bool:
    return "range" in _call_names(fn)


def d_int_str_convert(fn, helpers) -> bool:
    return bool(_call_names(fn) & {"int", "str"})


def d_list_build(fn, helpers) -> bool:
    if _has_listcomp(fn):
        return True
    for item in _walk(fn):
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Add):
            if isinstance(item.right, (ast.Name, ast.List, ast.Subscript)):
                return True
    return False


def d_reverse(fn, helpers) -> bool:
    if _call_names(fn) & {"reverse", "reversed"}:
        return True
    return -1 in _slice_steps(fn)


def d_builtin_max(fn, helpers) -> bool:
    return bool(_call_names(fn) & {"max", "min"})


def d_double_loop(fn, helpers) -> bool:
    return _has_nested_loop(fn)


def d_append_row(fn, helpers) -> bool:
    for item in _walk(fn):
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
            if item.func.attr == "append" and item.args:
                return True
    return False


def d_linear_scan(fn, helpers) -> bool:
    return any(isinstance(item, ast.For) for item in _walk(fn)) and (
        _has_break(fn)
        or any(isinstance(item, ast.Return) for item in _walk(fn))
    )


def d_insert(fn, helpers) -> bool:
    return "insert" in _call_names(fn)


def d_modulo(fn, helpers) -> bool:
    return any(
        isinstance(item, ast.BinOp) and isinstance(item.op, ast.Mod)
        for item in _walk(fn)
    )


KNOWLEDGE_DETECTORS = {
    "list_concat": d_list_concat,
    "slice_bounds": d_slice_bounds,
    "slice_reverse": d_slice_reverse,
    "len": d_len,
    "index_arith": d_index_arith,
    "floor_div": d_floor_div,
    "compare": d_compare,
    "if_else": d_if_else,
    "elif_chain": d_elif_chain,
    "loop": d_loop,
    "while_loop": d_while_loop,
    "nested_loop": d_nested_loop,
    "negative_index": d_negative_index,
    "list_mutation": d_list_mutation,
    "del_or_rebuild": d_del_or_rebuild,
    "comprehension": d_comprehension,
    "type_check": d_type_check,
    "helper_function": d_helper_function,
    "counter": d_counter,
    "nested_list": d_nested_list,
    "sort_key": d_sort_key,
    "lambda": d_lambda,
    "range_loop": d_range_loop,
    "int_str_convert": d_int_str_convert,
    "list_build": d_list_build,
    "reverse": d_reverse,
    "builtin_max": d_builtin_max,
    "double_loop": d_double_loop,
    "append_row": d_append_row,
    "linear_scan": d_linear_scan,
    "insert": d_insert,
    "modulo": d_modulo,
}


def detect_points(fn: ast.FunctionDef, helper_names: set[str]) -> list[str]:
    covered = []
    for tag, detector in KNOWLEDGE_DETECTORS.items():
        try:
            if detector(fn, helper_names):
                covered.append(tag)
        except Exception:  # 单条检测器异常不应中断整份评测
            continue
    return covered


_NESTING_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With)


def nesting_depth(node: ast.AST) -> int:
    """分支/循环/异常的嵌套层数。"""
    deepest = 0
    stack = [(node, 0)]
    while stack:
        current, depth = stack.pop()
        deepest = max(deepest, depth)
        for child in ast.iter_child_nodes(current):
            stack.append((child, depth + 1 if isinstance(child, _NESTING_NODES) else depth))
    return deepest


def function_metrics(fn: ast.FunctionDef) -> dict[str, int]:
    lines = (getattr(fn, "end_lineno", None) or fn.lineno) - fn.lineno + 1
    return {
        "lines": max(lines, 1),
        "depth": nesting_depth(fn),
        "statements": sum(1 for item in ast.walk(fn) if isinstance(item, ast.stmt)),
    }
