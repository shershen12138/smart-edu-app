# 学生代码质量评测智能体

面向教学辅助系统的静态评测工具：用 **LangGraph 编排 + pylint + AST 知识点检测 + 题库语义规则** 分析学生提交的 `.py`，
按评分量表给每个学生打分，输出 **Markdown 缺陷表** 与 **个人代码完成度雷达图**。

工具独立运行，不依赖 Django，不读写数据库，不改动学生文件。

## 输出什么

- `reports/<课程>/评测报告.md`：每个学生一张表，表头固定四项——题目编号、作业考察的知识点、缺陷及所在代码行、修改建议。
- `reports/<课程>/radar/studentXX.png`：每个学生一张雷达图，维度即评分量表的各项。
- 命令行摘要：量表来源、学生人数、每人总分与等级。

当前已配置题库：`03-列表`（func301～func315，15 题）、`04-分支结构`（func401～func411，11 题）。

## 目录结构

```text
tools/code_quality_agent/
├── __main__.py          命令行入口
├── config.py            路径与课程配置
├── curriculum.py        题库规格：每题的知识点标签
├── static_analysis.py   函数切块、AST 解析、知识点检测器
├── rules.py             题意规则（越界、返回码、排序键、整除等）
├── lint.py              pylint 适配与中文消息映射
├── rubric.py            量表解析、维度打分、加权总分
├── charts.py            雷达图渲染
├── report.py            Markdown 报告
├── pipeline.py          入口：发现文件 → 调用评测图 → 组装结果
├── agent_graph.py       LangGraph 状态图：节点编排与条件路由
├── stages.py            阶段函数：prepare / lint / tasks / notes / score
├── service.py           Django 适配接口（内存源码进、报告出）
└── models.py            数据契约
```

## 技术架构

### 分层与调用链

```text
调用方
├── CLI：__main__.py → pipeline.run(course, rubric)
└── Django：school/portal/quality_service.py
        → service.analyze / radar_png / markdown / payload
                │
                ▼
编排层 pipeline → agent_graph（LangGraph 状态图）
  prepare   split_functions 按函数切块，逐题独立解析；parse_whole 判断整文件可否解析
     ├─(可解析)→ lint     pylint 子进程 → 中文消息 → 维度归类
     └─(不可解析)→ 跳过 pylint，直接进入 tasks
  tasks     detect_points 考点命中 + rules 题意规则 + 把 lint 消息归到所属函数
  notes     汇总规范提示与扣分计数（命名问题按一类计）
  score     rubric.score_student 维度扣分 + weighted_total 加权总分
                │
                ▼
models.py 数据契约（TaskSpec / TaskResult / Issue / Dimension / StudentAnalysis）
                │
                ▼
输出层
├── charts.render        PNG 雷达图（轴 = 量表维度，值 = 该维度得分）
├── service.markdown     四列 Markdown 表格（网页下载）
├── service.payload      结构化明细（网页渲染）
└── report.build         CLI 批量报告（图片用相对路径）
```

`tools/` 不依赖 Django；`school/portal/quality_service.py` 是唯一的适配层，负责把数据库里的题目、源码、量表翻译成 `service` 的入参，再把结果写入私有存储与 `QualityReport`。

### Agent 层：LangGraph 状态图

评测不再是一条顺序函数调用，而是 `StateGraph` 的五个节点加一条条件边：

| 节点 | 读取 | 产出 |
| --- | --- | --- |
| `prepare` | 源码、题目规格 | 函数块、整文件 AST、解析错误 |
| `lint` | 临时文件路径 | pylint 消息（整文件不可解析时跳过） |
| `tasks` | 函数块、lint 消息 | 逐题 `TaskResult`：考点命中、规则缺陷、结构指标 |
| `notes` | 全部消息 | 规范提示文案、扣分计数 |
| `score` | 结果与维度 | 各维度得分、加权总分 |

条件边 `_route_after_prepare` 决定是否执行 `lint`：整份文件语法错误时行号不可信，直接进入 `tasks`，仍会为每题生成“语法错误”缺陷，而不是整体失败。

状态由 `stages.ReviewState`（`TypedDict`）描述，节点只返回自己改动的字段，互不覆盖。图编译一次后缓存在模块级（`compiled_graph()`），进程内跨请求复用，不持有任何学生数据。

LLM 是可选扩展点：图本身不调用大模型，所有结论来自 AST 与 pylint。要接入时在 `score` 之后插入一个节点，读取 `ReviewState` 并调用 LangChain 的 `BaseChatModel`，把生成的学习建议写入 `style_notes`；未配置模型时该节点不注册，报告内容与现在完全一致。

