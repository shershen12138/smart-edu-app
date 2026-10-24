# 同学的新电脑：安装、启动和测试

适用于自己的 Windows 或 Ubuntu 24.04 开发电脑。这里启动的是独立测试环境，不会连接学校数据库。前提是使用下面的本地配置，并确认没有指向远程数据库的环境变量。

如果正在操作学校已部署的 `/opt/coursejudge`，直接看 [校园更新说明](../deploy/linux/README.md)，不要执行本页的测试账号重置命令。

## 1. 下载正确的代码

在 Gitee 页面选择 **`codex/simplified-coursework`** 分支，再下载 ZIP 并解压。不要默认选 `main`。私有仓库需要仓库访问权限。

如果已经安装 Git，也可以在准备存放项目的文件夹打开终端，执行：

```bash
git clone --branch codex/simplified-coursework --single-branch https://gitee.com/arongmiao/python-course-judge.git
cd python-course-judge
```

后续“项目目录”指同时包含 `manage.py`、`school`、`requirements.lock.txt`、`README.md` 的文件夹。ZIP 解压后如果外面还有一层文件夹，要进入里面这一层。

## 2. 准备软件

| 项目 | 是否需要 | 用途 |
| --- | --- | --- |
| Python 3.12，64 位 | 必需 | 网站、迁移与测试 |
| Docker Linux 容器引擎 | 测试机器批阅时必需 | 隔离执行参考程序和学生代码 |
| Git | 可选 | 下载 ZIP 可以不用；协作修改建议安装 |
| MySQL / Redis / Node.js | 本地测试不需要单独安装 | 本地使用 SQLite 与 `run_judge`；网页没有 Node 构建步骤 |

