"""题库语义规则：lint 查不出、但与题意直接冲突的写法。

每条规则只针对一道题，返回 (块内行号, 缺陷说明, 修改建议, 维度)。
规则给出的是"静态可疑点"，报告中使用"疑似/应核对"的措辞，不把静态推断
描述成运行结果。修改建议只描述做法，不提供改好的代码。
"""

from __future__ import annotations

import ast

from . import models

Finding = tuple[int, str, str, str]


def _dump(node: ast.AST | None) -> str:
    return ast.dump(node) if node is not None else ""


def _const(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
    ):
        return -node.operand.value
    return None


def _last_return(body: list[ast.stmt]) -> ast.Return | None:
    for stmt in reversed(body):
        if isinstance(stmt, ast.Return):
            return stmt
    return None


def _is_plus_one(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Add)
        and _const(node.right) == 1
    )


def func301_slice_bounds(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Slice):
            lower, upper = _const(item.slice.lower), _const(item.slice.upper)
            if lower is None and upper is None:
                continue
            if (lower, upper) == (7, 15):
                continue
            findings.append(
                (
                    item.lineno,
                    f"切片边界 [{lower}:{upper}] 与“第 8~15 个元素”不一致："
                    "题目从 1 开始计数，换算成 0 起始下标应为 [7:15]",
                    "按“起始下标 = 序号 - 1、切片右端不包含”重新计算两个边界，"
                    "再用题目给的样例输入核对结果长度",
                    models.LOGIC,
                )
            )
    return findings


