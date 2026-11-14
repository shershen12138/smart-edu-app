# -*- coding: utf-8 -*-
"""由 spec_*.py 生成：题库 Markdown + 批阅包（gold.py / sample.py / func_info_list.txt / data）。

生成后立即自检：
  1) 用与 school/portal/parsers.py 相同的 argc 规则校验每条用例字面量；
  2) 实际调用 gold 函数，确认无异常、返回值可 JSON 打包、结果确定（重复调用一致）。
"""

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = ROOT / "data"
OUT_MD = DATA / "Python题库.md"
PKG = DATA / "qbank-package"

PRELUDE = {
    "func1003": '''class AgeError(Exception):
    """年龄不合法时抛出的自定义异常。"""
''',
    "func1201": '''class Rectangle:
    def __init__(self, w, h):
        self.w = w
        self.h = h

    def area(self):
        return self.w * self.h

    def perimeter(self):
        return 2 * (self.w + self.h)
''',
    "func1202": '''class Student:
    def __init__(self, name, score):
        self.name = name
        self.score = score

    def __str__(self):
        return f"Student({self.name},{self.score})"
''',
    "func1203": '''class Animal:
    def speak(self):
        return "..."


class Dog(Animal):
    def speak(self):
        return "Woof"


class Cat(Animal):
    def speak(self):
        return "Meow"
''',
    "func1204": '''class Account:
    def __init__(self, balance=0):
        self.balance = balance

    def deposit(self, amount):
        self.balance += amount

    def withdraw(self, amount):
        if amount > self.balance:
            return False
        self.balance -= amount
        return True
''',
}


def load_specs():
    domains, questions = {}, []
    for name in ("spec_a.py", "spec_b.py", "spec_c.py"):
        spec = importlib.util.spec_from_file_location(name[:-3], HERE / name)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        domains.update(mod.DOMAINS)
        questions.extend(mod.QUESTIONS)
    questions.sort(key=lambda q: (q["dom"], q["id"]))
    return domains, questions


def func_source(q):
    body = "def {}({}):\n{}".format(
        q["f"], q["sig"], "\n".join("    " + line for line in q["body"].split("\n"))
    )
    prelude = PRELUDE.get(q["f"])
    return (prelude.rstrip("\n") + "\n\n" + body) if prelude else body


def stub_source(q):
    return "def {}({}):\n    # TODO: 在此实现\n    pass".format(q["f"], q["sig"])


def argc_of(q):
    tree = ast.parse("def {}({}): pass".format(q["f"], q["sig"]))
    node = tree.body[0]
    return len(node.args.posonlyargs) + len(node.args.args)


def case_args(text, argc):
    raw = ast.literal_eval(text)
    if argc == 1:
        return (raw,)
    return tuple(raw)


def pack(value):
    """与判题器 PACKER_SOURCE 等价的类型打包，用于确认返回值可被判定。"""
    kind = type(value)
    if value is None:
        return {"type": "none"}
    if kind is bool:
        return {"type": "bool", "value": value}
    if kind is int:
        return {"type": "int", "value": value}
    if kind is float:
        return {"type": "float", "value": value}
    if kind is str:
        return {"type": "str", "value": value}
    if kind in (list, tuple):
        return {"type": kind.__name__, "items": [pack(v) for v in value]}
    if kind is set:
        return {"type": "set", "items": sorted(pack(v) for v in value)}
    if kind is dict:
        return {"type": "dict", "items": [[pack(k), pack(v)] for k, v in value.items()]}
    raise TypeError("unsupported return type: " + kind.__name__)


