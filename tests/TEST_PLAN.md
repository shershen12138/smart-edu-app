# 软件测试实践任务 —— 测试用例文档

## 概述

| 项目 | 内容 |
|---|---|
| 被测系统 | smart-edu-app（Django 弱项练习与机器批阅子系统） |
| 测试框架 | Django TestCase（unittest 风格，等价于 pytest 基座，可直接用 pytest 运行） |
| 运行方式 | `.venv/Scripts/python.exe manage.py test tests` |
| 测试代码位置 | `tests/test_unit_core_logic.py`、`tests/test_equiv_boundary.py`、`tests/test_e2e_scenario.py` |
| 测试用例总数 | 57 个，全部通过 |

## 选定的核心逻辑

| 模块 | 职责 |
|---|---|
| `school/portal/knowledge_profile.py` | 弱项画像统计（得分率聚合、弱项/掌握划分、阈值钳制、关键词拆分） |
| `school/portal/practice_agent.py` | 训练题解析（模型 JSON → 题目结构）、评测用例清洗、批阅结果格式化 |
| `school/portal/question_bank.py` | 题库用例单元格清洗、返回值打包（判题器协议） |

## 任务 1：核心逻辑单元测试

文件：`tests/test_unit_core_logic.py`（25 个用例，纯逻辑，无 DB/LLM/Docker 依赖）

| 测试类 | 覆盖点 |
|---|---|
| `WeakKeywordsTests` | 弱项名 → 检索关键词：分隔符拆分、小写归一、停用词过滤、边缘连接词去除 |
| `WeakPointsTests` | 画像 dict → 弱项/掌握划分：排序、阈值切分、零尝试排除、空画像 |
| `WeakThresholdTests` | 阈值配置解析：默认值、非法值回落、钳制到 [0,1] |
| `FormatValueTests` | 打包 JSON → 可读 repr：容器/标量/空串/非法 JSON 原样返回 |
| `ParsePracticeTests` | 模型输出解析：合法 JSON、围栏剥离、偏离弱项/缺字段/无用例的题丢弃、每弱项最多 2 题、难度兜底、非法输入抛 `PracticeParseError` |
| `QuestionBankHelpersTests` | 单元格清洗、函数签名解析、返回值打包、打包→还原回环 |

## 任务 2：等价类划分 + 边界值分析

文件：`tests/test_equiv_boundary.py`（17 个用例）

### 选定输入字段

1. `_normalize_cases(raw)` 的输入 —— 训练题评测用例列表（决定机器批阅计分）。
2. 派生字段：`weak_threshold()` 的配置值（钳制区间 [0,1]）、`weak_keywords()` 的 token 长度。

### 等价类表（_normalize_cases）

| 编号 | 输入条件 | 有效等价类 | 无效等价类 |
|---|---|---|---|
| EC1-2 | 用例结构 | input/output 均非空 → 保留 | 缺 input 或缺 output → 丢弃 |
| EC3 | 列表元素类型 | dict → 解析 | 非 dict（str/int/None）→ 丢弃 |
| EC4 | 输入整体类型 | list → 逐项处理 | None/str/int/dict → 返回空列表 |
| EC5 | is_sample 字段 | 任意真值 → True | 假值 → False |
| EC6 | 空白字符 | 非空白 → 保留 | 仅空白 → 视为缺失丢弃 |

对应用例：`NormalizeCasesEquivalenceClassTests`（9 个）。

### 边界值表

| 编号 | 边界点 | 取值 | 期望 |
|---|---|---|---|
| BVA1 | 用例数量下界 | 0 条 / 1 条 | 0 条返回空；1 条保留 |
| BVA2 | 用例数量上界 = 5（`MAX_CASES_PER_QUESTION`） | 恰好 5 条 | 全部保留 |
| BVA3 | 上界外 | 6 条 | 截断为前 5 条 |
| BVA4 | 阈值钳制下界 0 | -0.1 / 0.0 / 0.1 | -0.1→0；其余原值 |
| BVA5 | 阈值钳制上界 1 | 0.9 / 1.0 / 1.1 | 1.1→1；其余原值 |
| BVA6 | 关键词长度下界 | 长度 1 / 长度 2 | 长度 1 丢弃，长度 2 保留 |

对应用例：`NormalizeCasesBoundaryValueTests`、`WeakThresholdBoundaryValueTests`、`WeakKeywordsBoundaryValueTests`（8 个）。

## 任务 3：场景法端到端测试

文件：`tests/test_e2e_scenario.py`（6 个场景，每个场景一条端到端链路）

**关键业务流程**：学生登录 → 查看弱项画像 → 生成训练计划 → 查看训练题 → 提交代码 → 机器批阅 → 查看逐用例结果。

### 场景矩阵

| 场景 | 组合 | 用例 | 预期结果 |
|---|---|---|---|
| S1 基本流 | 有弱项 + 提交正确代码 | 提交 → 生成计划（source=rule）→ 看题 → 提交 | AC，2/2 用例通过，得分 100，结果页可见 |
| S2 备选流 1：部分通过 | 提交部分正确代码 | 提交 | WA，1/2 通过，得分 50（按比例计分） |
| S3 备选流 2：空提交 | 提交空代码 | 提交 | 表单校验拒绝，不产生批阅记录 |
| S4 备选流 3：无弱项学生 | 画像无弱项 | 请求生成计划 | 不生成训练计划 |
| S5 备选流 4：越权 | 其他学生访问他人题目/结果 | GET | 403 |
| S6 备选流 5：未登录 | 匿名访问训练页 | GET | 302 跳转登录页 |

批阅结果通过 mock `practice_agent.run_case` 模拟（与既有 `school/tests/test_practice_agent.py` 做法一致）；真实 Docker 容器批阅由 `RUN_DOCKER_TESTS=1` 门控的 `school/tests/test_docker.py` 覆盖，不在本任务范围。

## 任务 4：覆盖率统计

```powershell
.venv/Scripts/python.exe -m coverage run --source=school manage.py test tests
.venv/Scripts/python.exe -m coverage report --include="school/portal/practice_agent.py,school/portal/knowledge_profile.py,school/portal/question_bank.py"
```

实测结果（本次提交）：

| 模块 | 语句 | 未覆盖 | 覆盖率 |
|---|---|---|---|
| knowledge_profile.py | 132 | 40 | 70% |
| practice_agent.py | 232 | 40 | 83% |
| question_bank.py | 195 | 51 | 74% |
| **核心逻辑合计** | 559 | 131 | **77%**（≥ 60% 达标） |

## 已知边界与说明

- 覆盖率缺口主要为：LLM 在线生成路径（需真实 LLM 服务）、真实 Docker 容器批阅（`school/judge.py` 沙箱）、教师端班级汇总视图 —— 均不属于本次单元/端到端测试的可达范围。
- 测试运行使用内存 SQLite 与临时私有存储目录，不触碰真实 `.runtime` 数据。
