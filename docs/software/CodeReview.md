# 代码评审报告 — smart-edu-app（课码 · Python 作业在线批阅系统）

> 评审方式：AI 辅助评审（静态检查 + 全量测试 + 代码走读），评审深度 medium。
> 评审对象：`codex/main` 提交 `ef4a883`（含 PR #18 评分标准重构、PR #19 知识点弱项画像与个性化训练题）。

## 1. 关于代码

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 模块名 | smart-edu-app | Django 单体应用：`school/portal/`（业务）+ `tools/code_quality_agent/`（评测引擎）+ `school/judge.py`（Docker 隔离执行） |
| 审查人员 | CodeBuddy（AI 辅助评审） | ruff 静态检查、`manage.py check`、全量业务测试、分模块代码走读 |
| 版本 | 1.0 | Git 提交 `ef4a883` |
| 日期 | 2026-11-07 | |
| 程序设计语言 | Python 3.12 + Django 5.2 | 辅以 Django 模板 HTML/JS，无 Node 构建步骤 |
| 作者 | zzzjjj728、shershen12138 | GitHub 提交记录 |
| 文件数 | 120 个 `.py` 文件 | 不含 `.venv` 与 `.runtime` |

## 2. 自动检查

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 代码通过编译，没有任何错误 | 是 | Python 无独立编译步骤；`manage.py check` 通过，`0 issues` |
| 代码通过编译，没有任何警告信息 | 否 | `manage.py check` 无警告，但启动时有第三方 `LangChainPendingDeprecationWarning`（langgraph 0.3.34） |
| 存在单元测试 | 是 | 173 项业务测试，`OK (skipped=13)`；13 项为真实 Docker 测试，需 `RUN_DOCKER_TESTS=1` |
| 代码处于源代码版本控制之下 | 是 | Git，远程 `github.com/shershen12138/smart-edu-app` |
| 使用检查工具对代码进行了检查 | 是 | ruff 0.16.8 + Django `manage.py check` |
| 检查工具名称 | ruff / djlint（已配置） | `pyproject.toml` 预设规则集 E/W/F/I/B/C4/UP；本地有一处未提交修改使 TOML 非法，检查以隔离模式按预设规则集执行 |
| 使用检查工具检查的结果 | Error（345） | F405×194（star 导入）、E501×33（行长）、F401×31（未用导入）、I001×25（导入排序）等；78 项可 `ruff check --fix` 自动修复 |

## 3. 设计

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 代码已完成（相对于软件功能定义来说） | 是 | 管理员/教师/学生三端功能完整，含批阅、代码评测、知识画像与个性化训练 |
| 选择的算法模型很好 | 是 | LLM 生成评分标准/训练题 + 规则兜底并标注来源；机器批阅按用例比例计分；Docker 容器隔离执行学生代码（无网络、只读、非 root、pids/cpu/mem 限额，`school/judge.py:59-101`） |
| 采用了恰当的设计模式 | 是 | 分层清晰：评测引擎（不依赖 Django）→ service 适配层 → Django 业务层 → 视图；Agent 用 langgraph 图编排 |
| 任何缺失的功能都已在代码中清晰的标出 | 是 | 未配置 LLM 时明确标注 `source='rule'` 兜底来源，教师端有提示 |
| 代码的结构很好 | 是 | 常量集中（`DIMENSION_POOL`、`ABILITY_RULES`），docstring 说明设计边界 |
| 存在设计文档 | 是 | `docs/REQUIREMENTS.md`、`docs/VALIDATION.md`、`AGENTS.md`、`tools/code_quality_agent/README.md` |
| 代码与这些文档相符 | 是 | 与 `AGENTS.md` 声明的约束（角色、批阅规则、安全边界）一致 |

## 4. 对代码编写质量的总体意见

### 风格

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 代码的布局很清晰 | 是 | 分层与目录职责明确 |
| 代码遵循项目的风格准则 | 部分 | ruff/djlint 规则已配置，但存量代码有 345 项违规；且本地 `pyproject.toml` 被改坏，规则实际未生效 |
| 存在良好（无歧义）的公共 API | 是 | 视图层 URL 语义清晰，service 层函数签名稳定 |
| 选择的名称表达清晰和易理解 | 是 | 如 `ensure_rubric`、`normalize_abilities`、`student_knowledge_profile` |