def main():
    domains, questions = load_specs()

    # ---------- 构建 gold 命名空间并计算期望值 ----------
    gold_parts, sample_parts, manifest = [], [], []
    rows = []
    problems = []

    for q in questions:
        src = func_source(q)
        gold_parts.append(src)
        sample_parts.append(stub_source(q))
        argc = argc_of(q)

        namespace = {"__name__": "qbank_gold"}
        try:
            exec(compile(src, q["f"] + ".py", "exec"), namespace)
        except Exception as exc:  # noqa: BLE001
            problems.append("{}: gold 编译失败 {}".format(q["f"], exc))
            continue
        fn = namespace[q["f"]]

        expected = []
        for idx, text in enumerate(q["cases"], 1):
            try:
                args = case_args(text, argc)
            except Exception as exc:  # noqa: BLE001
                problems.append("{} 用例{}: 字面量非法 {} ({})".format(q["f"], idx, text, exc))
                expected.append(None)
                continue
            if argc != 1 and not (isinstance(ast.literal_eval(text), (tuple, list))
                                  and len(ast.literal_eval(text)) == argc):
                problems.append("{} 用例{}: 参数个数与签名不一致".format(q["f"], idx))
            try:
                first = fn(*args)
                second = fn(*case_args(text, argc))
            except Exception as exc:  # noqa: BLE001
                problems.append("{} 用例{}: 运行异常 {}: {}".format(q["f"], idx, type(exc).__name__, exc))
                expected.append(None)
                continue
            if pack(first) != pack(second):
                problems.append("{} 用例{}: 两次调用结果不一致".format(q["f"], idx))
            expected.append(repr(first))
        rows.append((q, argc, expected))

    # ---------- 写批阅包 ----------
    (PKG / "data").mkdir(parents=True, exist_ok=True)
    for q, argc, expected in rows:
        lines = [c + "\n" for c in q["cases"]]
        (PKG / "data" / (q["f"] + ".txt")).write_text("".join(lines), encoding="utf-8")
        manifest.append("{}\t{}\tdata/{}.txt".format(q["f"], q["s"], q["f"]))

    (PKG / "gold.py").write_text(
        '# -*- coding: utf-8 -*-\n"""标准答案（gold.py）：每个函数即为一道题。"""\n\n'
        + "\n\n".join(gold_parts)
        + '\n\nif __name__ == "__main__":\n    pass\n',
        encoding="utf-8",
    )
    (PKG / "sample.py").write_text(
        '# -*- coding: utf-8 -*-\n"""学生起始代码（sample.py）：保留函数签名，函数体待完成。"""\n\n'
        + "\n\n".join(sample_parts)
        + "\n",
        encoding="utf-8",
    )
    (PKG / "func_info_list.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")

    # ---------- 渲染 Markdown ----------
    md = []
    md.append(render_head(domains, rows))
    md.append(render_index(domains, rows))
    current = None
    for q, argc, expected in rows:
        if q["dom"] != current:
            current = q["dom"]
            md.append("\n---\n\n## 知识域 {}　{}\n".format(current, domains[current]))
            md.append("> " + domain_intro(current) + "\n")
        md.append(render_question(q, argc, expected))
    md.append(render_tail())
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("题目 {} 道，用例 {} 条".format(len(rows), sum(len(q["cases"]) for q, _, _ in rows)))
    print("Markdown: {} 行".format(len(OUT_MD.read_text(encoding='utf-8').splitlines())))
    if problems:
        print("!! 问题 {} 处".format(len(problems)))
        for p in problems:
            print("  -", p)
        return 1
    print("自检通过：argc 合规 / 无异常 / 返回值可打包 / 结果确定")
    return 0


