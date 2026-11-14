# .qbank：题库与批阅包生成器

隐藏目录（Git 跟踪，但默认文件列表看不到）。它**不是运行时模块**，没有任何 Django 代码 import 它；它是一套离线脚本，负责把「题目规格」编译成「题库文档 + 判题数据包」。

一句话：**改题目只改这里的三份 spec，然后跑一次 `build.py`，`data/` 下的 `Python题库.md` 和 `qbank-package/` 会被整体重生成并自检。**

## 文件清单

| 文件 | 内容 | 规模 |
| --- | --- | --- |
| `spec_a.py` | 知识域 1~4 的题目定义（`DOMAINS` + `QUESTIONS`） | 15 题 |
| `spec_b.py` | 知识域 5~8 | 15 题 |
| `spec_c.py` | 知识域 9~12 | 14 题 |
| `build.py` | 生成器：合并 spec → 生成 gold/sample/用例 → 自检 → 写盘 | — |

合计 **44 题 × 10 条用例 = 440 条用例**。

## 一份题目规格长什么样

`QUESTIONS` 是字典列表，每题字段固定：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `id` | `Q1-01` 形式的题号 | Markdown 标题、排序 |
| `f` | 函数名，如 `func0101` | gold/sample/数据文件名 |
| `t` | 题目标题 | Markdown 与 DOCX 题面 |
| `d` / `s` | 难度星级 / 分值 | Markdown 标题、`func_info_list.txt` 第二列 |
| `dom` | 知识域编号 1~12 | 分章、排序 |
| `tags` | 知识点标签列表 | 供 Tag 库校验与练习选题 |
| `desc` / `p` / `r` / `ex` / `hint` | 题面、参数、返回值、示例、易错点 | Markdown 第 2 节 |
| `sig` | 参数列表字符串，如 `n` 或 `r, pi=3.14159` | 拼 `def`、算 `argc` |
| `body` | **函数体**（不含 `def` 行，缩进由脚本加） | 拼 gold |
| `cases` | 10 条**字面量文本**，如 `"0"`、`"2,3"` | 写入 `data/*.txt`、求期望值 |

## build.py 的实现

```74:83:.qbank/build.py
def load_specs():
    domains, questions = {}, []
    for name in ("spec_a.py", "spec_b.py", "spec_c.py"):
```

主流程 `main()` 分五步：

1. **加载并排序**：`importlib.util.spec_from_file_location` 动态导入三份 spec（不依赖包路径），合并 `DOMAINS`、`QUESTIONS`，按 `(dom, id)` 排序。
2. **拼 gold 源码**：`func_source()` 把 `body` 每行加 4 格缩进后接到 `def {f}({sig}):` 之下；`PRELUDE` 里登记的题（`AgeError`、`Rectangle`、`Student`、`Animal`/`Dog`/`Cat`、`Account`）会在前面插入辅助类定义。
3. **拼 sample 桩**：`stub_source()` 保留签名，函数体替换为 `# TODO: 在此实现` + `pass`。
4. **算参数个数**：`argc_of()` 用 `ast.parse` 解析签名，只数位置参数（`posonlyargs + args`），**带默认值的参数也计入**。
5. **求期望值并自检**：`case_args()` 用 `ast.literal_eval` 解析每条用例；`argc == 1` 时整体作为单参数传入，否则按元组顺序展开。随后 `exec` 执行 gold，每题调用两次比对结果，最后 `pack()` 打包返回值。

### 自检具体拦什么

`problems` 列表非空就打印「!! 问题 N 处」并返回退出码 1。注意**产物在自检之前就写盘了**，所以判断成败要看退出码或那行提示，不能只看文件是否生成：

| 检查 | 失败示例 |
| --- | --- |
| 用例字面量合法 | `cases` 里写了 `input()` 或表达式 |
| 参数个数与签名一致 | `sig` 是 `a, b` 但用例只写了 `3` |
| gold 可编译、可执行 | 函数体语法错误、除零、越界 |
| 返回值可被判题器打包 | 返回自定义对象；`pack()` 只认 `none/bool/int/float/str/list/tuple/set/dict` |
| 结果确定 | 两次调用返回不同（例如内部用了 `random`） |

> 注意：`build.py` 的 `pack()` 是判题器 `PACKER_SOURCE` 的等价副本，但**没有 `complex` 分支**，而 `school/portal/question_bank.py` 的 `pack_value()` 支持复数。当前 44 题没有复数返回值，暂不影响；将来加复数题要同步补这里。

## 产物一：`Python题库.md`

写在 `data/Python题库.md`，是**人工可读 + 机器可解析**的双用途文档。结构由 `render_head` / `render_index` / `render_question` / `render_tail` 拼出：

