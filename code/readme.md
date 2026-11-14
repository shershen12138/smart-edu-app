# code/ 目录说明

本目录**不存放任何代码**，当前只有一个 `readme.md`。保留它是为了兼容旧的仓库布局与外部链接，避免有人误以为源码放在这里。

## 真正的代码在哪里

| 你要找的东西 | 实际位置 | 说明 |
| --- | --- | --- |
| 站点入口配置 | `config/` | `settings.py`（本地）、`campus_settings.py`（校园版覆盖）、`urls.py`（唯一对外路由）、`wsgi.py`、`celery.py` |
| 当前业务代码 | `school/portal/` | 36 个模块：路由、三端视图、业务服务、智能体、表单 |
| 数据模型 | `school/models.py`、`school/course_models.py` | 前者是账号/班级/授权/审计与旧版判题表，后者是当前 18 个业务模型 |
| 机器批阅 | `school/judge.py`、`school/portal/grading.py` | 前者是单用例 Docker 沙箱，后者负责批阅编排与按用例比例计分 |
| 静态评测工具 | `tools/` | `code_quality_agent/`（LangGraph 静态评测）、`taglib/`（Tag 库加载与归一） |
| 模板与前端 | `templates/`、`static/` | Django 模板 + 原生 CSS/JS，没有构建步骤 |
| 测试 | `school/tests/` | 23 个 `test_*.py`，见 `tests/readme.md` |
| 运维脚本 | `scripts/`、`deploy/linux/` | 本地启动/校验/孤儿文件清理；Linux 校园版更新 |

## 约定

- 不要在 `code/` 下新建源码目录或复制文件，Django 的 app 发现依赖 `config/settings.py` 的 `INSTALLED_APPS`，这里的文件不会被加载。
- 新增 Python 模块放回对应 app（业务写进 `school/` 或 `school/portal/`），并补上测试。
- 本目录不再扩展功能，仅保留说明作用。
