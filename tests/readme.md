# tests/ 目录说明

本仓库有**两套测试**，位置不同、命令不同、分工也不同，不要混为一谈：

| 位置 | 命令 | 规模 | 定位 |
| --- | --- | --- | --- |
| 根目录 `tests/` | `manage.py test tests` | 60 项 | 软件测试实践作业交付：核心逻辑单元测试、等价类/边界值、场景法端到端，配套用例文档 `TEST_PLAN.md` |
| `school/tests/` | `manage.py test school.tests` | 655 项（含 13 项 Docker 跳过） | 项目自身回归：三端页面、权限、批阅、解析、命令、基础设施 |

两套互不覆盖，提交前建议都跑。

## 一、根目录 `tests/`

| 文件 | 内容 |
| --- | --- |
| `TEST_PLAN.md` | 测试用例文档：被测系统、运行方式、被测模块、等价类表与边界值分析、场景法流程 |
| `test_unit_core_logic.py` | 核心逻辑单元测试（无 DB、无 LLM、无 Docker）：弱项关键词拆分、弱项/掌握划分、阈值钳制、返回结果格式化、模型输出解析、题库单元格清洗 |
| `test_equiv_boundary.py` | 等价类划分 + 边界值分析：训练题评测用例清洗、阈值钳制区间、关键词 token 长度 |
| `test_e2e_scenario.py` | 场景法端到端：把「学生提交 → 质量报告 → 弱项画像 → 训练题 → 判题」串起来 |
| `__init__.py` | 使根目录成为可被 Django 测试发现器导入的包，缺了它 `manage.py test tests` 会报找不到模块 |

被测模块集中在 `school/portal/` 的三个纯逻辑文件：`knowledge_profile.py`、`practice_agent.py`、`question_bank.py`。

```powershell
.\.venv\Scripts\python.exe manage.py test tests --noinput
```

## 二、`school/tests/`

| 分组 | 模块 | 覆盖内容 |
| --- | --- | --- |
| 现行三端回归 | `test_portal`、`test_roster_scope`、`test_review_changes`、`test_package_regressions`、`test_auth_views`、`test_llm_config`、`test_rubric_views`、`test_rubric_agent`、`test_quality_report`、`test_practice_agent` | 页面、权限、上传提交、批阅包更新、名册口径、认证、大模型配置、评分标准、质量报告、弱项练习 |
| 旧路由回归 | `test_legacy_views`、`test_teaching`、`test_workflows` | 用 `@override_settings(ROOT_URLCONF='config.legacy_urls')` 跑旧门户全流程 |
| 批阅与沙箱 | `test_judge_unit`、`test_judge_sandbox`、`test_grading_unit`、`test_docker` | 执行器状态机、Docker 命令（mock）；`test_docker` 是唯一需要真实容器的模块 |
| 解析与命令 | `test_parsers`、`test_imports_and_commands` | 上传材料解析与校验、名单导入、管理命令 |
| 纯函数 | `test_taglib`、`test_quality_rules`、`test_quality_agent_internals` | Tag 加载与归一、题库反查、题意规则、评测图内部 |
| 基础设施 | `test_exception_logging` | ERROR 及以上落盘到轮转 `exception.log` |

辅助文件：`tests_helpers_docx.py` 负责现场生成最小 `.docx` 夹具；`__init__.py` 为空。

## 三、怎么跑

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test tests --noinput
.\.venv\Scripts\python.exe manage.py test school.tests --noinput
```

只跑一组时用模块名，例如 `manage.py test school.tests.test_portal` 或 `manage.py test tests.test_equiv_boundary`。真实容器验收需要显式开关：

```powershell
$env:RUN_DOCKER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test school.tests.test_docker
```

Ubuntu 下改用 `.venv/bin/python`，命令等价。

## 四、写测试的约定

- **没有 `conftest.py`**：夹具由各文件 `setUp` 自建，常用 `@override_settings(PASSWORD_HASHERS=MD5, REDIS_URL='', CACHES=locmem)` 让测试不依赖 Redis 与慢哈希。
- 私有存储指向临时目录，测试不会污染 `.runtime/private`。
- 需要 Docker 的用例沿用 `RUN_DOCKER_TESTS=1` 开关，未开启时跳过，不要用 mock 结果冒充真实批阅通过。
- 修改权限、计分、并发受理规则时，先补能复现问题的用例，再改实现。
- 根 `tests/` 与 `school/tests/` 的用例数会随提交变化（`TEST_PLAN.md` 里写的 57 项已是历史数字，实际以 `manage.py test tests` 输出的 `Found N test(s)` 为准）。