### 防御性编程

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 避免空指针 | 是 | 全程 `or []`、`getattr(..., None)` 防护，未见明显空引用隐患 |
| 数据类型选择正确并使用类型检查 | 是 | pydantic 模型、`TypedDict`、LLM 返回严格类型校验（`rubric_agent.py:278-399`、`practice_agent.py:139-176`） |
| 所有输入都经过验证 | **否** | 严重项 S1：学生姓名未清洗直接拼进临时文件路径 `lint-{name}.py`（`pipeline.py:98`）；练习提交代码无 `max_length` 上限（`practice_views.py:26-29`）；LLM 返回字段无长度校验直接落库（`practice_agent.py:167-169`） |
| 限制资源使用 | 部分 | Docker 容器限额完善；但报告生成（pylint + matplotlib）与练习批阅在 GET/POST 中同步执行，无速率限制 |
| 控制并发 | **否** | 严重项 S2/S3：报告生成无锁（`quality_views.py:43`）、练习提交与计划生成无并发去重/幂等（`practice_views.py:60-75, 121-143`）；批阅抢占（`judge.py:273-293`）反而做得很好 |
| 避免循环引用 | 是 | 未发现 |
| 不存在特定编译器功能（C/C++） | 不适用 | Python 项目 |

### 错误处理

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 错误情况都得到了处理 | 部分 | LLM 三类异常 + 兜底路径设计正确；但存在多处静默吞错：`quality_service.py:46-47`、`practice_agent.py:222-226`（裸 `except Exception: return ''`）、`practice_views.py:49-53` |
| 使用断言来验证逻辑 | 否 | 业务代码未使用断言（测试中正常使用） |
| 代码是异常安全(exception safe)的 | 是 | lint 临时文件有 `finally` 清理，Docker 容器 `finally` 强制删除 |
| 错误将被传播，而不会被隐藏 | 部分 | `rubric_agent.py:462,600` 的 `json.loads` 异常未按约定包成 `RubricParseError`；`grade_attempt` 对非基础设施异常无兜底标记，attempt 卡中间态（`practice_agent.py:296-328`） |
| 本地有日志文件 | **否** | `judge.py`、`rubric_agent.py`、`quality_service.py`、`quality_views.py`、`practice_agent.py`、`practice_views.py` 全部零 logging，吞错处不记录，排障困难 |
| 没有任何资源被泄露 | 部分 | Docker 容器清理完善；"先写文件后写库"或事务内外部 IO 失败时留下无登记孤儿文件（`quality_service.py:257-274`、`practice_agent.py:255-261`） |
| 代码使用多线程 | 不适用 | 无显式多线程；并发来自 Django 请求与批阅循环 |
| 它是线程安全的 | 部分 | `agent_graph.py:66-71` 懒初始化无锁（后果轻）；批阅抢占用条件 `update` 正确 |
| 不会发生死锁 | 是 | 仅单表短事务 `select_for_update`，无嵌套锁 |

### 结构

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 不存在冗余的代码 | 否 | `rubric_agent.py:518-528` 与 `:296-298` 重复 levels 组装逻辑；`knowledge_profile.py:50-75` 与 `:161-191` 重复聚合逻辑；`judge.py:181-195` 有死代码 |
| 不存在剪切粘贴式的编程 | 否 | `rubric_agent.py:487-490` 题库映射与 `service.py:20-25` 完全重复；等级阈值 90/80/70/60 等魔法数字内联 |

## 5. 代码审查清单（语句级）

### 严重

| 文件 | 行 | 问题 | 说明 |
| :---- | :---: | :---- | :---- |
| `tools/code_quality_agent/pipeline.py` | 98 | 学生姓名未清洗拼入临时文件路径 `lint-{name}.py` | 路径注入 + 同名学生/双开页面时一方 `unlink` 删掉另一方在用的文件（Windows 表现为 `OSError: busy`）。改用 `tempfile` 或加 uuid |
| `school/portal/quality_views.py` | 43 | GET 请求中同步生成报告且无并发锁 | pylint + matplotlib 重活可被并发请求放大；落败请求留下孤儿文件。建议加缓存锁或改任务队列 |
| `school/portal/practice_views.py` | 26-29, 121-143 | 练习提交代码无长度上限，提交后同步跑 Docker 批阅且无频率/并发控制 | 连击或脚本可产生大量并行批阅，耗尽 Docker 批阅资源 |
| `school/portal/knowledge_profile.py` | 52-55, 133-134, 168 | 全班画像 N+1 查询（学生数 × 作业数逐条查库，无 prefetch） | 教师端页面随班级规模线性变慢，大班可超时 |

### 一般