依赖 `langgraph`（`requirements.txt` 与 `requirements.lock.txt` 均已列出）。导入 langgraph 时会向 stderr 打印一条与 `allowed_objects` 默认值有关的 `LangChainPendingDeprecationWarning`，它不受 warnings 过滤器控制，属第三方一次性输出，不影响结果。

### 模块职责

| 模块 | 职责 | 关键接口 |
| --- | --- | --- |
| `config.py` | 路径常量、CLI 课程表、`CourseContext` | `build_context`、`COURSES` |
| `curriculum.py` | 题库规格：每题的考点标签与题干摘要 | `COURSE_SPECS`、`POINT_LABELS`、`specs_for` |
| `static_analysis.py` | 函数切块、整文件解析、结构指标、考点检测器 | `split_functions`、`parse_whole`、`detect_points`、`function_metrics` |
| `lint.py` | pylint 适配，只启用与教学相关的消息，英文消息映射为中文建议 | `run`、`pylint_available` |
| `rules.py` | 题意规则：静态推断与题目要求冲突的写法 | `evaluate_task`、`common_rules`、`RULES` |
| `rubric.py` | 量表解析（Markdown 表格 / 列表写法）与维度打分 | `dimensions_from_text`、`load_rubric`、`score_student`、`weighted_total` |
| `pipeline.py` | 入口：文件发现、临时落盘、组装 `StudentAnalysis` / `Evaluation` | `analyze_text`、`run` |
| `agent_graph.py` | LangGraph 状态图：节点注册、条件路由、编译缓存 | `build_graph`、`compiled_graph`、`invoke`、`node_names` |
| `stages.py` | 评测各阶段实现，输入输出都是图状态 | `prepare`、`run_lint`、`build_tasks`、`collect_notes`、`score` |
| `charts.py` | matplotlib 极坐标雷达图 | `render` |
| `report.py` | CLI 批量 Markdown 报告 | `build` |
| `service.py` | Django 适配接口：内存源码进、报告出 | `build_specs`、`analyze`、`radar_png`、`markdown`、`payload` |
| `models.py` | 不可变数据契约 | `TaskSpec`、`TaskResult`、`Issue`、`Dimension` |

### 数据契约

| 类型 | 作用 | 关键字段 |
| --- | --- | --- |
| `TaskSpec` | 一道题的期望 | `task_id`（函数名）、`title`、`points`（考点标签元组） |
| `TaskResult` | 一道题的实际结果 | `parsed`、`covered` / `missing`、`issues` |
| `Issue` | 一条可定位缺陷 | `line`、`message`、`advice`、`dimension`、`severity`、`source` |
| `Dimension` | 评分维度 | `key`、`label`、`weight`（0~1） |
| `StudentAnalysis` | 一名学生的汇总 | `results`、`scores`、`total`、`metrics`、`style_notes` |

`severity` 取 `fatal / error / warning / convention`，`source` 取 `ast / rule / pylint / syntax`。报告里的缺陷表按严重度排序，同一句提示合并行号，单题最多列 8 条。

### 评分链路

1. 知识点覆盖 = 命中考点数 ÷ 题目考点数 × 100；整份文件无法解析时再乘 0.5。
2. 语法与静态缺陷 = 100 − 40 × error 数 − 5 × 语法警告数。
3. 边界与健壮性、题意一致性 = 100 − 25 × 对应维度缺陷数。
4. 代码规范 = 100 − 3 × 规范问题数；文件不可解析时封顶 50。可读性当前复用同一基数。
5. 代码结构 = 100 − 10 × 超长函数 − 10 × 深嵌套 − 5 × 语句过密。
6. 维度权重按合计归一化（`round(weight / total, 4)`）；总分 = Σ 维度得分 × 权重，等级 A≥90、B≥80、C≥70、D≥60。

评分只认内置维度 key（`knowledge / syntax / boundary / logic / style / structure / readability`）。量表里出现其他 key 时该维度恒为 0 分，不会静默改名。

### 幂等与缓存（Django 侧）

`QualityReport` 与一次提交一对一。复用的条件是源码摘要和量表/考点指纹都没变：

- `source_sha256`：源码内容；
- `payload.rubric_signature`：量表维度（key、label、weight）与本题考点标签拼接后的指纹。

任一变化就重新生成，旧的 Markdown / PNG 交给 `PrivateFileCleanup` 延迟删除。因此教师改了评分标准、或题库补了某门课的考点配置，学生下次打开报告会自动更新。

### 扩展点