DOMAIN_INTRO = {
    1: "覆盖考点：变量与赋值、`int/float/str/bool` 的区别、显式类型转换、整除 `//` 与取余 `%` 的符号规则、浮点结果精度控制。",
    2: "覆盖考点：算术/比较/位运算符、运算符优先级、进制转换、数值拆位、Python 3 真除法与整除的差别。",
    3: "覆盖考点：字符串不可变性与遍历、`split/join`、切片反转、`upper/lower/capitalize`、`isalpha/isdigit`。",
    4: "覆盖考点：列表索引与切片（含步长、负索引）、原地交换、冒泡排序、去重保序、`max/min/sum/len` 聚合。",
    5: "覆盖考点：字典计数与 `get()`、`items()` 遍历、按键/值/多关键字排序、元组不可变性与解包、集合交并差。",
    6: "覆盖考点：`if/elif/else` 多分支与判断顺序、`for/while` 循环、`break` 提前退出、累加器、区间筛选与边界处理。",
    7: "覆盖考点：`def` 定义与调用、位置参数与默认参数、返回多值、函数拆分与复用、参数校验。",
    8: "覆盖考点：递归三要素（终止条件、递归式、规模缩小）、递归调用树与重复计算、递归改迭代、欧几里得算法。",
    9: "覆盖考点：列表/字典推导式、生成器表达式与惰性求值、`lambda`、`map/filter` 组合、迭代器与容器的区别。",
    10: "覆盖考点：`try/except` 捕获具体异常、`ZeroDivisionError` 与 `ValueError` 的区分、循环内异常处理、`raise` 自定义异常。",
    11: "覆盖考点：二维列表（记录集）的遍历与聚合、按行解析结构化文本、按首次出现顺序保序、多关键字排序与筛选。",
    12: "覆盖考点：`class` 与 `__init__`、实例属性与 `self`、实例方法、`__str__` 魔术方法、继承与方法重写（多态）。",
}


def domain_intro(dom):
    return DOMAIN_INTRO[dom]


def render_head(domains, rows):
    total_cases = sum(len(q["cases"]) for q, _, _ in rows)
    return """# Python 教学辅助系统 · 分层训练题库（函数式判题版）

| 文档属性 | 内容 |
|:--|:--|
| 版本 | v2.0（函数框架版，替换 v1.0 的标准输入输出版） |
| 生成日期 | 2026-11-07 |
| 题目规模 | **{nq} 道函数题 / 12 个知识域 / {nc} 组判题用例** |
| 判题形态 | 调用 `函数名(参数...)`，比对**返回值**（类型严格 + 浮点容差 1e-6） |
| 题目结构 | ①题目标题 ②题目描述 ③知识点标签 ④函数框架 + 标准答案 + 测试用例 |
| 配套产物 | `qbank-package/`：`gold.py`、`sample.py`、`func_info_list.txt`、`data/*.txt` |
| 自检状态 | 全部 {nc} 组用例已逐条调用标准答案验证：无异常、返回值可序列化、结果确定 |

---

## 〇、格式说明（与 `03-列表` 等课码材料完全一致）

### 0.1 一个批阅包里有什么

| 文件 | 作用 | 本文档对应位置 |
|:--|:--|:--|
| `xxx习题说明.docx` | 题面（只有描述，没有答案） | 每题的「2、题目描述」 |
| `sample.py` | 学生起始代码，保留函数签名 | 每题的「4.1 函数框架」 |
| `gold.py` | 标准答案，同名函数给出正确实现 | 每题的「4.2 标准答案」 |
| `func_info_list.txt` | `函数名 分值 用例路径`，一行一题 | 「一、题库总览」的分值列 |
| `data/funcXXXX.txt` | 每题 10 行，每行一条用例的实参 | 每题的「4.3 测试用例」 |

### 0.2 用例文件的三条硬规则

1. **每行一个安全的 Python 字面量**（`ast.literal_eval` 可解析），空行会被跳过。
2. **函数只有 1 个位置参数时**，该行直接写这个参数，例如 `[1,2,3]`、`"abc"`、`42`。
3. **函数有 2 个及以上位置参数时**，该行写成 `a,b`（解析后是元组，长度必须等于参数个数），例如 `7,2`、`[1,2,3],[4,5]`、`"dog",90`。
   ⚠️ **带默认参数也算参数个数**：`def f(r, pi=3.14159)` 的参数个数是 2，用例必须写 `2,3.14159`，不能只写 `2`。

### 0.3 返回值怎么判

- 判分按**类型 + 值**严格比对：`3` 与 `3.0`、`[1,2]` 与 `(1,2)` 都算不同答案；`float` 之间容差 `1e-6`。
- 返回值必须是可 JSON 打包的基本类型：`None/bool/int/float/str/list/tuple/set/dict`（`set`、`dict` 按内容比较，顺序无关）。
- 函数内部的 `print` 会被重定向丢弃，**答题只认 `return`**。
- 需要小数时统一用 `round(x, 2)` 返回 `float`，不要返回字符串。

### 0.4 难度与分值

| 星级 | 含义 | 建议用时 | 分值 |
|:--:|:--|:--:|:--:|
| ★☆☆ | 单一语法点，套模板即可 | 3~5 分钟 | 10 |
| ★★☆ | 组合 2~3 个语法点，或需处理边界 | 6~10 分钟 | 15 |
| ★★★ | 需设计数据结构、处理多分支业务规则 | 12~20 分钟 | 20 |

### 0.5 目录

- 一、题库总览　二、知识域索引　三、细分考点标签索引
- 四、题目正文（12 个知识域，共 {nq} 题）
- 五、附录（批阅包清单、接入方式、自检记录）

---
""".format(nq=len(rows), nc=total_cases)