| 文件 | 行 | 问题 | 说明 |
| :---- | :---: | :---- | :---- |
| `school/portal/quality_service.py` | 46-47 | `except Exception: return stored` 静默吞掉所有异常且无日志 | 教师端会误以为评分标准已生成 |
| `school/portal/quality_views.py` | 47-49 | 报告生成兜底分支只给泛化提示不记日志 | 根因丢失 |
| `school/portal/rubric_agent.py` | 462, 600 | `json.loads` 异常未包成 `RubricParseError` | 异常契约被 `_extract_json` 自身的约定破坏 |
| `school/portal/rubric_agent.py` | 233-265 | LLM `chat()` 无重试/退避 | 教师一次点击失败即失败 |
| `school/portal/practice_agent.py` | 222-226, 302, 305-319 | 裸 `except Exception` 吞错无日志；`grade_attempt` 对非基础设施异常无兜底标记 | attempt 永久停留中间态且无留痕 |
| `school/portal/practice_agent.py` | 167-169, 246-261 | LLM 返回的题目/代码/解释无长度校验直接落库；`save_private` 外部 IO 放在事务内 | 回滚会留孤儿文件 |
| `school/portal/practice_views.py` | 60-75 | 生成计划无幂等/限流 | 并发点击生成多份重复 plan，旧 plan 成为垃圾数据 |
| `school/judge.py` | 181-195 | `timed_out` 在 181 行已 return，194 行判断为死代码 | 维护易错 |
| `pyproject.toml` | 14-16 | 本地未提交修改使 TOML 非法（`[tool.ruff]` 重复声明） | ruff/CI 无法读取项目 lint 配置 |

### 建议

| 文件 | 行 | 问题 | 说明 |
| :---- | :---: | :---- | :---- |
| `school/portal/rubric_agent.py` | 518-528 / 296-298 | 抽公共 `_levels_for`；`:487-490` 复用 `service.known_specs()` | 消除重复 |
| `school/portal/knowledge_profile.py` | 50-75, 161-191 | 合并重复聚合逻辑，补 `entries`/`questions` prefetch | 与严重项 4 一并处理 |
| `tools/code_quality_agent/pipeline.py` | 30-38 | 等级阈值 90/80/70/60 魔法数字 | 提为常量或配置 |
| `school/judge.py` | 72-88 | `pids-limit 16`、`nofile=64` 等安全参数内联 | 与 `JUDGE_CONTAINER_START_GRACE_SECONDS` 风格统一，提为 settings |
| `tools/code_quality_agent/agent_graph.py` | 66-71 | `_COMPILED` 懒初始化无锁 | 改为模块级构建或加锁 |
| `school/portal/practice_agent.py` | 196-198, 332-336 | `rule_based` O(n²) 计数改 dict；删除 `status_text` 薄包装；`latest_plan` 显式 `order_by` | 小改进 |
| `school/tests/test_practice_agent.py` | — | 缺 `practice_submit` 视图流程、越权访问、并发提交、`_read_case` 读失败测试 | 补充覆盖 |

## 6. 跟踪调查

### 评审结论

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 代码质量较好 | 是 | 整体架构分层清晰、Docker 隔离安全设计优于平均水平、173 项测试全部通过、LLM 兜底与来源标注设计正确；但存在 4 项严重问题需修复 |
| 重新编写并验证 | 未完成 | 不需要整体重写，仅需修复严重项 4 项与一般项 9 项 |
| 重新编写并重新审查 | 未通过 | 待修复 S1（路径注入）、S2（报告生成无锁）、S3（练习提交无频率控制）、S4（N+1 查询）后复审 |

### 审查结果记录

| 检查项目 | 结果 | 说明 |
| :---- | :----: | :---- |
| 审查 | 存在问题，需修复后重新审查 | 严重 4 项（路径注入、报告生成无并发锁、练习提交无频率控制、全班画像 N+1）；一般 9 项（静默吞错、异常契约、无重试、幂等缺失、事务内外部 IO、死代码、TOML 损坏等）；建议 7 项 |
| 校验 | 通过 | `manage.py check` 0 issues；业务测试 173 项全部通过（13 项 Docker 测试跳过，需 `RUN_DOCKER_TESTS=1`）；ruff 345 项存量违规待清理（78 项可 `--fix` 自动修复） |

### 评审环境说明

- 静态检查用 ruff 0.16.8 隔离模式执行（因 `pyproject.toml` 本地未提交修改损坏 TOML 格式）
- 业务测试依赖 `pylint`（`requirements-dev.txt` 开发依赖），本机已安装后全部通过
- 13 项真实 Docker 测试本次未运行（需要 Docker Linux 引擎），不影响其余 160 项结论
- 评审不涉及学校已部署环境；所有结论基于本机独立测试环境