- **新增课程**：`curriculum.COURSE_SPECS` 增加一组 `TaskSpec`；新考点标签要在 `POINT_LABELS` 与 `static_analysis.KNOWLEDGE_DETECTORS` 同时登记；CLI 还要在 `config.COURSES` 加课程目录与量表文件名。
- **新增题意规则**：`rules.py` 写函数返回 `(行号, 缺陷, 建议, 维度)`，注册进 `RULES`。
- **新增评分维度**：`models.DIMENSION_LABELS` 加 key 与中文名，并在 `rubric.score_student` 的 `raw` 映射里给出评分口径。
- **替换输出**：`service.payload` 是网页渲染的唯一数据源，字段增减不影响打分。
- **新增评测步骤**：在 `stages.py` 写一个 `(state) -> dict` 的函数，在 `agent_graph.build_graph` 注册节点并接边，同时更新 `NODE_NAMES`；不需要改 `pipeline`。

### 设计取舍

- **只做静态分析**：不执行学生代码，缺陷一律表述为“疑似/应核对”，不声称运行通过或失败；需要运行期验证时复用 `school/judge.py` 的受限容器。
- **用状态图而非顺序调用**：`lint` 要按“整文件是否可解析”分支，状态图把这一判断显式化成条件边；各阶段可单独测试，后续插入 LLM 节点也不必改评分逻辑。
- **逐题切块**：单个函数语法错误不会拖垮同文件其他题的分析，只有整文件不可解析时才整体降级。
- **考点用 AST 检测器**：比正则匹配跨行写法更稳，也避免把字符串或注释里的同名文本当成实现。
- **考点标注依赖参考实现**：同一道题有多种写法，标签只保证题库 `gold.py` 的写法能命中；学生用了等价但结构不同的写法，可能出现误判的 ✗，这是当前的主要局限。
- **未登记课程不臆造考点**：题目函数名不在 `COURSE_SPECS` 时 `points` 为空，报告显示“未配置知识点模板（仅通用检查）”，只做 lint 与通用规则。

## 输入数据约定

```text
data/
├── 03-列表/             学生代码，文件名即学生名（学生01.py）
├── 04-分支结构/         同结构，题库函数名为 func4xx
├── 03评分量表.md        评分量表（可为空，见“替换评分量表”）
exercise requirements/
├── 03-列表/
│   └── 03-列表/         题库包：func_info_list.txt、*习题说明.docx、gold.py、data/func3xx.txt
└── 04-分支结构/
    └── 04-分支结构/     题库包，func_info_list.txt、*习题说明.docx、gold.py、data/func4xx.txt
```

学生文件名去掉 `.py` 即为报告中的学生名；作业编号沿用题库函数名（`func301` 表示第 3 章第 1 题）。

## 环境准备

需要 Python 3.12 或更高版本，以及两个第三方库：`pylint`（静态检查）与 `matplotlib`（雷达图）。

已按项目约定使用虚拟环境时：

```powershell
# Windows
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
# Ubuntu
.venv/bin/python -m pip install -r requirements-dev.txt
```

没有虚拟环境、只想跑这个工具时：

```powershell
python -m pip install pylint matplotlib
```

验证安装：

```powershell
python -m pylint --version
python -c "import matplotlib; print(matplotlib.__version__)"
```

## 启动

在仓库根目录执行（注意不是工具目录内）：

```powershell
# Windows
.\.venv\Scripts\python.exe -m tools.code_quality_agent --course 03-列表
```

```bash
# Ubuntu
.venv/bin/python -m tools.code_quality_agent --course 03-列表
```

没有虚拟环境时把解释器换成 `python`：

```powershell
python -m tools.code_quality_agent --course 03-列表
```

预期输出：

```text
课程：03-列表
量表：03评分量表.md 为空（0 字节），使用内置默认量表
学生：5 人
  学生01: 57.6 分（E）
  学生02: 79.1 分（C）
  学生03: 87.3 分（B）
  学生04: 72.3 分（C）
  学生05: 52.2 分（E）
报告：D:\...\reports\03-列表\评测报告.md
图表：D:\...\reports\03-列表\radar
```

打开 `reports/03-列表/评测报告.md` 预览即可（VS Code 用 `Ctrl+Shift+V`）。报告里的图片是相对路径，需保持 `radar/` 与报告同目录。

### 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--course` | `03-列表` | 课程目录名，需同时在 `config.COURSES` 与 `curriculum.COURSE_SPECS` 中配置 |
| `--rubric` | `data/<课程>评分量表.md` | 指定另一份量表文件 |
| `--out` | `reports/<课程>` | 报告与图表输出目录 |

示例：

```powershell
python -m tools.code_quality_agent --course 03-列表 --rubric "D:\量表\期中量表.md" --out "D:\评阅结果\第3章"
```

