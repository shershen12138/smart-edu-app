# 两人协作开发（2026-10-06）

## 第一次加入

仓库所有者在 Gitee 的“管理 → 仓库成员管理”邀请协作者，并授予开发者权限。
私有仓库只向已加入的成员开放。当前协作和交付分支是 **`codex/simplified-coursework`**，不是 `main`。协作者按 [新电脑安装与测试](docs/GETTING_STARTED.md) 创建自己的 `.venv`、`.env` 和测试账号。
不要共享开发数据库、`.env` 或本机随机密码；各自初始化测试数据。

```bash
git clone --branch codex/simplified-coursework --single-branch https://gitee.com/arongmiao/python-course-judge.git
cd python-course-judge
git switch -c codex/your-feature
```

## 每次修改

1. 先检查 `git status`，保留未提交的修改，再到 `codex/simplified-coursework` 执行 `git pull --ff-only` 同步同学的提交。
2. 每个功能建议建立独立分支，例如 `codex/student-dashboard`。直接共用协作分支时避免同时修改相同文件，不强制推送覆盖另一人的工作。
3. 修改代码和必要的测试；数据模型变化后运行 `python manage.py makemigrations`。
4. 执行 `python manage.py check` 和 `python manage.py test school.tests`。
5. 提交、推送功能分支，在 Gitee 建立 Pull Request，目标选择 `codex/simplified-coursework`，另一人检查后合并。代码推送不等于学校容器已经更新，现场另按 `deploy/linux/README.md` 操作。

```bash
git add school templates static docs
git commit -m "feat: describe the behavior change"
git push -u origin codex/your-feature
```

## 合作约定

可选开发工具：`pip install -r requirements-dev.txt`。
使用虚拟环境解释器运行检查。Python 可用 `python -m ruff format`，Django 模板可用 `python -m djlint --reformat`，只格式化本次修改的文件。Windows 可执行 `scripts/check.ps1`；Ubuntu 可激活 `.venv` 后运行 `bash scripts/check.sh`。真实 Docker 测试命令见安装指南。

- 页面只显示当前题目和作业；草稿原地更新。已发布内容变化时后台保存快照，保留旧提交与成绩依据。
- 学生名单与用户身份由管理员维护；当前只开放管理员、教师、学生，不恢复旧助教、审批和成绩发布批次。
- 机器批阅按用例通过比例计分；非机器批阅保留教师逐题人工评分与评语。此前“全通过才计分”“禁止人工评分”不适用于当前版本。
- 教师可看期望和实际结果，学生保持答案隐藏。批阅只在 Docker 中执行，基础设施异常不记为学生零分。
- 永久删除实际移除关联记录与专用文件，共用文件仍有引用时保留。归档保留数据，但日常列表及旧链接不可访问，管理员取消归档后恢复。
- 在班人数按有效在班关系、学生身份及未删除账号去重；停用登录不等于离班。
- 修改权限、扣分、并发受理等规则时，补充能够复现问题的测试。
- 不提交 `.runtime/`、`.env`、学生名单、真实代码或密钥，不强制推送主分支。
- 同时修改模型时提前约定迁移编号；冲突时运行 `makemigrations --merge` 并共同检查依赖。

## 当前模块与共用文件

当前业务位于 `school/portal/`：教师端在 `teaching_views.py`、`teaching_forms.py`、`coursework_services.py`、`reporting_services.py` 和相关模板；管理员在 `administration_views.py`；学生及提交结果在 `learning_views.py`；批阅在 `grading.py` 和 `school/judge.py`。

当前 URL 入口是 `config/urls.py`。`config/legacy_urls.py`、旧 `school/views.py` 和 `school/teaching_views.py` 保留作兼容及回归，不以旧模块功能作为新增需求。

`school/models.py`、`school/course_models.py`、权限、基础模板及 URL 为共用区域；修改前同步代码。迁移已到 `0009_data_lifecycle_and_teacher_outputs`；下一次改模型先核对远端实际编号，不能直接覆盖同学的迁移。

教师通过完整机器批阅 ZIP 提供函数清单、标准答案及测试数据，不开发逐条样例录入。真实题目包另行传递，不提交 Git。不要把 `reset_local_accounts`、`seed_demo` 或删除数据卷加入日常启动。需求变化以用户最新明确要求为准，并更新相关文档。
