"""pylint 适配层：把 lint 输出归一化成可定位到行的中文缺陷。

设计要点：
- 只启用与教学质量相关的检查项，避免 default 级别的海量风格告警淹没报告；
- pylint 不可用或文件无法解析时不抛异常，降级为"仅有语法/语义分析"；
- 保留 symbol 便于教师追溯原始规则。
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import models

ENABLED = (
    "E",  # 全部 error（含语法错误）
    "F",  # fatal
    "W0612",  # unused-variable
    "W0611",  # unused-import
    "W0613",  # unused-argument
    "W0622",  # redefined-builtin
    "W0631",  # used-before-assignment
    "W0640",  # cell-var-from-loop
    "W0104",  # pointless-statement
    "W0108",  # unnecessary-lambda
    "W0123",  # eval-used
    "W3301",  # nested-min-max
    "C0123",  # unidiomatic-typecheck
    "C0103",  # invalid-name
    "C0200",  # consider-using-enumerate
)

ADVICE = {
    "E0001": "先修掉语法错误，保证文件能整体解析，其余分析才有意义",
    "E0602": "核对变量名拼写，确认该变量在函数参数或前面的赋值中出现过",
    "E0601": "把变量的赋值语句移到使用之前，或补充默认值",
    "E1101": "确认调用对象的数据类型，避免对不支持该方法的对象调用",
    "E1120": "按题目给定的参数个数调用函数",
    "E1121": "检查调用时是否多传了参数",
    "E1136": "先确认对象是列表或字符串，再进行下标访问",
    "W0612": "删除未使用的中间变量，或真正把它用于后续计算",
    "W0611": "移除非必需的导入语句",
    "W0613": "参数若确实不需要，可改名或在函数中使用它",
    "W0622": "换一个不与内置函数重名的变量名，避免遮蔽 sum、max 等",
    "W0631": "调整语句顺序，保证变量在读取前已经赋值",
    "W0104": "删除没有副作用的表达式，或修改为有意义的语句",
    "C0123": "类型判断可保留题目要求的写法，进阶写法是 isinstance",
    "C0103": "使用有含义的变量名（如 total、index），避免单字母名",
    "C0200": "需要下标时可用 enumerate 让代码更直观",
}

MESSAGES = {
    "E0001": "语法错误",
    "E0401": "导入失败",
    "E0601": "变量在赋值前使用",
    "E0602": "使用了未定义的变量",
    "E0603": "引用了未定义的名称",
    "E1101": "对象没有该属性或方法",
    "E1120": "调用函数时缺少必需参数",
    "E1121": "调用函数时参数过多",
    "E1123": "使用了不存在的关键字参数",
    "E1136": "对不可下标的值使用了下标",
    "E1137": "下标赋值目标不支持",
    "E1306": "f-string 语法错误",
    "E1307": "字符串格式化参数类型不匹配",
    "W0611": "导入后未使用",
    "W0612": "变量赋值后未使用",
    "W0613": "函数参数未被使用",
    "W0622": "变量名覆盖了内置函数",
    "W0631": "变量可能在赋值前被使用",
    "W0640": "闭包在循环变量上延迟取值",
    "W0104": "语句没有产生任何效果",
    "W0108": "lambda 体内多余的函数调用",
    "W0123": "使用了 eval",
    "C0123": "用 type() 比较类型（建议 isinstance，但本题允许 type）",
    "C0103": "命名不符合规范",
    "C0200": "遍历索引可用 enumerate 简化",
}


@dataclass
class LintMessage:
    line: int
    symbol: str
    message: str
    severity: str
    dimension: str
    advice: str


def _dimension(symbol: str) -> str:
    if symbol.startswith(("E", "F")):
        return models.SYNTAX
    return models.STYLE


def _severity(symbol: str) -> str:
    prefix = symbol[:1]
    return {
        "F": "fatal",
        "E": "error",
        "W": "warning",
        "C": "convention",
        "R": "convention",
    }.get(prefix, "warning")


def pylint_available() -> bool:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pylint", "--version"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def run(path: Path) -> tuple[list[LintMessage], str | None]:
    """返回 (消息列表, 不可用原因)。"""
    command = [
        sys.executable,
        "-m",
        "pylint",
        "--output-format=json",
        "--score=n",
        "--reports=n",
        "--persistent=n",
        "--disable=all",
        "--enable=" + ",".join(ENABLED),
        str(path),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"pylint 无法启动：{exc}"

    raw = proc.stdout.decode("utf-8", "replace").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end < start:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        return [], f"pylint 未返回 JSON：{detail[0] if detail else '未知原因'}"

    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return [], "pylint 输出无法解析"

    messages: list[LintMessage] = []
    for item in payload:
        symbol = item.get("symbol", "")
        line = int(item.get("line") or 0)
        if line <= 0:
            continue
        text = MESSAGES.get(symbol) or MESSAGES.get(item.get("message-id", ""), "")
        if not text:
            text = item.get("message", "").strip()
        messages.append(
            LintMessage(
                line=line,
                symbol=symbol,
                message=text,
                severity=_severity(symbol),
                dimension=_dimension(symbol),
                advice=ADVICE.get(item.get("message-id", ""), ADVICE.get(symbol, "按提示修正该处写法")),
            )
        )
    return messages, None
