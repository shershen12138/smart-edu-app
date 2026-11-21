# 部署与运行（场景先行）

## 学校已部署好的 Ubuntu 24.04

当前学校方案来自 `Ubuntu24部署包_20260930`：安装在 `/opt/coursejudge`，Docker 内运行 Web、MySQL、Redis、worker 和 beat，Web 经校内 IP 的 HTTP 8000 端口访问。更新使用 [校园版更新说明](../deploy/linux/README.md)，保留原网络、数据卷及账号；只拉源码不会自动替换容器。

## 同学自己的新电脑

请按 [新电脑安装与测试](GETTING_STARTED.md) 操作。该方案用 Python 3.12、SQLite 和本地工作进程，可以在 Windows 或 Ubuntu 上测试，不需要先搭建下面的完整服务器架构。

## 从零部署一台正式服务器

校园更新脚本不支持空机器首次安装。若希望完全复用之前的离线安装流程，需要另行取得 `Ubuntu24部署包_20260930`，完成初装后再用当前源码更新；这个首次部署材料包不在 Git 中。

下面保留的是供维护人员从源码部署的**通用 HTTPS 方案**，使用仓库根目录的 `compose.yaml`，不是当前学校 HTTP 部署的重装步骤。需要先安装 Docker Engine 与 Compose，确定存储位置、域名、反向代理和网络权限。若只想让同学测试功能，使用上一节即可。

## 开发与生产

本地 SQLite 适合单人开发，不作为真实课堂并发验收环境。
生产使用 Linux、MySQL 8.4、Redis 7、Python 3.12 评测镜像。
应用只运行固定的 Python 镜像和标准库。要增加第三方包，由维护者预构建并审核镜像，不允许学生任意安装依赖。

## Docker Compose（Linux 目标机）

复制 `.env.example` 为 `.env`，配置：

```dotenv
DEBUG=false
SECRET_KEY=<使用 Django get_random_secret_key 生成>
ALLOWED_HOSTS=<实际域名>
CSRF_TRUSTED_ORIGINS=https://<实际域名>
TRUST_PROXY=true
MYSQL_PASSWORD=<独立随机数据库密码，仅使用 URL 安全字符>
MYSQL_ROOT_PASSWORD=<另一个独立随机密码>
JUDGE_HOST_STORAGE=/srv/coursejudge-storage
JUDGE_IMAGE=python:3.12-slim
```

生成密钥：`python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`。
不要把结果贴进 Issue 或提交到 Git。
如镜像使用 digest 固定版本，题目保存的运行环境也跟随该配置。

```bash
sudo install -d -m 750 -o 10001 -g 10001 /srv/coursejudge-storage
docker pull python:3.12-slim
docker compose build
docker compose up -d db redis
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py collectstatic --noinput
docker compose run --rm web python manage.py bootstrap_admin
docker compose up -d
```

静态文件在构建镜像时收集（Dockerfile）；运行时 collectstatic 仅用于检查。配置反向代理将 HTTPS 域名转发到本机 `127.0.0.1:8000`。
反代必须覆盖而不是追加客户端传入的 `X-Forwarded-Proto`，应用配置 `TRUST_PROXY=true` 后识别 HTTPS。
MySQL 与 Redis 不向公网暴露；Web 服务没有 Docker socket。
worker 挂载 socket，因此 worker 主机属于受信管理边界。建议评测独立主机，按实际部署共享受限存储并隔离内部服务访问。

## 任务恢复

- 受理提交与待派发记录同一事务提交。派发失败不会丢任务。
- Celery Beat 每 15 秒重派待处理任务；重复队列消息只能抢占一次执行。
- 长时间未启动的排队任务可重新派发；运行中超过 20 分钟无心跳记为系统异常。
- 当前网站由有相应权限的教师在异常提交详情中重试。旧版“运行监控与审计”、正式成绩批次等入口不在当前网站开放。
- 生产启动 worker 与 beat；开发环境可使用 `python manage.py run_judge`。

## 备份与恢复

备份同时包含 MySQL 和 `/srv/coursejudge-storage`。为避免跨文件与数据库状态不一致，在维护窗口暂停 Web 写入和工作进程后备份。

```bash
docker compose stop web worker beat
mkdir -p backups
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u coursejudge --single-transaction --no-tablespaces --set-gtid-purged=OFF coursejudge' > backups/database.sql
tar -czf backups/private-storage.tar.gz -C /srv/coursejudge-storage .
docker compose start web worker beat
```

