# 课码 · Python 作业在线批阅系统

2026-11-14 版本。仓库当前分支为 **`main`**，远端是 GitHub 的 `shershen12138/smart-edu-app`；`AGENTS.md`、`CONTRIBUTING.md` 等旧文档里写的 `codex/simplified-coursework` 与 Gitee 地址是早期协作记录，实际不存在该分支。机器批阅作业由学生提交一个 `.py`，非机器批阅作业由学生提交包含多题源码的 ZIP。

## 第一次打开仓库，先选用途

| 你要做什么 | 按哪份说明操作 |
| --- | --- |
| 同学在自己的 Windows / Ubuntu 电脑上安装、测试 | [新电脑安装与测试](docs/GETTING_STARTED.md)，包括命令运行位置、账号初始化、网页和批阅启动 |
| 让 AI 帮忙安装或测试 | 把仓库文件夹交给可执行终端命令的 AI，使用 [可复制的 AI 安装请求](docs/GETTING_STARTED.md#交给-ai-的请求)；仓库也有 [AGENTS.md](AGENTS.md) |
| 更新已经部署好的实验室 Ubuntu 电脑 | [校园版更新说明](deploy/linux/README.md)：自动备份、迁移、清理旧删除数据、重启服务 |
| 一台从未部署过的正式服务器 | [部署说明](docs/DEPLOYMENT.md)；不能直接运行校园版更新脚本 |
| 和同学一起修改代码 | [协作说明](CONTRIBUTING.md) |

**从仓库下载的是源码，不是装好环境的整机包。** Python、Docker 安装程序及离线镜像不在 Git 中；首次安装需要联网下载依赖。账号、数据库、老师原始题目包、学生提交和 `.env` 也不在 Git 中。新电脑可以自己生成测试账号、运行自动化测试；手动测试老师的真实章节时，另行取得题目 ZIP。

此前发送的 `Ubuntu24部署包_20260930` 是首次部署用的离线材料包；`Ubuntu24更新包_20261006_*.zip` 是本仓库对应提交的源码快照。**从当前分支下载的最新源码已经包含更新脚本，不必再找另一份更新 ZIP。** 校园更新依赖学校电脑原有的 `/opt/coursejudge`、运行镜像和配置。

## 当前功能

- 管理员：教师账号 CRUD、按教学班设置作业管理/成绩查看/报表导出权限；教学班 CRUD；学生单个 CRUD、CSV/XLSX 预览导入、批量加班/移班/启停/删除；数据字典及字典项 CRUD。
- 教师：创建时选择机器批阅或非机器批阅；同一个上传位置分别显示“机器批阅包”或“非机器批阅包”；支持逐题人工评分与评语、班级清单、统计汇总及 CSV 导出。
- 学生：机器批阅作业上传单个 UTF-8 `.py`；第 10 章人工批阅作业上传包含 `1001.py`～`1005.py` 的 ZIP，提交后查看人工分数和评语。
- 只开放三种角色。助教、补交审批、题目审核、成绩发布批次、v1/v2 等旧入口不在当前网站显示或路由中。
- 修改作业可调整时限；没有提交时可重新上传完整题目包。两种 ZIP 作业都可在“修改作业”页选择包内单个文件生成新版本。机器批阅只有 Word 说明文档变更不重评；`sample*.py`、参考答案、函数清单或测试数据变更须经 Docker 验证，成功后自动重评已有提交并保留旧成绩记录，失败则继续使用旧版本。非机器批阅材料更新直接生效，不调用 Docker，也不改动已有人工成绩。重评期间显示成功、剩余和失败数量，全部成功后进度提示自动收进版本更新记录。已有提交后若要整体换成另一套批阅模板，仍应新建作业。
- 每题按通过用例数占该题全部用例的比例计分，与原批卷器一致；返回值严格检查类型，浮点数和复数允许 `1e-6` 误差。当前结果取最后一次提交。未批阅/批阅异常是“—”，不会当作 0 分；均分只统计本班已批阅学生。
- 删除账号、班级、作业时实际清理相应数据库关系与专用文件；教学班归档保留数据，所有角色的日常页面与旧链接隐藏该班内容，管理员在归档页取消勾选后恢复。
- 名单导入后显示处理结果；同一班级的名单、人数和报表统一统计口径，支持页码跳转与每页条数。管理员总名单统计全部日常可见学生账号（含未分班），并显示所属教学班；选定具体班级后才是该班人数。管理员名单页不显示“本班作业”。
- 教师可查看机器批阅的期望结果及实际返回值；学生端仍不显示答案。两种批阅方式都支持按班打包下载每名学生最后一次提交；人工答案 ZIP 会直接展开到“学号_姓名_提交次数”目录。保留教师均分、最高/最低分及分布图。
- 评分标准由题目分析智能体生成，知识点统一为《Python教学Tag库》标准名（`tools/taglib/`，词表见 `data/Python教学Tag库_v1.0.md`）；学生每次提交生成代码质量评测报告：六轴“考察重点”雷达图 + 逐题明细（机器可判定的知识点 ✓/✗、缺陷所在行与修改建议）。用户未配置个人大模型时只用规则兜底，结果标注来源。
- 学生端“弱项练习”按任务区分：取每个任务**第一次提交**评测报告逐题明细里的缺陷，归到 Tag 库对应知识点作为该任务弱项，再据此从题库或大模型生成该任务的训练题；训练题不计入正式成绩。
- 大模型为**用户自备**：只有“教师生成评分标准”和“学生生成弱项训练题”两处调用大模型；两者都在点击按钮时弹出配置窗口，可自选服务商（DeepSeek、通义千问、Kimi、OpenAI 或任意 OpenAI 兼容端点）并填写自己的 API Key，配置只对本人生效，页面只回显打码 Key。

## 本地运行

需要 Python 3.12；本地默认 SQLite（`DATABASE_URL` 留空），前端无需 Node 构建。机器批阅需要可用的 Docker Linux 容器引擎和 `python:3.12-slim` 镜像；**只打开网页不代表批阅已启动**。完整安装说明见 [新电脑安装与测试](docs/GETTING_STARTED.md)。

### 1. 准备虚拟环境与依赖（仅首次）

```powershell
cd 仓库根目录
py -3.12 -m venv .venv                       # 或 python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.txt
Copy-Item .env.example .env
```

依赖全部收在 `requirements/` 目录：`base.in` 是宽松版本区间，`base.txt` 是精确锁定（含传递依赖，Docker 镜像与部署用它），`dev.txt` 在 `base.txt` 之上追加开发工具（含 pylint 与 matplotlib，缺失时缺陷检测与雷达图会降级）。日常安装用 `dev.txt` 即可，它已包含 `base.txt`。`.env` 中按需填写 `REDIS_URL`（留空则用本地文件缓存）、`PRIVATE_STORAGE`（留空默认 `.runtime/private`）、`LLM_TIMEOUT`。`.env` 不进 Git。

**大模型不再写在 `.env` 里**：每位用户登录后点击侧边栏“配置大模型”，选择服务商（DeepSeek、通义千问、Kimi、OpenAI 或任何 OpenAI 兼容端点）并填写自己的 API Key。配置保存在数据库中（`UserLLMConfig`），只对本人生效；评分标准智能体使用教师自己的配置，训练题智能体使用学生自己的配置，未配置时只能走规则兜底。页面只回显打码后的 Key。

### 2. 初始化数据库

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

### 3. 启动网页服务（终端 A，必须）

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

出现 `Starting development server at http://127.0.0.1:8000/` 后浏览器访问。开发时**不要加** `--noreload`，改代码会自动重启；该终端需要一直开着。

### 4. 启动自动批阅工作进程（终端 B，机器批阅必须）

```powershell
docker info                                  # 确认 Docker 引擎可用
docker pull python:3.12-slim                 # 首次或镜像缺失时执行
.\.venv\Scripts\python.exe manage.py run_judge
```

没有它，学生提交会一直停在“排队中”，训练题也不会产生批阅结果。没有可用 Docker 时仍可管理网站、收取作业与人工批阅，但机器批阅不会完成；系统不提供在宿主机直接执行学生代码的降级路径。

### 5. 一键脚本（可选）

```powershell
.\scripts\start.ps1          # 先迁移，再启动网页服务
.\scripts\start.ps1 -Worker  # 启动自动批阅工作进程
.\scripts\check.ps1          # check + 迁移检查 + 测试
```

### 6. 停止服务

两个终端各自 `Ctrl + C`。后台启动的进程可统一清理：

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'runserver|run_judge' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### 7. 日志与故障排查

| 位置 | 内容 |
| --- | --- |
| 终端输出 | 手动启动时的实时日志，排查首选 |
| `.runtime/webserver.log`、`.runtime/webserver.err.log` | 用 `Start-Process` 后台启动时的输出 |
| `.runtime/judge.log`、`.runtime/judge.err.log` | 批阅工作进程的后台输出 |
| `.runtime/logs/exception.log` | ERROR 级异常及完整堆栈，10 MB × 5 轮转 |

| 现象 | 原因 |
| --- | --- |
| `127.0.0.1 拒绝连接` | 网页进程未启动或已退出 |
| `WinError 10048` 端口被占用 | 已有实例在跑，先停旧进程 |
| 提交一直“排队中” | `run_judge` 未运行 |
| `DOCKER_UNAVAILABLE` | Docker Desktop 未启动或 `python:3.12-slim` 镜像缺失 |

学生源码、测试用例、评分标准与评测报告等私有文件存放在 `PRIVATE_STORAGE`（默认 `.runtime/private/objects/`），数据库只保存键名。`.runtime/` 整体不进 Git，备份时必须与数据库同时进行。测试已把存储指向临时目录，不会污染真实数据；长期使用后可用下述脚本预览或清理数据库不再引用的孤儿文件。

```powershell
.\.venv\Scripts\python.exe scripts\clean_orphans.py            # 只统计，不删除
.\.venv\Scripts\python.exe scripts\clean_orphans.py --delete   # 执行删除
```

### 新建本地测试账号

| 身份 | 用户名 | 初始密码 |
| --- | --- | --- |
| 管理员 | admin | 123456 |
| 教师 | teacher | 123456 |
| 学生 | student | 123456 |

**三个账号首次登录都必须修改密码才能进入业务页面。** 管理员新建/批量导入账号默认也使用 `123456`，可另设临时密码；当前不开放学生自行注册，不需要邮箱。

账号和上传数据不随 Git 同步，下载源码后不会自动出现上述账号。**只在自己的全新、无数据测试库中**，按安装说明确认账号数为 0 后执行一次：

```powershell
.\.venv\Scripts\python.exe manage.py reset_local_accounts --confirm-reset
```

该命令会停用所有现有账号并移出清单，再创建以上三账号及测试班级关系。因此不能用于学校更新、日常启动或已有同学数据的环境。正式新部署使用 `bootstrap_admin` 创建自定密码的管理员。旧 `seed_demo` 仅用于历史开发，不用于当前版本。

用户明确要求本阶段保留可读密码：`User.recovery_password` 保存明文副本，只有管理员的账号编辑页可查看（响应禁止缓存），登录校验仍使用 Django 哈希。首次改密和管理员重置同步更新该副本；密码不进报表或审计日志。`STORE_RECOVERY_PASSWORDS` 在 DEBUG 模式默认开启、非 DEBUG 默认关闭。后续上线前关闭该开关并清除历史明文副本；这项临时设计不能视为已完成生产安全处理。

## 章节批阅配置

用户提供的 `01-作业20260922.rar` 在本机解压后导入，参考答案、测试数据、数据库、学生源码和密码均不进入 Git。

```powershell
.\.venv\Scripts\python.exe manage.py import_course_packages '你的已解压章节根目录'
```

教师创建机器批阅作业时上传完整章节 ZIP。网站只静态解析 ZIP，标准答案由工作进程在 Docker 中验证一次并生成私有标准结果；等待中的学生提交会在验证通过后自动入队。后台仍可为历史作业另行关联：

```powershell
.\.venv\Scripts\python.exe manage.py bind_course_package 作业ID chapter-02
```

该命令将此前待接入的提交加入队列；已开始批阅的作业不能整体更换配置，但可通过“更新单个文件”生成新版本并在验证后自动重评。第 1～9 章使用函数式机器批阅包；第 10 章上传题目和数据材料 ZIP，由学生提交五个独立源码组成的答案 ZIP，教师逐题人工评分。清单第二列作为每题满分，总分按章节累加，不自动折算为百分制。

压缩包中的 `gold.py` 是参考函数实现，并非完整网站批阅服务。适配器读取函数清单和字面量参数，先在独立容器中验证参考函数并缓存带类型的标准结果。每份学生提交只启动一个容器、加载学生文件一次，并在容器内依次执行全部用例；容器外按原批卷器规则比较。学生容器不包含参考答案或预期输出。单参数用例整体传入；多参数按顺序展开。

第 6 章 patch 与原配置相同；第 4 章存在未列入清单的额外 data 文件，当前仅按清单启用，不擅自加题。文件缺失、参考程序异常、Docker 异常不会记学生 0 分。

### 启动自动批阅工作进程

启动命令与依赖见上文[本地运行](#本地运行)第 4 步；本章节只补充部署差异。需要 Docker Linux 容器引擎，也可用 `./scripts/start.ps1 -Worker` 开启工作进程。没有可用 Docker 时，可管理网站、收取作业并进行非机器批阅，机器批阅不会正常完成；没有在主机直接执行学生代码的降级路径。学校现有环境使用 Docker、MySQL、Redis 和 Celery，按 [校园更新说明](deploy/linux/README.md) 更新。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test school.tests
```

测试会把私有存储重定向到临时目录，不会在 `.runtime/private` 留下文件；批量跑完后可用 `scripts/clean_orphans.py` 核对存储健康度。`school.tests` 现有 23 个 `test_*.py`，其中只有 `test_docker` 需要 `RUN_DOCKER_TESTS=1`，两种系统的具体命令见安装指南。2026-11-14 已验证 SQLite 业务回归（600+ 项测试）、Tag 化评分标准与评测报告、按任务弱项练习；这不替代学校目标机验收及实际班级集中提交压测。迁移当前到 `0018_userllmconfig`（`CONTRIBUTING.md` 写的 `0009` 是旧编号，改模型前以 `school/migrations/` 实际编号为准）。

## 代码地图：每个板块做什么、怎么做

### 入口与路由

| 位置 | 功能 | 实现方式 |
| --- | --- | --- |
| `config/urls.py` | 全站唯一对外入口 | 先挂 `login/`、`logout/`、`password/`、`health/` 四个认证视图，再 `include` 四个 portal 路由模块 |
| `school/portal/urls_common.py` | 仪表盘、个人设置、大模型配置 | 四个路由模块都用 `path('', include(...))` 平铺到根路径，**没有 namespace**，URL name 全局唯一 |
| `school/portal/urls_administration.py` | 管理员页面 | `teachers/` 与 `students/` 复用同一个 `people` 视图，靠传 `{'kind': ...}` 区分；`work_export` 是 `work_results` 带 `{'export': True}` 的别名路由 |
| `school/portal/urls_teaching.py` | 教师端作业、结果、导出 | 作业 CRUD、`work/<pk>/package-file/`、`submissions.zip`、`results/` |
| `school/portal/urls_learning.py` | 学生端提交、结果与知识图谱 | `knowledge/`（知识图谱）、`practice/`（弱项练习）、`work/<pk>/`、`entries/<pk>/`、质量报告与雷达图 |
| `config/legacy_urls.py` | 旧门户 50 条路由 | 不被任何 URLconf `include`；只有 3 个测试模块用 `override_settings(ROOT_URLCONF='config.legacy_urls')` 打开 |

### 数据层

| 模块 | 功能 | 实现方式 |
| --- | --- | --- |
| `school/models.py` | 账号、角色、班级、授权、审计，以及旧版判题表 | `User` 继承 `AbstractUser` + 自定义 `AccountManager`；`db_table` 沿用 `users`/`classes`/`judge_runs` 等旧表名，迁移不重建表；末尾再导出 14 个 `course_models` 模型，所以 `school.models` 是统一入口（`QualityReport`、`CourseworkRubric`、`PracticeCaseResult` 只能从 `school.course_models` 导入） |
| `school/course_models.py` | 当前业务 18 个模型 | 字典、`EvaluationPackage`、`Coursework`/`CourseworkItem`、`CourseworkSubmission`、逐题 `CourseworkQuestionResult` 与逐用例 `CourseworkCaseResult`、`CourseworkPackageUpdate`（包更新状态机）、`CourseworkGradeHistory`（成绩历史）、`PrivateFileCleanup`（待删文件队列）、`QualityReport`、`CourseworkRubric`、练习五件套；文件不存路径只存私有存储键名，题目与分值用 `JSONField` 快照 |
| `school/accounts.py` | 建号时同步明文密码副本 | `AccountManager._create_user_object` 在 `STORE_RECOVERY_PASSWORDS` 开启时写入 `recovery_password`，登录校验仍用 Django 哈希 |
| `school/storage.py` | 私有文件存储（不是 Django Storage 后端） | UUID 键写入 `PRIVATE_STORAGE/objects/`，`open('xb')` 防覆盖，读取前用 `is_relative_to()` 拦路径穿越；数据库只保存键名 |
| `data/` | 题库与标签数据源（只读，不被 Django 加载） | `Python题库.md`（44 题 / 440 用例）、`Python教学Tag库_v1.0.md`（词表）、`qbank-tags-v2.json`（逐题打标）、`qbank-package/`（判题数据样张）；路径由 `question_bank.bank_path()` 与 `tools/taglib/loader.py` 的 `DATA_DIR` 常量定位 |

### 权限、中间件与请求上下文

| 模块 | 功能 | 实现方式 |
| --- | --- | --- |
| `school/portal/access.py` | 当前权限判定 | `role()` 按 `admin > teacher > student` 取首个命中；`require_role()` 不符即抛 `PermissionDenied`；`classes_for(user, action)` 按 `ClassStaff` 授权位与 `expires_at` 过滤，学生传 `action` 时返回空 |
| `school/portal/common_views.py` | `work_for(user, pk, action)` 作业级鉴权单点 | 统一过滤软删与归档；学生要求作业 `status == 'open'` 且在班；教师只看 `can_<action>` 授权位 |
| `school/middleware.py` | `AccountMiddleware` | 从 session 恢复 `active_role` 并确认仍在 `UserRole` 中；停用账号强制登出；`must_change_password` 时除改密、登出、静态文件外一律重定向 |
| `school/context.py` | 模板上下文处理器 `common` | 注入角色、打码后的大模型配置、未读通知数；按 `request.urlconf` 在 `school/base.html` 与 `portal/base.html` 之间切换 |
| `school/permissions.py` | 旧门户的权限函数 | 纯函数 + ORM `Q` 查询，供 `school/views.py` 使用；新代码改用 `portal/access.py` |

### 批阅执行

| 模块 | 功能 | 实现方式 |
| --- | --- | --- |
| `school/judge.py` | 单用例沙箱执行器 | `docker run` 带 `--network none`、`--read-only`、`--cap-drop ALL`、`--user 65534:65534`、`--pids-limit/--cpus/--memory/--ulimit`，代码只读挂载，stdin 喂输入，两个线程按 `output_kb` 截断输出；超时 = 题目限时 + 容器启动宽限（默认 10 秒）；判定顺序 OLE→TLE→启动失败→MLE→CE→RE→AC/WA；`finally` 强制 `docker rm -f`；基础设施异常写 `error_code` 且 `base_score=None`，**不记学生 0 分**；`verify_reference()` 先把镜像固定成 sha256 再跑参考解 |
| `school/portal/grading.py` | 当前批阅编排与计分 | `validate_package()` 在容器里跑参考答案、固化带类型的期望值；`batch_harness()` 让一份提交只起一个容器、容器内循环全部用例；`grade_submission()` 写逐题/逐用例结果，得分 = `points × 通过用例数 / 总用例数`；`evaluate(entry_id)` 用条件 `update()` 抢占 `pending → running` 并写心跳；`recover_stale()` 回收超时任务 |
| `school/tasks.py` | Celery 任务与兜底巡查 | `@shared_task` 定义验证/批阅/派发任务，业务代码在 `transaction.on_commit` 后投递；投递失败回退状态；`cache.add` 做参考验证的防重复锁 |

> `school/judge.py` 里的 `evaluate()` 走的是旧 `JudgeRun` 路径，口径为“全部正式用例 AC 才给满分”；当前按用例比例计分在 `school/portal/grading.py`，两者不要混用。

### 三端视图

| 模块 | 功能 | 实现方式 |
| --- | --- | --- |
| `school/portal/common_views.py` | 仪表盘与全站公共件 | `dashboard` 按角色分三套看板（管理员统计卡、教师待批阅/异常计数、学生作业看板）；`page/table/form_page/link` 统一渲染，`csv_response`+`safe_csv` 输出带 BOM 且防公式注入的 CSV，`private_download` 限私有目录内文件 |
| `school/portal/administration_views.py` | 管理员账号、教学班、名单、授权、归档、数据字典 | 每个视图首行 `require_role(user, 'admin')`；名单导入走两段式“预览 → 确认”；删除字典项前先查是否被业务引用 |
| `school/portal/teaching_views.py` | 教师端作业与成绩 | `@role_required('teacher')` 装饰器；两套批阅包差异封装进 `AutomaticPackageStrategy` / `ManualPackageStrategy`，由 `package_strategy(work)` 按 `grading_mode` 选择；`_prepare_rubric()` 在上传时生成评分标准 |
| `school/portal/learning_views.py` | 学生端提交与共享结果页 | `work_detail` 提交、`work_file` 下载说明/模板/材料、`entry_detail` 逐题与逐用例结果（教师在此看到期望与实际并提交 `ManualReviewForm`）、`entry_retry` 重判 |
| `school/portal/quality_views.py` | 代码质量报告 | 报告页、雷达图 PNG、Markdown 下载；鉴权集中在 `_entry_for`，文件直接流式读私有存储 |
| `school/portal/rubric_views.py` | 评分标准页 | 只读展示与 `.md` 下载；历史作业用规则兜底补一份，不调用大模型 |
| `school/portal/practice_views.py` | 弱项练习 | 首页、答题、提交、结果；提交后**同步**调用 `practice_agent.grade_attempt()` 走 Docker 判题 |
| `school/portal/knowledge_views.py` | Python 知识图谱（仅学生） | `require_role(user, 'student')`；`knowledge_graph.build_graph()` 读 `data/python_graph.json` 并计算放射布局坐标，模板用 ECharts 渲染，支持放射/力导向双布局 |
| `school/portal/llm_views.py` | 个人大模型配置 | 保存/清除只作用于当前用户；跳转用 `url_has_allowed_host_and_scheme` 防开放重定向 |

### 业务服务层

| 模块 | 功能 | 实现方式 |
| --- | --- | --- |
| `school/portal/submission_services.py` | 提交受理与人工批阅 | `submit()` 用 `request_id` 幂等、校验次数上限、按 `grading_mode` 分叉状态（机器 `pending`/`waiting`，人工 `review`）；`review_manual_submission()` 写人工分数、评语与批阅人 |
| `school/portal/coursework_services.py` | 作业与题目包落库 | `save_work`、`save_uploaded_package`、`snapshot()` 把题目、分值、期望结果冻结进提交 |
| `school/portal/package_update_services.py` | 更新包内单个文件的状态机 | `create_package_update → mark_validating/error → activate_package_update`：升 `revision`、重建题目、归档 `CourseworkGradeHistory`、重排批阅队列，并触发评分标准重建 |
| `school/portal/reporting_services.py` | 名册与统计 | `roster_rows(work)` 汇总每人最后一次提交与统计量；`score_distribution` 供分布图 |
| `school/portal/downloads.py` | 按班打包下载 | 生成 `submissions.zip` 并附 `打包结果.csv`；机器批阅打 `.py`，人工 ZIP 展开到“学号_姓名_提交次数”目录 |
| `school/portal/parsers.py` | 上传材料解析 | 解析 ZIP / DOCX / PDF / 文本；`_safe_zip_files()` 限制成员数、展开总量与单文件大小，防压缩炸弹 |
| `school/portal/rosters.py` | 学生统计口径 | `students_in`、`with_student_counts`（`annotate`）、`visible_students`（只在已归档班的学生不出现） |
| `school/portal/result_display.py` | 批阅结果可读化 | 把 typed JSON 递归渲染成 Python 字面量，只格式化不反序列化、不执行，带深度与长度截断 |
| `school/portal/pagination.py` | 分页归一 | 限定 `per_page ∈ {10,30,50,100}`，返回省略页码并保留原有过滤参数 |
| `school/imports.py` | 名单 CSV/XLSX 导入 | `preview_import` 逐行产出错误、`commit_import` 用 `transaction.atomic` + `select_for_update`；`openpyxl` 只读模式并先用 `ZipFile` 限条目数与体积 |
| `school/portal/services.py`、`school/portal/forms.py` | 兼容再导出 | 只做 import 转发，保证旧调用路径可用；新代码应直接导入领域模块 |

### 智能体、质量报告与练习

| 模块 | 功能 | 实现方式 |
| --- | --- | --- |
| `school/portal/llm_client.py` | 用户自备大模型 | 读取当前用户的 `UserLLMConfig`，按 OpenAI 兼容协议 `chat()`；`mask_key()` 只回显打码 Key；未配置抛 `LLMNotConfigured` |
| `school/portal/rubric_agent.py` | 题目分析智能体（评分标准） | `build_messages → chat → parse/normalize → render_markdown`；无 Key 时 `rule_based()` 用 `ast` 解析参考代码兜底；`prepare_for_upload` / `schedule_regeneration` 在后台线程重建 |
| `school/portal/quality_service.py` | 代码质量报告与缓存 | `supported(entry)` 只认机器批阅单文件；`generate()` 用“源码 sha256 + 量表/知识点/能力签名”判断能否复用旧报告；`schedule_generate` 在 `on_commit` 后起守护线程 |
| `school/portal/knowledge_profile.py` | 知识点画像 | 按任务聚合逐题缺陷 → 弱项 / 已掌握 |
| `school/portal/practice_agent.py` | 弱项练习智能体 | `generate_practice_plan()` 优先大模型，失败或离线时用 `question_bank` 规则兜底；`grade_attempt()` 在 Docker 里跑练习用例 |
| `school/portal/question_bank.py` | Markdown 题库解析 | `bank_path()` 定位 `data/Python题库.md`；`load_bank()` 缓存解析结果，按 Tag 匹配选题 |
| `tools/code_quality_agent/` | 静态评测工具（不依赖 Django） | LangGraph 状态图编排 pylint + AST 考点检测 + 题意规则，另见该目录 README |
| `tools/taglib/` | Tag 库加载与归一 | 解析 `data/Python教学Tag库_v1.0.md`，精确/包含归一，读 `data/qbank-tags-v2.json` 做题目标签反查 |

### 前端

| 位置 | 功能 | 实现方式 |
| --- | --- | --- |
| `templates/portal/` | 三端 21 个页面 | `base.html` + 通用件 `form/table/pagination/confirm` + 业务页；模板继承渲染，**没有前端构建步骤** |
| `static/app.css`、`static/portal.js` | 站点样式与三端交互 | 原生 CSS 设计令牌 + 少量原生 JS；`practice_editor.*` 是练习代码编辑器，`vendor/echarts.min.js` 供知识图谱绘图 |
| `templates/school/`、`templates/403.html`、`templates/404.html` | 旧门户模板 | 只有 `login.html`、`form.html`、`base.html` 仍被当前登录页使用，其余随旧视图废弃 |

### 命令行

| 命令 | 功能 |
| --- | --- |
| `run_judge` | 开发用轮询工作进程：恢复僵尸任务、验证批阅包、批阅提交、验证参考答案；`--once` 跑一轮 |
| `bootstrap_admin` | 交互式创建首个管理员，同名已存在即报错 |
| `reset_local_accounts` | 只能在空测试库执行：停用并重命名现有账号，重建三账号与测试班级 |
| `import_course_packages` | 扫描已解压章节目录，静态解析为 `EvaluationPackage`；同 digest 复用，异 digest 生成 `chapter-XX-<digest>` |
| `bind_course_package` | 把历史作业关联到批阅包，并把 `waiting` 提交转入批阅队列 |
| `analyze_rubric` | 调题目分析智能体生成评分标准；`--offline` 走规则兜底 |
| `refresh_abilities` | 按各作业知识点重新归纳雷达图六大主能力 |
| `upgrade_rubric` | 用已存知识点与维度重渲染评分标准 Markdown（不调大模型），默认预览 |
| `purge_deleted_data` | 清理逻辑删除记录与无引用私有文件，默认预览，`--apply` 才执行 |
| `seed_demo` | 仅 `DEBUG=true`：创建演示班、四角色账号与两道题；当前版本不使用 |

### 测试

测试分两套：`school/tests/`（23 个 `test_*.py`，项目自身回归，655 项）与根目录 `tests/`（3 个模块，软件测试实践作业的单元/等价类/场景用例，60 项，配套 `tests/TEST_PLAN.md`）。两套都没有 `conftest.py`，夹具由各文件 `setUp` 自建。

| 分组 | 模块 | 覆盖内容 |
| --- | --- | --- |
| 现行三端回归 | `test_portal`、`test_roster_scope`、`test_review_changes`、`test_package_regressions`、`test_auth_views`、`test_llm_config`、`test_rubric_views`、`test_rubric_agent`、`test_quality_report`、`test_practice_agent` | 页面、权限、上传提交、包更新、名册口径、认证、大模型配置、评分标准、质量报告、弱项练习 |
| 旧路由回归 | `test_legacy_views`、`test_teaching`、`test_workflows` | 用 `override_settings(ROOT_URLCONF='config.legacy_urls')` 跑旧门户全流程 |
| 批阅与沙箱 | `test_judge_unit`、`test_judge_sandbox`、`test_grading_unit`、`test_docker` | 执行器状态机与 Docker 命令（mock）；`test_docker` 是唯一需要 `RUN_DOCKER_TESTS=1` 的真实容器验收 |
| 解析与命令 | `test_parsers`、`test_imports_and_commands` | 上传材料解析/校验、名单导入、管理命令 |
| 纯函数 | `test_taglib`、`test_quality_rules`、`test_quality_agent_internals` | Tag 加载归一、题库反查、题意规则、评测图内部 |
| 基础设施 | `test_exception_logging` | ERROR 及以上落盘到轮转 `exception.log` |

### 教师端视图的设计模式（`school/portal/teaching_views.py`）

> 注意：这一节描述的是当前业务模块 `school/portal/teaching_views.py`。旧门户的 `school/teaching_views.py` 属另一份实现，只有 `config/legacy_urls.py` 可达，不含下列结构。

教学端视图曾存在三类重复：每个视图手写角色检查、`work_package_file` 按批阅方式的 if/else 分支散落在权限、归档路径、解析器、成功提示、页面说明 5 处、`works` 与 `results` 重复的班级筛选逻辑。重构时**行为保持不变**（提示文案、重定向、403 条件逐字一致），用以下模式收敛：

**1. 装饰器模式 —— 角色检查收敛**

新增 `role_required(*roles)` 装饰器工厂和 `teacher_required = role_required('teacher')`，替代各视图重复的 `if role(...) != 'teacher': raise PermissionDenied`：

```python
@login_required
@teacher_required          # 或 @role_required('teacher', 'admin')
def work_edit(request, pk=None): ...
```

视图只需叠加强调顺序：`@login_required` 在前、角色装饰器在后。`works` 是例外——学生访问要跳转仪表盘而非 403，因此保留内联判断。

**2. 策略模式 —— 按批阅方式分流**

机器批阅与非机器批阅在“更新单个文件”流程中的差异封装为同接口的两个策略类，由 `package_strategy(work)` 按 `grading_mode` 选择：

| 策略类 | archive_path | member_choices | description | success_message |
| --- | --- | --- | --- | --- |
| `AutomaticPackageStrategy` | 批阅包路径（缺失即 403） | `package_member_choices` | Docker 重评说明 | 含验证中/已生效分支 |
| `ManualPackageStrategy` | 材料路径（缺失即 403） | `manual_member_choices` | 直接生效说明 | 无需 Docker 分支 |

主视图 `work_package_file` 不再出现任何批阅方式判断；新增批阅方式时只需增加一个策略类。

**3. 公共辅助函数抽取**

- `_filtered_by_classroom(request, queryset)`：`works` 与 `results` 共用的“GET classroom 参数 → 过滤查询集”
- `_export_row(work, row)` / `_results_csv(request, work, rows)` / `EXPORT_HEADERS`：班级结果 CSV 导出的行组装与完整导出职责，`work_results` 主函数只保留流程控制，且导出分支提前返回、不再白算页面才需要的分数分布

**4. 同文件新增的异步触发点**

- `_prepare_rubric(request, work, auto_llm)`：`work_edit` 保存成功后调用（`auto_llm` 控制是否尝试大模型）；已有评分标准跳过，未配置大模型提示后跳过，失败只警告不阻塞上传
- 同上模式的 CSV 导出集中在 `_export_row` / `_results_csv` / `EXPORT_HEADERS`（`teaching_views.py:335`）
- 非机器批阅材料更新成功后调用 `rubric_agent.schedule_regeneration(work.pk)`，机器批阅由 `activate_package_update` 在验证生效后触发（后台线程，失败保留旧标准）

以上行为均有测试覆盖：`school/tests/test_rubric_agent.py`（自动生成与重建）、`school/tests/test_quality_report.py`（提交后后台分析）、`school/tests/test_portal.py` / `test_review_changes.py`（视图回归）。

本轮方案与交接见 [需求说明](docs/REQUIREMENTS.md)、[A 开发交接](docs/A_HANDOFF.md)、[验证记录](docs/VALIDATION.md)。代码仓库：[smart-edu-app](https://github.com/shershen12138/smart-edu-app)。