def render_index(domains, rows):
    out = ["## 一、题库总览\n",
           "| 题号 | 函数名 | 题目标题 | 难度 | 分值 | 所属知识域 |",
           "|:--|:--|:--|:--:|:--:|:--|"]
    for q, argc, _ in rows:
        out.append("| {} | `{}` | {} | {} | {} | {} |".format(
            q["id"], q["f"], q["t"], q["d"], q["s"], domains[q["dom"]]))
    out.append("")

    out.append("## 二、知识域索引\n")
    out.append("| 知识域 | 题量 | 函数名 | 合计分值 |")
    out.append("|:--|:--:|:--|:--:|")
    for dom in sorted(domains):
        ids = [q for q, _, _ in rows if q["dom"] == dom]
        out.append("| {}　{} | {} | {} | {} |".format(
            dom, domains[dom], len(ids), "、".join(q["f"] for q in ids),
            sum(q["s"] for q in ids)))
    out.append("")

    tag_map = {}
    for q, _, _ in rows:
        for t in q["tags"]:
            tag_map.setdefault(t, []).append(q["f"])
    order = ["基础语法", "运算符", "输入输出", "字符串", "列表", "元组", "字典", "集合",
             "控制流程", "循环", "函数", "推导式", "迭代器", "数据结构", "异常处理",
             "文件与数据解析", "面向对象", "算法", "内置函数", "健壮性"]
    grouped = {}
    for t, fs in tag_map.items():
        grouped.setdefault(t.split("/")[0], []).append((t, fs))
    out.append("## 三、细分考点标签索引（薄弱项 → 题目）\n")
    out.append("> 教学系统按学生的薄弱标签反查函数名，即可定位到具体题目与判题用例。\n")
    out.append("| 标签 | 题目数 | 对应函数 |")
    out.append("|:--|:--:|:--|")
    for top in order:
        for t, fs in sorted(grouped.get(top, []), key=lambda x: (-len(x[1]), x[0])):
            out.append("| `{}` | {} | {} |".format(t, len(fs), "、".join(fs)))
    out.append("")
    return "\n".join(out)