- 头部：题库说明、判题口径（只认 `return`，`print` 被丢弃）、`argc` 与默认参数规则
- 目录索引：按知识域列出 44 题
- 正文：每个知识域一节，每题固定四段——`### 1、题目标题：…`、`**2、题目描述**`、`**3、题目考察的知识点标签**`、`**4、函数框架、标准答案与测试用例**`（含 4.1 `sample` 片段、4.2 `gold` 片段、4.3 十行用例表）
- 附录：批阅包目录结构、`func_info_list.txt` 片段、上传前要补 DOCX 的提醒

**这些固定小标题不能随手改**：`school/portal/question_bank.py` 就是按正则抓它们的。

```34:39:school/portal/question_bank.py
_HEADER_RE = re.compile(
    r'^###\s*1、题目标题：(Q\d+-\d+)\s*(.+?)（(★[☆★]*)｜(\d+)\s*分）\s*$'
)
_SECTION_RE = re.compile(r'^\*\*([234])、')
```

改标题格式、改章节编号、改用例表列数，都会导致弱项练习选题解析失败。

## 产物二：`qbank-package/`

| 文件 | 内容 |
| --- | --- |
| `gold.py` | 44 个标准答案函数 + 辅助类，是合法可执行的文件 |
| `sample.py` | 44 个函数桩，学生起始代码 |
| `func_info_list.txt` | 每行 `函数名<TAB>分值<TAB>data/xxx.txt`，共 44 行 |
| `data/funcXXXX.txt` | 44 个文件，每个 10 行用例实参 |

这是标准「函数式机器批阅包」的四件套。`school/portal/parsers.py` 校验上传包时要求：根目录**恰好一个** `func_info_list.txt`、**一个** `sample*.py`、`gold.py` 存在，外加**一个题目 DOCX**。

⚠️ `data/qbank-package/` 里**没有 DOCX**，所以不能直接压缩上传当作业包；它的用途是格式样张与数据来源，需要时把 `data/Python题库.md` 的题面另存为 docx 补进去。

## 谁在用它

| 产物 | 使用方 | 说明 |
| --- | --- | --- |
| `Python题库.md` | `school/portal/question_bank.py` | 运行时读取（`settings.BASE_DIR / 'data/Python题库.md'`，由 `bank_path()` 拼出），解析后供学生「弱项练习」按 Tag 选题；文件缺失或格式变动会直接影响该功能 |
| `Python题库.md` | `tools/taglib/build.py` | 生成 Tag 库时把它当校验输入：要求文档里出现的**每一个旧标签都能归一**到叶子 tag，做不到就中止 |
| `data/qbank-package/` | 无运行时引用 | 全仓库 Python 代码没有读取它；仅作格式参考、手工试批阅 |
| `.qbank/build.py` | 无代码引用 | 只能手动执行，不在任何启动脚本或 CI 里 |

## 怎么跑

```powershell
cd 仓库根目录
.\.venv\Scripts\python.exe .qbank\build.py
```

Ubuntu 用 `.venv/bin/python .qbank/build.py`。正常输出：

```text
题目 44 道，用例 440 条
Markdown: NNNN 行
自检通过：argc 合规 / 无异常 / 返回值可打包 / 结果确定
```

有问题时先打印「!! 问题 N 处」并逐条列出，再返回退出码 1。**修完 spec 重跑直到通过**，不要手工改 `Python题库.md` 或 `qbank-package/`——下次生成会被覆盖。

## 新增或修改题目

1. 在对应 `spec_a/b/c.py` 的 `QUESTIONS` 追加或修改一条记录。
2. 若该题需要辅助类/前置定义，在 `build.py` 的 `PRELUDE` 里按函数名登记。
3. 跑 `.qbank/build.py`，确认自检通过。
4. `tags` 写得对不对**不由本目录校验**，而是由 `tools/taglib/build.py` 检查能否归一到 Tag 库；新标签先去 Tag 库登记，再来加题。
5. 涉及题型/判题口径变化时，同步更新 `docs/REQUIREMENTS.md` 与根 `README.md` 的代码地图。

## 与 `tools/taglib/` 的区别（容易混）

两个目录都有 `spec_a.py`、`spec_b.py`、`spec_c.py` 和 `build.py`，**同名不同物**：

| | `.qbank/` | `tools/taglib/` |
| --- | --- | --- |
| `spec_*.py` 是什么 | **题目**规格（题面、函数体、用例） | **标签词表**规格（U01~U12 单元、tag 名、别名） |
| `build.py` 产物 | `data/Python题库.md` + `data/qbank-package/` | 根目录 `Python考点Tag库.md` + `tags/tags.json` |
| 依赖关系 | 独立 | 读取 `data/Python题库.md` 做标签归一的校验 |

另外注意：`tools/taglib/build.py` 声明的产物名（`Python考点Tag库.md`、`tags/tags.json`）与仓库现存文件（`Python教学Tag库_v1.0.md`、`qbank-tags-v2.json`、无 `tags/` 目录）不一致，说明该脚本的产物已改名或被手工整理过。运行它前先确认产物落在哪里，避免生成出重复的文档。