## 评分口径

| 维度 | 默认权重 | 判定方式 |
| --- | --- | --- |
| 知识点覆盖 | 30% | 题目要求的知识点命中率（AST 检测）；文件整体无法解析时按 50% 计 |
| 语法与静态缺陷 | 20% | 每条语法错误或 lint error 扣 40 分 |
| 边界与健壮性 | 15% | 越界、range 上界、整数不可迭代等，每条扣 25 分 |
| 题意一致性 | 25% | 返回码、比较方向、类型过滤、排序键等与题意冲突，每条扣 25 分 |
| 代码规范 | 10% | pylint 规范提示；命名问题按一类计，避免一次扣光 |

总分 = 各维度得分 × 权重之和，等级 A≥90、B≥80、C≥70、D≥60、E<60。

量表若包含「代码结构」或「可读性」，同样参与加权：结构看函数长度、嵌套深度与语句数量，可读性当前复用代码规范的评分基数。

## 替换评分量表

`data/03评分量表.md` 目前是空文件，工具会自动使用上面的内置量表并在报告开头注明。
填入真实量表后重跑即可生效，支持两种写法。

Markdown 表格（推荐，可直接粘贴 5 分制量表）：

```markdown
## 二、5 分制量表

| 维度 | 权重 | 5 分 | 4 分 | 3 分 | 2 分 | 1 分 |
| --- | --- | --- | --- | --- | --- | --- |
| 知识点掌握 | 40 | 全部命中 | 命中多数 | 命中一半 | 命中少数 | 未命中 |
| 语法规范 | 20 | 无缺陷 | 少量提示 | 有可修复缺陷 | 有 error | 无法解析 |
| 边界健壮 | 20 | 覆盖完整 | 基本覆盖 | 偶有遗漏 | 多处遗漏 | 未处理 |
| 逻辑正确 | 15 | 完全一致 | 基本一致 | 个别偏差 | 明显偏差 | 与题意冲突 |
| 代码规范 | 5 | 命名清晰 | 略有不足 | 一般 | 较乱 | 难以阅读 |
```

只有标题含“量表”的小节内的表格才会被解析，所以同一份文件里的知识点表不会混入评分维度。
简化的三列表格（`维度 | 权重 | 说明`）同样可用。

列表写法：

```markdown
- 知识点掌握：40%
- 语法规范：20%
- 边界健壮：20%
- 逻辑正确：15%
- 代码规范：5%
```

维度名通过关键词映射到内置维度（知识点、语法、边界、逻辑、规范、结构、可读性），权重会自动归一化。
识别不到任何维度时退回内置量表，并在报告里说明原因。

## 扩展新课程（05-循环结构）

1. 在 `curriculum.py` 增加一组 `TaskSpec`，为每题声明 `task_id`、题干摘要与所需知识点标签；新标签需在 `POINT_LABELS` 和 `static_analysis.KNOWLEDGE_DETECTORS` 中同时登记。
2. 在 `rules.py` 为有明确题意陷阱的题注册规则函数（返回 `(行号, 缺陷, 建议, 维度)`），并在 `RULES` 中登记。
3. 在 `config.COURSES` 增加课程与量表文件名。
4. 重新运行命令即可，报告与图表流程不用改。

## 限制与安全边界

- **不执行学生代码**。评测完全静态，缺陷是"静态推断"，报告中使用"疑似/应核对"措辞，不声称运行通过或失败。
- 若后续接入运行期验证，应复用 `school/judge.py` 的受限容器（`--network none`、只读根、降权用户），不要在主机直接 `exec` 学生代码。
- 语法错误的函数不会影响同文件其他函数的分析；但整份文件无法编译时，知识点按 50% 计、规范维度封顶 50 分，并在报告中标注。
- 规则针对题库设计，不能自动发现题意之外的业务逻辑错误；未注册规则的题只做 lint 与知识点检测。

## 常见问题

**提示 `pylint 不可用`**：当前解释器没装 pylint。用同一个解释器安装，或确认命令里的 `python` 是预期的那一个。

**报告里没有 lint 结果**：学生文件整体无法解析时 pylint 会跳过，报告会写明"pylint 已跳过"。

**雷达图中文变方框**：系统缺少中文字体。Windows 装 Microsoft YaHei、Ubuntu 装 `fonts-noto-cjk` 后重跑。

**想只跑某个学生**：把该学生的 `.py` 复制到临时目录，用 `--out` 指定输出，或先移出其他文件再运行。

**输出目录不存在**：工具会自动创建 `reports/<课程>/radar/`。