def render_question(q, argc, expected):
    lines = []
    lines.append("\n---\n")
    lines.append("### 1、题目标题：{} {}（{}｜{} 分）\n".format(q["id"], q["t"], q["d"], q["s"]))
    lines.append("**2、题目描述**\n")
    lines.append(q["desc"] + "\n")
    lines.append("- 函数签名：`def {}({}):`".format(q["f"], q["sig"]))
    lines.append("- 参数：{}".format(q["p"]))
    lines.append("- 返回值：{}".format(q["r"]))
    lines.append("- 示例：{}\n".format(q["ex"]))
    lines.append("> 易错点：{}\n".format(q["hint"]))
    lines.append("**3、题目考察的知识点标签**\n")
    lines.append(" ".join("`{}`".format(t) for t in q["tags"]) + "\n")
    lines.append("**4、函数框架、标准答案与测试用例**\n")
    lines.append("**4.1 函数框架（`sample.py` 片段，学生起始代码）**\n")
    lines.append("```python\n" + stub_source(q) + "\n```\n")
    lines.append("**4.2 标准答案（`gold.py` 片段）**\n")
    lines.append("```python\n" + func_source(q).rstrip() + "\n```\n")
    lines.append("**4.3 测试用例（10 组，可直接保存为 `data/{}.txt`）**\n".format(q["f"]))
    if argc == 1:
        lines.append("> 本题只有 1 个位置参数，用例行直接写该参数本身。\n")
    else:
        lines.append("> 本题有 {} 个位置参数，用例行写成 `a,b` 形式（解析后是长度为 {} 的元组）。\n".format(argc, argc))
    lines.append("| # | 用例行（字面量） | 期望返回值（`repr`） |")
    lines.append("|:--:|:--|:--|")
    for idx, (text, exp) in enumerate(zip(q["cases"], expected), 1):
        shown = exp if exp is not None else "（生成失败）"
        lines.append("| {} | `{}` | `{}` |".format(idx, text.replace("|", "\\|"), str(shown).replace("|", "\\|")))
    lines.append("")
    return "\n".join(lines)


def render_tail():
    return """---

## 五、附录

### 附录 A　批阅包目录结构

```
qbank-package/
├── gold.py                 # 44 个标准答案函数（含 Rectangle / Student / Account 等辅助类）
├── sample.py               # 44 个函数框架，函数体为 pass
├── func_info_list.txt      # 每行：函数名  分值  用例路径
└── data/
    ├── func0101.txt        # 10 行，每行一条用例实参
    ├── func0102.txt
    └── ...（共 44 个文件）
```

`func_info_list.txt` 片段：

```text
func0101	10	data/func0101.txt
func0102	10	data/func0102.txt
func0301	10	data/func0301.txt
func1204	20	data/func1204.txt
```

> 上传前还需在同级目录放一份题面 `xxx习题说明.docx`（内容即本文档每题的第 2 项，可用 Word 另存为 docx）；批阅包要求「一个 docx + 一个 sample*.py + gold.py + func_info_list.txt」。

### 附录 B　命名规则与扩展

- 函数名统一为 `func{知识域两位}{题号两位}`：`func0301` = 知识域 3 的第 1 题，与 `03-列表` 中的 `func301` 不会重名。
- 新增题目时：在 `.qbank/spec_a.py`（知识域 1~4）、`spec_b.py`（5~8）、`spec_c.py`（9~12）中增加一条记录，然后在项目根目录执行 `python .qbank/build.py` —— 会自动重生成本文档、`qbank-package/` 下的 gold/sample/数据文件与清单，并跑一遍自检。
- 参数个数（`argc`）由 `gold.py` 中函数定义的位置参数个数决定，**改签名就要同步改用例行**，否则批阅包上传时校验会失败。

### 附录 C　两种判题通道的适配

本项目同时存在「函数式批阅包」与「`stdin/stdout` 单文件判题」两条通道。函数式题目若要走 `stdin → stdout` 通道，可用下面的 `main.py` 适配器：

```python
import ast
import sys

from solution import func0101          # 学生提交仍然只写函数


def main():
    line = sys.stdin.read().strip()
    args = ast.literal_eval(line) if line else ()
    if not isinstance(args, tuple):
        args = (args,)
    print(repr(func0101(*args)))


if __name__ == "__main__":
    main()
```

### 附录 D　自检记录

- 逐题用 `ast.parse` 统计位置参数个数，按批阅包规则校验每条用例字面量，**无参数个数不匹配**。
- 逐条调用标准答案：**无异常抛出**，返回值均可按判题器的 `_pack` 规则打包，且同一用例重复调用结果一致（排除随机性）。
- 期望返回值列全部由标准答案实际运行得出（`repr`），不存在手写错值。
"""


if __name__ == "__main__":
    sys.exit(main())