Windows 的 Python 从 [Python 官方下载页](https://www.python.org/downloads/windows/) 获取 3.12 的 64 位安装器，安装时保留 Python Launcher。Docker 使用 [Docker Desktop 官方 Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)，启动后需要 Linux 引擎可用。若提示未启用虚拟化，先处理 BIOS / WSL 等前置条件，不能靠安装 Python 解决。

Ubuntu 24.04 若缺少 Python 虚拟环境组件，在系统“终端”执行：

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip
```

Ubuntu 的 Docker 依照 [Docker Engine 官方安装说明](https://docs.docker.com/engine/install/ubuntu/) 安装。先检查已有 Docker，避免同时混装 Docker Desktop、系统 Docker 和不同软件源。运行本地批阅的用户需要能直接执行 `docker info`；权限不足时按官方 Linux 安装后步骤处理，不要改成在主机直接执行学生源码。

## 3A. Windows：第一次创建环境

在资源管理器中打开**项目目录**，地址栏输入 `powershell` 后回车。下面每条命令执行成功后再运行下一条；有报错先保留完整输出处理。

```powershell
Get-Item manage.py, requirements.lock.txt
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

在记事本确认以下字段，用于自己的本地测试；保存后关闭：

```dotenv
DEBUG=true
ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=
REDIS_URL=
```

不要把学校的 `.env` 复制过来。已有 `.env` 不会被上述复制命令覆盖；如果里面已有数据库地址，应先确认用途，不要继续重置账号。系统环境变量会优先于 `.env`，AI 排查时也要核对，但不要把其中的密码公开输出。

继续在同一 PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py shell -c "from school.models import User; print('账号数量:', User.objects.count())"
```

**仅当这是全新的本地测试库、账号数量为 0 时**，执行一次：

```powershell
.\.venv\Scripts\python.exe manage.py reset_local_accounts --confirm-reset
```

已有账号则跳过这条。该命令会停用原账号，不能用来修复登录问题。本文不要求激活虚拟环境，直接使用 `.venv` 中的 Python 即可，也无需更改 PowerShell 执行策略。

## 3B. Ubuntu 24.04：第一次创建环境

在文件管理器中打开**项目目录**，空白处右键“在终端打开”。逐条执行：

```bash
ls manage.py requirements.lock.txt
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
test -f .env || cp .env.example .env
nano .env
```

确认 `.env` 中 `DEBUG=true`、`ALLOWED_HOSTS=127.0.0.1,localhost`，`DATABASE_URL` 与 `REDIS_URL` 均留空。`nano` 中按 Ctrl+O、回车保存，再按 Ctrl+X 退出。已有配置和环境变量处理原则与 Windows 相同。

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py check
.venv/bin/python manage.py shell -c "from school.models import User; print('账号数量:', User.objects.count())"
```

**仅在全新、无账号的本地测试库执行一次：**

```bash
.venv/bin/python manage.py reset_local_accounts --confirm-reset
```

## 4. 启动网页：终端 A

仍在项目目录，选择自己的系统运行一条，保持这个终端开着。

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Ubuntu 终端：

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

在**这台电脑的浏览器**打开 <http://127.0.0.1:8000/>。新测试库中有 `admin`、`teacher`、`student` 三个账号，初始密码均为 `123456`，首次登录要求修改密码；改过之后使用自己设置的密码。老师和学生已加入一个测试教学班。

这是本机测试地址，别人不能用自己电脑的 `127.0.0.1` 访问你的服务。要让全校访问，需要正式部署及校内网络路由、端口放行。

## 5. 启动机器批阅：另开终端 B

**终端 A 不要关闭。** 再在同一个项目目录打开第二个 PowerShell / Ubuntu 终端。先运行：

```bash
docker info
docker version --format '{{.Server.Os}}'
docker pull python:3.12-slim
```

第二条应显示 `linux`，三条均成功后再启动批阅。`docker pull` 下载镜像只需首次或需要更新时执行。

Windows：

```powershell
.\.venv\Scripts\python.exe manage.py run_judge
```

Ubuntu：

```bash
.venv/bin/python manage.py run_judge
```

出现“评测进程已启动”后保持终端 B 开着。网站先接收提交，工作进程再完成批阅；未启动、Docker 不可用或题目包异常，都会导致机器批阅不能正常完成。非机器批阅可由教师直接评分。

停止时分别在终端 A、B 按 Ctrl+C。下次只需启动这两个进程，不再重建账号。

## 6. 怎么确认安装好了

先检查三个账号能登录并完成首次改密；再做以下测试：

- 管理员：教学班和名单人数一致；创建或导入少量虚构学生；确认成功提示、分页、按班授权，以及归档和恢复。
- 教师：用另行取得的章节 ZIP 新建作业并设置截止时间。机器批阅需要完整题目包；非机器批阅上传含 DOCX 和数据的 ZIP。
- 学生：机器批阅提交对应的 `.py`；第 10 章非机器批阅提交包含 `1001.py`～`1005.py` 的 ZIP。
- 结果：机器批阅完成后，教师能看期望/实际结果，学生不显示答案；教师可对非机器批阅评分，并可对两种作业按班打包下载每名学生最后一次提交。
- 删除测试只操作自己创建的虚构数据。永久删除不会像归档那样可以取消。

**没有老师的题目包也能运行自动化测试**，测试使用自己生成的夹具，不需要真实学生文件。在第三个项目终端执行：

Windows：

```powershell
.\.venv\Scripts\python.exe manage.py test school.tests --noinput
```

Ubuntu：

```bash
.venv/bin/python manage.py test school.tests --noinput
```

看到 `OK (skipped=13)` 表示业务测试通过，13 项真实 Docker 测试尚未运行，不表示完整批阅已通过。Docker 正常后单独验证：

Windows：

```powershell
$env:RUN_DOCKER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test school.tests.test_docker --noinput
Remove-Item Env:RUN_DOCKER_TESTS
```

Ubuntu：

```bash
RUN_DOCKER_TESTS=1 .venv/bin/python manage.py test school.tests.test_docker --noinput
```

2026-10-06 版本共 125 项测试，其中 13 项为真实 Docker 测试；之后数量可能增加。测试使用测试数据库，不能因此在真实学校环境随意执行初始化或清理命令。

## 7. 文件放在哪里，更新包是什么

本地默认 SQLite 文件是 `.runtime/db.sqlite3`；上传内容存放在 `.runtime/private/objects/`，数据库记录对应路径。自己的 `.env` 或环境变量设置了存储目录时，以配置为准。这些内容不会随 Git 同步。

| 下载物 | 能用来做什么 | 不包含什么 |
| --- | --- | --- |
| Gitee 当前分支源码 ZIP / Git 克隆 | 全新本地安装、测试、协作；也包含学校更新脚本 | 软件安装器、依赖环境、真实题目、账号及学生数据 |
| `Ubuntu24更新包_20261006_*.zip` | 某次 Git 提交的源码快照；按学校更新说明使用 | 初装离线软件与基础镜像；后续提交不会自动进入旧 ZIP |
| `Ubuntu24部署包_20260930` | 此前交付的 Ubuntu 首次部署材料 | 不在 Gitee；其中应用源码不是最新版本 |

**更新学校网站：**在已经部署好的 Ubuntu 电脑，下载最新分支源码、解压后，在包含 `manage.py` 的目录执行 `sudo bash deploy/linux/update.sh`。需要原 `/opt/coursejudge` 配置和已安装镜像；脚本会先备份再迁移。完整步骤及失败处理见 [学校更新说明](../deploy/linux/README.md)。仅执行 `git pull` 不会自动替换正在运行的 Docker 网站。

**更新自己的测试环境：**有 Git 的源码目录先检查 `git status`，自己的修改先保存，再 `git pull --ff-only`；停掉两个终端中的进程后，安装 `requirements.lock.txt`、运行 `migrate`，再启动两个进程。保留原 `.env` 和 `.runtime`，不要重新执行账号重置。用 ZIP 更新时应保留原环境和数据，避免把旧文件夹当成可直接删除的临时文件。

## 交给 AI 的请求

把下载的整个源码文件夹交给具有终端执行能力的 AI，然后发送：

> 请先阅读本仓库 README.md、AGENTS.md 和 docs/GETTING_STARTED.md。我现在要在自己的电脑上安装独立测试环境，不是更新学校服务器。先确认操作系统、Python 3.12、Docker Linux 引擎是否可用，以及是否已有 .env、数据库和账号。按对应系统安装依赖、执行迁移；仅在全新空测试库创建 admin / teacher / student 测试账号。分别启动网页与 run_judge，运行系统检查、业务测试和真实 Docker 测试，告诉我网址、初始账号和哪些测试确实通过。保留已有数据及配置，不使用学校数据库；没有题目包时说明缺少材料，不伪造真实批阅结果。遇到需要我点击安装窗口或进入 BIOS 的步骤，说明具体该做什么。

如果要更新学校电脑，用另一段请求：

> 请先阅读 README.md、AGENTS.md 和 deploy/linux/README.md。我现在操作的是已用 Ubuntu24部署包_20260930 安装的学校 Ubuntu 24.04 电脑，需要升级到当前 codex/simplified-coursework 分支。先核对原 /opt/coursejudge、配置、镜像、数据库和备份路径，再执行 deploy/linux/update.sh，并检查网页、数据库迁移与批阅服务。保留现有账号、作业、学生提交和网络配置；不要运行 reset_local_accounts、seed_demo 或重新初始化数据卷。失败时保留完整错误和备份位置，不把初始化作为修复办法。

能读文件、执行终端的 AI 可以实际协助；只有聊天功能的 AI 只能指导你操作。是否已安装成功，以运行检查及网页、批阅结果为准。