def func302_median(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if isinstance(item, ast.Subscript) and _is_plus_one(item.slice):
            findings.append(
                (
                    item.lineno,
                    "偶数长度时中间右下标为 len//2，再 +1 等于 len，访问会越界",
                    "偶数个元素时两个中间下标分别是 len//2-1 与 len//2，"
                    "不要越过 len-1",
                    models.BOUNDARY,
                )
            )
    for item in ast.walk(fn):
        if not isinstance(item, ast.If) or not item.orelse:
            continue
        test = item.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        left, right = test.left, test.comparators[0]
        if not (isinstance(left, ast.Subscript) and isinstance(right, ast.Subscript)):
            continue
        then_ret = _last_return(item.body)
        else_ret = _last_return(item.orelse)
        if not (then_ret and else_ret):
            continue
        op = test.ops[0]
        then_is_left = _dump(then_ret.value) == _dump(left)
        left_greater = isinstance(op, (ast.Gt, ast.GtE))
        left_less = isinstance(op, (ast.Lt, ast.LtE))
        if (left_greater and then_is_left) or (left_less and not then_is_left):
            findings.append(
                (
                    item.lineno,
                    "偶数个元素时应取中间两数中较小的一个，该分支返回的却是较大者",
                    "把比较方向反过来，或在两个中间元素之间用 min 取较小值",
                    models.LOGIC,
                )
            )
    return findings


def func303_palindrome(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if not isinstance(item, ast.If) or not item.orelse:
            continue
        test = item.test
        if not isinstance(test, ast.Compare):
            continue
        is_palindrome_test = any(
            isinstance(node, ast.Slice) and _const(node.step) == -1
            for node in ast.walk(test)
        )
        if not is_palindrome_test:
            continue
        then_ret = _last_return(item.body)
        else_ret = _last_return(item.orelse)
        if then_ret and _const(then_ret.value) == 0:
            findings.append(
                (
                    then_ret.lineno,
                    "回文判断为真时应返回 1，当前分支返回 0，返回值语义与题目相反",
                    "交换两个分支的返回常量，保持“是回文→1、不是→0”",
                    models.LOGIC,
                )
            )
        elif else_ret and _const(else_ret.value) == 1:
            findings.append(
                (
                    else_ret.lineno,
                    "非回文时应返回 0，当前分支返回 1，返回值语义与题目相反",
                    "交换两个分支的返回常量，保持“是回文→1、不是→0”",
                    models.LOGIC,
                )
            )
    return findings


def func305_int_filter(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if not isinstance(item, ast.Compare) or len(item.ops) != 1:
            continue
        if not isinstance(item.ops[0], ast.Eq):
            continue
        left, right = item.left, item.comparators[0]
        checked = None
        target = None
        for first, second in ((left, right), (right, left)):
            if isinstance(first, ast.Call) and isinstance(first.func, ast.Name):
                if first.func.id == "type":
                    checked, target = first, second
                elif first.func.id == "isinstance" and len(first.args) == 2:
                    checked, target = first, first.args[1]
        if checked is None:
            continue
        if isinstance(target, ast.Name) and target.id == "str":
            findings.append(
                (
                    item.lineno,
                    "题目要求删除“不是整数”的元素，这里判断的是 str，筛选条件与题意相反",
                    "把类型判断改为 int（或 isinstance(..., int)），让它筛选出整数",
                    models.LOGIC,
                )
            )
    return findings


def func308_return_codes(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if not isinstance(item, ast.If):
            continue
        test = item.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        ret = _last_return(item.body)
        code = _const(ret.value) if ret else None
        if code is None:
            continue
        op = test.ops[0]
        if isinstance(op, ast.Gt) and code == 3:
            findings.append(
                (
                    ret.lineno,
                    "偶数个数大于奇数个数应返回 2，当前返回 3",
                    "按题目给定的返回码对照表重排三个分支的返回值",
                    models.LOGIC,
                )
            )
        elif isinstance(op, ast.Lt) and code == 2:
            findings.append(
                (
                    ret.lineno,
                    "偶数个数小于奇数个数应返回 3，当前返回 2",
                    "按题目给定的返回码对照表重排三个分支的返回值",
                    models.LOGIC,
                )
            )
        elif isinstance(op, ast.Eq) and code != 1:
            findings.append(
                (
                    ret.lineno,
                    "奇偶个数相等应返回 1，当前返回码不符",
                    "把相等分支的返回码改为 1",
                    models.LOGIC,
                )
            )
    return findings


def func309_sort_key(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Attribute):
            continue
        if item.func.attr not in {"sort", "sorted"}:
            continue
        reverse = any(
            kw.arg == "reverse"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in item.keywords
        )
        key = next((kw.value for kw in item.keywords if kw.arg == "key"), None)
        if not reverse or not isinstance(key, ast.Lambda):
            continue
        body = key.body
        if not isinstance(body, ast.Tuple) or len(body.elts) < 2:
            continue
        second = body.elts[1]
        if not isinstance(second, ast.UnaryOp):
            findings.append(
                (
                    item.lineno,
                    "总分相同时要求按学号升序，但 reverse=True 会让第二个排序键整体降序，"
                    "疑似排序键方向不对",
                    "对第二个排序键（学号）取负，或改用两次稳定排序",
                    models.LOGIC,
                )
            )
    return findings


def func310_prime_range(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Name):
            continue
        if item.func.id != "range" or len(item.args) != 2:
            continue
        stop = item.args[1]
        if _is_plus_one(stop):
            continue
        if isinstance(stop, ast.Name):
            findings.append(
                (
                    item.lineno,
                    "range(2, N) 的上界不包含 N，题目要求 N 以内包含 N",
                    "把 range 的上界写成 N+1，保证 N 本身参与判断",
                    models.BOUNDARY,
                )
            )
        elif isinstance(stop, ast.BinOp) and isinstance(stop.op, ast.Sub):
            findings.append(
                (
                    item.lineno,
                    "range 上界被减去 1，会漏掉 N 本身",
                    "上界改为 N+1，不要额外减 1",
                    models.BOUNDARY,
                )
            )
    return findings


def func311_digit_reverse(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    has_reverse = False
    for item in ast.walk(fn):
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
            if item.func.attr == "reverse":
                has_reverse = True
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
            if item.func.id == "reversed":
                has_reverse = True
        if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Slice):
            if _const(item.slice.step) == -1:
                has_reverse = True
        if isinstance(item, (ast.ListComp, ast.GeneratorExp)):
            for generator in item.generators:
                if isinstance(generator.iter, ast.Subscript):
                    findings.append(
                        (
                            generator.iter.lineno,
                            "直接遍历列表元素（整数）会抛 TypeError：整数不可迭代",
                            "先把当前元素转成字符串，再逐字符取数字",
                            models.BOUNDARY,
                        )
                    )
    if not has_reverse:
        findings.append(
            (
                fn.lineno,
                "逐位拆分后没有反转，拼接结果是高位到低位，题目要求从低位到高位",
                "对每位数字组成的子列表做一次反转，再拼进结果",
                models.LOGIC,
            )
        )
    return findings


def func312_integer_average(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if not isinstance(item, ast.BinOp) or not isinstance(item.op, ast.Div):
            continue
        if _const(item.right) == 2 or _const(item.left) == 2:
            findings.append(
                (
                    item.lineno,
                    "两数平均应使用整除 //，/ 会得到浮点数，后续结果类型与题目要求不符",
                    "把 / 改成 //，保持列表元素仍是整数",
                    models.LOGIC,
                )
            )
    return findings


def func313_transpose(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
            if item.func.attr == "extend":
                findings.append(
                    (
                        item.lineno,
                        "转置需要把每一列作为子列表 append 进结果，extend 会把列展开成一维列表",
                        "把整列作为一个元素追加到结果列表，而不是展开追加",
                        models.LOGIC,
                    )
                )
    return findings


def func315_insert_direction(fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for item in ast.walk(fn):
        if not isinstance(item, ast.If):
            continue
        test = item.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        left, right = test.left, test.comparators[0]
        if not isinstance(right, ast.Subscript):
            continue
        if isinstance(test.ops[0], (ast.Gt, ast.GtE)) and isinstance(left, ast.Name):
            findings.append(
                (
                    item.lineno,
                    "升序列表应在 Num < A[i] 时插入，当前用 Num > A[i]，插入位置方向相反",
                    "把比较方向改为待插入值小于当前元素时插入",
                    models.LOGIC,
                )
            )
    return findings


RULES = {
    "func301": (func301_slice_bounds,),
    "func302": (func302_median,),
    "func303": (func303_palindrome,),
    "func305": (func305_int_filter,),
    "func308": (func308_return_codes,),
    "func309": (func309_sort_key,),
    "func310": (func310_prime_range,),
    "func311": (func311_digit_reverse,),
    "func312": (func312_integer_average,),
    "func313": (func313_transpose,),
    "func315": (func315_insert_direction,),
}


def evaluate_task(task_id: str, fn: ast.FunctionDef, helpers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES.get(task_id, ()):
        try:
            findings.extend(rule(fn, helpers))
        except Exception:  # 单条规则异常不影响其他规则
            continue
    return findings


def common_rules(fn: ast.FunctionDef) -> list[Finding]:
    """与具体题目无关的规则：空实现、无返回值。"""
    body = [stmt for stmt in fn.body if not isinstance(stmt, ast.Expr)]
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return [
            (
                fn.lineno,
                "函数体只有 pass，尚未实现",
                "按题目要求补全计算过程并返回结果",
                models.KNOWLEDGE,
            )
        ]
    has_return = any(
        isinstance(item, ast.Return) and item.value is not None for item in ast.walk(fn)
    )
    if not has_return:
        return [
            (
                fn.lineno,
                "函数没有返回计算结果，题目要求 return 结果",
                "把最终计算结果用 return 返回，而不是只在函数内部打印",
                models.KNOWLEDGE,
            )
        ]
    return []