备份文件保存在仓库以外并加密，复制到独立服务器；保留周期由课程和学校确定。
恢复必须在隔离验收环境执行：先停止写入，将备份导入空数据库，解压存储目录并恢复 UID 10001 的访问权，运行 `manage.py check`，登录核对一份历史提交、正式成绩和隐藏用例，再开放服务。
实际恢复演练、磁盘容量报警和备份调度需要在目标服务器部署时配置，首版代码不会声称已完成这些运维验证。

## 算法端大模型配置

评分标准智能体、训练题智能体与综合能力归因统一使用部署环境里的模型配置。学生端、教师端和管理员端均不提供模型配置入口，用户无需自备 Key：

| 变量 | 说明 |
| --- | --- |
| `LLM_BASE_URL` | OpenAI 兼容端点，如 `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名，如 `deepseek-chat` |
| `LLM_API_KEY` | 服务端 Key，只写现场 `.env`（权限 600），不进仓库、不进数据库、不显示在页面 |
| `LLM_PROVIDER` | 可选，仅用于页面展示来源，默认 `custom` |
| `LLM_ALLOW_USER_OVERRIDE` | 默认 `false`；只影响后端是否采用数据库中已有的历史个人配置，页面已无入口 |

三项（地址、模型、Key）缺一即视为未配置：所有智能体自动走规则兜底，并在结果里标注“规则诊断（未使用大模型）”。修改后重建 `web`、`worker`、`beat` 三个容器生效：

```bash
docker compose up -d --force-recreate web worker beat
```

在容器内核对当前来源（不会打印 Key）：

```bash
docker compose exec -T web python manage.py shell -c "from school.portal import llm_client; print(llm_client.status_text())"
```

历史个人配置（`user_llm_configs` 表）只在 `LLM_ALLOW_USER_OVERRIDE=true` 时参与后端解析；页面不再提供“模型配置”入口，相关写入接口也已移除。切换模型后能力画像签名变化，学生下次打开页面会重新生成。

## 数据库审计与注入巡检

`compose.yaml` 为 MySQL 打开慢查询日志（超过 2 秒写入 `mysql.slow_log`，`general_log` 保持关闭，避免全量语句和个人信息落盘）。应用账号只有业务库权限，读不到 `mysql` 库，日志由维护人员取出后交给巡检命令：

```bash
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B -e "SELECT sql_text FROM mysql.slow_log ORDER BY start_time DESC LIMIT 500"' \
  | docker compose exec -T web python manage.py db_security_check --slow-log - --skip-privileges
```

只检查应用账号权限：

```bash
docker compose exec -T web python manage.py db_security_check
```

两条命令都只读，不会修改数据或权限。加上 `--fail-on-risk` 后，出现全局高危权限（`FILE`、`PROCESS`、`SUPER`、`GRANT OPTION` 等）或日志命中注入特征时返回非 0，可挂到定时任务。输出中的语句已把字符串常量替换为 `?`，不会打印姓名、口令等业务数据。

业务查询本身全部使用 ORM 参数绑定；应用入口另有 GET 参数检测（`school/sql_guard.py`），高风险特征直接返回 400 并写审计，`UNION SELECT` 等低风险关键字只记日志，避免误伤题库检索。`mysql.slow_log` 过大时用 root 执行 `TRUNCATE TABLE mysql.slow_log`。

## 上线前验收

1. 运行业务测试和 Docker 测试，包括正确、错误、语法、超时、输出超限、禁止联网。
2. 使用 MySQL 运行同一测试，并做多进程重复请求、频率、次数和角色撤销竞争测试。
3. 按实际班级人数模拟集中提交，测量排队时间、失败率与资源占用，调整 worker 并发。
4. 用管理员、教师、学生三种角色检查“名单与授权 → 上传作业 → 提交 → 批阅结果 → 导出”，以及归档/恢复、永久删除及文件清理。
5. 演练一次数据库与文件联合恢复。
6. `DEBUG=false python manage.py check --deploy`；确认 HTTPS、域名、凭据与备份。

Docker 限制参数见 `school/judge.py`。容器运行不等于绝对安全；保持 Docker、内核与基础镜像更新，避免让评测机器承载其他敏感业务。
