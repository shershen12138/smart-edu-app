# 学生代码质量评测智能体

面向教学辅助系统的静态评测工具：用 **LangGraph 编排 + pylint + AST 知识点检测 + 题库语义规则** 分析学生提交的 `.py`，
按作业自己的评分标准打分，输出 **逐题缺陷明细** 与 **个人主能力雷达图**。

工具独立运行，不依赖 Django，不读写数据库，不改动学生文件；网页端由 `school/portal/quality_service.py` 调用。

## 输出什么

每次生成报告产出三件东西，写入私有存储并在页面上展示：

- **Markdown 报告**：逐题四列——题目编号、作业考察的知识点、缺陷及所在代码行、修改建议。
- **雷达图 PNG**：轴为评分标准归纳出的六个主能力，值取所绑定评分维度的得分。
- **结构化 payload**：总分、主能力得分、逐题明细、pylint 规范提示，是网页渲染的唯一数据源。

题库规格在 `curriculum.py`；未登记的题目只做 lint 与通用规则，不臆造考点。

## 目录结构

```text
tools/code_quality_agent/
├── curriculum.py        题库规格：每题的知识点标签
├── specs.py             考点解析：题库规格 → 数据库确认 → 参考答案 → 题面 → 兜底
├── static_analysis.py   函数切块、AST 解析、知识点检测器
├── rules.py             题意规则（越界、返回码、排序键、整除等）
├── lint.py              pylint 适配与中文消息映射
├── rubric.py            量表解析、维度打分、加权总分
├── charts.py            雷达图渲染
├── pipeline.py          入口：临时落盘 → 调用评测图 → 组装结果
├── agent_graph.py       LangGraph 状态图：节点编排与条件路由
├── stages.py            阶段函数：resolve_specs / prepare / lint / tasks / notes / score
├── service.py           Django 适配接口（内存源码进、报告出）
└── models.py            数据契约
```

## 技术架构

### 分层与调用链

```text
调用方：school/portal/quality_service.py
        → service.build_specs / analyze / radar_png / markdown / payload
                │
                ▼
编排层 pipeline → agent_graph（LangGraph 状态图）
  resolve_specs  已有 specs 时跳过；否则按数据库题目 → 参考答案 → 题面 → 兜底推断考点
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
├── charts.render        PNG 雷达图（轴 = 主能力，值 = 所绑定维度得分）
├── service.markdown     Markdown 表格（网页下载）
└── service.payload      结构化明细（网页渲染）
```

`tools/` 不依赖 Django；`school/portal/quality_service.py` 是唯一的适配层，负责把数据库里的题目、源码、评分标准翻译成 `service` 的入参，再把结果写入私有存储与 `QualityReport`。

### Agent 层：LangGraph 状态图

评测是 `StateGraph` 的六个节点加一条条件边：

| 节点 | 读取 | 产出 |
| --- | --- | --- |
| `resolve_specs` | 题目、题面、参考答案 | 每题的考点标签（已有 `specs` 时直接跳过） |
| `prepare` | 源码、题目规格 | 函数块、整文件 AST、解析错误 |
| `lint` | 临时文件路径 | pylint 消息（整文件不可解析时跳过） |
| `tasks` | 函数块、lint 消息 | 逐题 `TaskResult`：考点命中、规则缺陷、结构指标 |
| `notes` | 全部消息 | 规范提示文案、扣分计数 |
| `score` | 结果与维度 | 各维度得分、加权总分 |

条件边 `_route_after_prepare` 决定是否执行 `lint`：整份文件语法错误时行号不可信，直接进入 `tasks`，仍会为每题生成“语法错误”缺陷，而不是整体失败。

状态由 `stages.ReviewState`（`TypedDict`）描述，节点只返回自己改动的字段，互不覆盖。图编译一次后缓存在模块级（`compiled_graph()`），进程内跨请求复用，不持有任何学生数据。

节点名不能与状态字段重名（例如状态里已有 `specs`，节点就叫 `resolve_specs`），否则新版 langgraph 会拒绝构图。

LLM 是可选扩展点：图本身不调用大模型，所有结论来自 AST 与 pylint。评分标准与主能力的归纳由 `school/portal/rubric_agent.py` 在教师触发时调用模型，不在评测图内。

依赖 `langgraph`（`requirements/base.in` 与锁定的 `requirements/base.txt` 均已列出）。导入 langgraph 时会向 stderr 打印一条与 `allowed_objects` 默认值有关的 `LangChainPendingDeprecationWarning`，它不受 warnings 过滤器控制，属第三方一次性输出，不影响结果。

