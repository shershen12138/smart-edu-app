# 面向协作 AI 的项目说明

## 先识别任务场景

- 当前协作分支：`codex/simplified-coursework`。不要假定 `main` 是当前版本。
- 新电脑安装或本地测试：读 `README.md` 与 `docs/GETTING_STARTED.md`，先识别操作系统、解释器、Docker 引擎、现有配置和数据。
- 学校已有 Ubuntu 24.04 部署更新：读 `deploy/linux/README.md`。现场根目录是 `/opt/coursejudge`，依赖原首次部署包、镜像和网络配置；使用 `deploy/linux/update.sh`。
- 一台全新正式服务器：参考 `docs/DEPLOYMENT.md`，不能把更新脚本当作首次安装器。

## 环境与数据

本地使用 Python 3.12、`requirements.lock.txt`、SQLite 与 `run_judge`；没有 Node 构建步骤。Windows 虚拟环境解释器是 `.venv/Scripts/python.exe`，Ubuntu 是 `.venv/bin/python`。网页与本地批阅分别运行；机器批阅需要 Docker Linux 引擎和 `python:3.12-slim`。

学校部署使用 Docker、MySQL、Redis 与 Celery；源码仓库中的根 `compose.yaml` 为通用 HTTPS 部署参考，`deploy/linux/compose.yaml` 为现有校园部署更新配置，两者不能混用。不要替换现场网络、防火墙和动态 IP 脚本。

先保留已有 `.env`、`.runtime`、上传文件、数据卷和用户修改。检查环境变量是否覆盖 `.env`，不要输出数据库密码、密钥或密码恢复副本。`reset_local_accounts --confirm-reset` 只适用于明确创建空白本地测试环境，不用于已有环境更新或修复；不自动重置真实账号。

学校更新必须先有数据库与私有文件备份。更新脚本已实现暂停写入、备份、迁移、清理旧逻辑删除和重启；失败保留报错及备份，不通过删除数据卷或初始化来消除错误。不要仅切换旧镜像就宣称已经完整回滚数据库变更。

Gitee 不包含安装器、离线镜像、真实题目包、账号或学生数据。缺材料时说明具体缺项；业务及真实 Docker 自动化测试使用合成夹具，可以独立运行。不要把模拟结果报告为真实批阅通过。

## 当前代码与规则

以用户最新要求及 `docs/REQUIREMENTS.md` 为准。当前 URL 是 `config/urls.py`，业务在 `school/portal/`；旧 `legacy_urls` 只供回归测试。当前只有管理员、教师、学生；不恢复旧助教、审批、成绩发布流程。

机器批阅按用例通过比例计分；非机器批阅支持教师评分。教师可查看期望及实际结果，学生保持答案隐藏。永久删除与可恢复归档是两种操作；归档内容不能通过旧 URL 绕过。上传代码必须在受限 Docker 中运行。

## 验证与交付

使用项目虚拟环境执行 `manage.py check`、`manage.py makemigrations --check --dry-run` 和与变更相关的测试。完整业务测试为 `manage.py test school.tests`；真实容器测试需 `RUN_DOCKER_TESTS=1`，命令详见安装指南。不要为纯文档修改重跑全部容器测试。

同步时先检查工作区及远端，保留同学提交，不强制推送。迁移已到 `0011`，下一次改模型先检查分支上的实际编号。交付说明分清代码已推送、测试已完成、学校机器是否实际更新，不将三者混为一谈。
