# tests/ 目录说明

仓库根目录的 `tests/` 是一个**空占位目录**，只有一个 `readme.md`。真正的测试位于 `school/tests/`，`manage.py test school.tests` 只发现后者。

## 真实测试位置与分组

| 分组 | 模块 | 覆盖内容 |
| --- | --- | --- |
| 现行三端回归 | `test_portal`、`test_roster_scope`、`test_review_changes`、`test_package_regressions`、`test_auth_views`、`test_llm_config`、`test_rubric_views`、`test_rubric_agent`、`test_quality_report`、`test_practice_agent` | 页面、权限、上传提交、批阅包更新、名册口径、认证、大模型配置、评分标准、质量报告、弱项练习 |
| 旧路由回归 | `test_legacy_views`、`test_teaching`、`test_workflows` | 用 `@override_settings(ROOT_URLCONF='config.legacy_urls')` 跑旧门户全流程 |
| 批阅与沙箱 | `test_judge_unit`、`test_judge_sandbox`、`test_grading_unit`、`test_docker` | 执行器状态机、Docker 命令（mock）；`test_docker` 是唯一需要真实容器的模块 |
| 解析与命令 | `test_parsers`、`test_imports_and_commands` | 上传材料解析与校验、名单导入、管理命令 |
| 纯函数 | `test_taglib`、`test_quality_rules`、`test_quality_agent_internals` | Tag 加载与归一、题库反查、题意规则、评测图内部 |
| 基础设施 | `test_exception_logging` | ERROR 及以上落盘到轮转 `exception.log` |

辅助文件：`school/tests/tests_helpers_docx.py` 负责现场生成最小 `.docx` 夹具；`__init__.py` 为空。

## 怎么跑

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test school.tests
```

只跑一组时用模块名，例如 `manage.py test school.tests.test_portal`。真实容器验收需要显式开关：

```powershell
$env:RUN_DOCKER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test school.tests.test_docker
```

Ubuntu 下改用 `.venv/bin/python`，命令等价。

## 写测试的约定

- **没有 `conftest.py`**：夹具由各文件 `setUp` 自建，常用 `@override_settings(PASSWORD_HASHERS=MD5, REDIS_URL='', CACHES=locmem)` 让测试不依赖 Redis 与慢哈希。
- 私有存储指向临时目录，测试不会污染 `.runtime/private`。
- 需要 Docker 的用例沿用 `RUN_DOCKER_TESTS=1` 开关，未开启时跳过，不要用 mock 结果冒充真实批阅通过。
- 修改权限、计分、并发受理规则时，先补能复现问题的用例，再改实现。