### 模块职责

| 模块 | 职责 | 关键接口 |
| --- | --- | --- |
| `curriculum.py` | 题库规格：每题的考点标签与题干摘要 | `COURSE_SPECS`、`POINT_LABELS`、`LABEL_TO_POINT`、`specs_for` |
| `specs.py` | 按题目、参考答案、题面推断考点 | `resolve_specs` |
| `static_analysis.py` | 函数切块、整文件解析、结构指标、考点检测器 | `split_functions`、`parse_whole`、`detect_points`、`function_metrics` |
| `lint.py` | pylint 适配，只启用与教学相关的消息，英文消息映射为中文建议 | `run`、`pylint_available` |
| `rules.py` | 题意规则：静态推断与题目要求冲突的写法 | `evaluate_task`、`common_rules`、`RULES` |
| `rubric.py` | 量表解析（Markdown 表格 / 列表写法）与维度打分 | `dimensions_from_text`、`load_rubric`、`score_student`、`weighted_total` |
| `pipeline.py` | 临时落盘、执行评测图、组装 `StudentAnalysis` | `analyze_text` |
| `agent_graph.py` | LangGraph 状态图：节点注册、条件路由、编译缓存 | `build_graph`、`compiled_graph`、`invoke`、`node_names` |
| `stages.py` | 评测各阶段实现，输入输出都是图状态 | `resolve_specs`、`prepare`、`run_lint`、`build_tasks`、`collect_notes`、`score` |
| `charts.py` | matplotlib 极坐标雷达图 | `render` |
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

雷达图不直接使用维度名：`school/portal/rubric_agent.py` 会按作业的考察知识点归纳六个主能力，每个能力绑定一个维度，轴名用能力名、分数取所绑定维度的分数。

### 幂等与缓存（Django 侧）

`QualityReport` 与一次提交一对一。复用的条件是源码摘要和量表/考点/能力指纹都没变：

- `source_sha256`：源码内容；
- `payload.rubric_signature`：量表维度、本题考点标签、评分标准知识点与六个主能力拼接后的指纹。

任一变化就重新生成，旧的 Markdown / PNG 交给 `PrivateFileCleanup` 延迟删除。因此教师改了评分标准、题库补了考点配置或重新归纳了主能力，学生下次打开报告会自动更新。

### 扩展点

- **新增课程**：`curriculum.COURSE_SPECS` 增加一组 `TaskSpec`；新考点标签要在 `POINT_LABELS` 与 `static_analysis.KNOWLEDGE_DETECTORS` 同时登记。
- **新增题意规则**：`rules.py` 写函数返回 `(行号, 缺陷, 建议, 维度)`，注册进 `RULES`。
- **新增评分维度**：`models.DIMENSION_LABELS` 加 key 与中文名，并在 `rubric.score_student` 的 `raw` 映射里给出评分口径；`school/portal/rubric_agent.py` 的 `DIMENSION_POOL` 同步登记，主能力才能绑定它。
- **替换输出**：`service.payload` 是网页渲染的唯一数据源，字段增减不影响打分。
- **新增评测步骤**：在 `stages.py` 写一个 `(state) -> dict` 的函数，在 `agent_graph.build_graph` 注册节点并接边，同时更新 `NODE_NAMES`；不需要改 `pipeline`。

### 设计取舍

- **只做静态分析**：不执行学生代码，缺陷一律表述为“疑似/应核对”，不声称运行通过或失败；需要运行期验证时复用 `school/judge.py` 的受限容器。
- **用状态图而非顺序调用**：`lint` 要按“整文件是否可解析”分支，状态图把这一判断显式化成条件边；各阶段可单独测试，后续插入 LLM 节点也不必改评分逻辑。
- **逐题切块**：单个函数语法错误不会拖垮同文件其他题的分析，只有整文件不可解析时才整体降级。
- **考点用 AST 检测器**：比正则匹配跨行写法更稳，也避免把字符串或注释里的同名文本当成实现。
- **考点标注依赖参考实现**：同一道题有多种写法，标签只保证题库 `gold.py` 的写法能命中；学生用了等价但结构不同的写法，可能出现误判的 ✗，这是当前的主要局限。
- **评分标准按任务存库**：每个作业的量表、知识点与六个主能力都只属于自己，不再共用仓库里的通用量表文件。

## 题库来源

题库包放在仓库根目录的 `exercise requirements/`（`func_info_list.txt`、`*习题说明.docx`、`gold.py`、`data/funcXxx.txt`），
由 `school/management/commands/import_course_packages.py` 导入数据库；网页端只读数据库里的题目与参考答案。

## 与标签库、题库、评分标准的衔接

本目录只做“源码 → 缺陷与得分”，其余环节在其他模块：

| 环节 | 负责模块 | 实现方式 |
| --- | --- | --- |
| 知识点词表 | `tools/taglib/loader.py` | 解析根目录 `Python教学Tag库_v1.0.md`，`normalize_tag()` 先精确后包含匹配做归一 |
| 考点检测器 | 本目录 `static_analysis.KNOWLEDGE_DETECTORS` | key 与 `curriculum.POINT_LABELS` 一一对应；新增标签必须两边同时登记，否则永远检测不到 |
| 题目/Tag 反查 | `tools/taglib/loader.py`（`qbank_by_tag`）、`school/portal/question_bank.py` | 读 `qbank-tags-v2.json` 与 `Python题库.md`，供弱项练习按 Tag 选题 |
| 评分标准与六主能力 | `school/portal/rubric_agent.py` | 大模型按题目与参考答案产出维度与主能力，无 Key 时用 `ast` 规则兜底，写入 `CourseworkRubric` |
| 报告生成与缓存 | `school/portal/quality_service.py` | 源码 sha256 + 量表/知识点/能力签名一致才复用旧 `QualityReport`，否则后台线程重算 |

注意：根目录隐藏目录 `.qbank/` 与 `tools/taglib/` **同名不同物，不要混用**：

- `.qbank/spec_a~c.py` 是**题目**规格，`.qbank/build.py` 由它生成 `Python题库.md` 和 `qbank-package/`，是这两个文件的唯一生成器，`Python题库.md:3090` 的维护说明仍指向它。
- `tools/taglib/spec_a~c.py` 是**标签词表**规格，`tools/taglib/build.py` 只生成标签库文档与 `tags.json`，不产出题库。

## 环境准备

需要 Python 3.12 或更高版本，以及两个第三方库：`pylint`（静态检查）与 `matplotlib`（雷达图）。

已按项目约定使用虚拟环境时：

```powershell
# Windows
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.txt
```

```bash
# Ubuntu
.venv/bin/python -m pip install -r requirements/dev.txt
```

## 评分标准从哪来

评分标准不来自仓库文件，而是按作业存在数据库：

1. 教师在“分析题目”触发 `school/portal/rubric_agent.py`：大模型根据题目与参考答案产出知识点，以及六个“考察重点（雷达图维度）”，每个考察重点自带 5 分制量表（5/4/3/2/1 分描述），写入 `CourseworkRubric`；
2. 没有配置大模型时用规则兜底，同样按该作业的题目生成；
3. 学生首次打开报告时若该作业还没有量表，`quality_service.ensure_rubric()` 会生成规则版并存库，保证每个任务都有独立的一套；
4. 运维可用 `manage.py refresh_abilities` 按各作业的知识点重新归纳六个主能力（`--offline` 只做规则归类，`--coursework <id>` 只处理一个作业）。

量表 Markdown 若包含「量表」小节，`rubric.dimensions_from_text()` 会解析其中的表格或 `- 维度：30%` 列表写法；维度名通过关键词映射到内置 key，权重自动归一化。

## 限制与安全边界

- **不执行学生代码**。评测完全静态，缺陷是“静态推断”，报告中使用“疑似/应核对”措辞，不声称运行通过或失败。
- 若后续接入运行期验证，应复用 `school/judge.py` 的受限容器（`--network none`、只读根、降权用户），不要在主机直接 `exec` 学生代码。
- 语法错误的函数不会影响同文件其他函数的分析；但整份文件无法编译时，知识点按 50% 计、规范维度封顶 50 分，并在报告中标注。
- 规则针对题库设计，不能自动发现题意之外的业务逻辑错误；未注册规则的题只做 lint 与知识点检测。

## 常见问题

**提示 `pylint 不可用`**：当前解释器没装 pylint。用同一个解释器安装，或确认命令里的 `python` 是预期的那一个。

**报告里没有 lint 结果**：学生文件整体无法解析时 pylint 会跳过，报告会写明“pylint 已跳过”。

**雷达图中文变方框**：系统缺少中文字体。Windows 装 Microsoft YaHei、Ubuntu 装 `fonts-noto-cjk` 后重跑。
