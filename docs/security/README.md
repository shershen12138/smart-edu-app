# 三级等保自查与 SQL 注入防护流程

本目录记录本项目围绕**三级等保（8.1.4 安全计算环境）**所做的自查，重点是 SQL 注入的检查结论、防护链路、巡检流程与应急处理。它是**自查材料**，不能替代测评机构的现场测评和渗透测试结论。

适用范围：`config/`、`school/`、`school/portal/`、`templates/`、`static/`、`deploy/linux/`。不包含学校现场的网络、防火墙与动态 IP 脚本。

## 1. 结论速览

| 问题 | 结论 |
| --- | --- |
| 是否存在可利用的 SQL 注入点 | **未发现**。业务查询全部走 Django ORM 参数绑定，全仓库只有 1 处生产原生 SQL，且为常量语句 `SELECT 1`（健康检查） |
| 是否只依赖“代码写对了” | 不是。增加了应用层注入检测、审计留痕、慢查询日志与账号权限巡检，形成检测—留痕—复核闭环 |
| 是否已在学校机器生效 | **未更新学校机器**。代码与测试在本地完成；慢查询日志参数需现场执行 `deploy/linux/update.sh` 重启 db 后才生效 |

## 2. 对应条款与措施

编号沿用项目既有注释习惯（`config/settings.py`、`school/models.py`），仅作自查对照，不作为测评依据。

| 条款 | 要求要点 | 本项目措施 | 证据位置 |
| --- | --- | --- | --- |
| 8.1.4.2 访问控制 | 按最小权限授权 | 数据库使用专用 `coursejudge` 账号，MySQL/Redis 不对公网暴露；巡检发现全局高危权限 | `compose.yaml`、`deploy/linux/compose.yaml`、`school/db_security.py` |
| 8.1.4.3 安全审计 | 审计不可删除、可追溯 | `AuditLog` 逐条哈希串联；注入拦截写 `security.sql_injection_blocked`；MySQL 慢查询写入 `mysql.slow_log` | `school/services.py`、`school/sql_guard.py`、`school/management/commands/db_security_check.py` |
| 8.1.4.4 入侵防范 | 发现并阻断已知攻击手法 | ORM 参数化 + GET 参数注入特征检测（高/低风险分级）+ 回归测试 | `school/sql_guard.py`、`school/tests/test_sql_injection.py` |
| 8.1.4.7 数据完整性 | 数据不被非授权篡改 | 参数化避免查询语义被改写；`STRICT_TRANS_TABLES` + `utf8mb4` | `config/settings.py` |
| 8.1.4.8 数据保密性 | 敏感信息不泄露 | 审计只记参数名与规则名，不落原始输入；巡检输出把字符串常量替换为 `?` | `school/sql_guard.py`、`school/db_security.py` |

## 3. SQL 注入检查方法与证据

### 3.1 检索面

按以下写法全仓库检索（`*.py`、`*.sh`、`*.yaml`、`*.md`）：

`cursor.execute`、`connection.cursor`、`.raw()`、`.extra()`、`RawSQL`、`as_sql`、`executescript`、`sqlite3`/`pymysql` 直连、f-string / `%` / `format` 拼 SQL、`filter(**{...})`、`Q(**{...})`、`order_by(变量)`、`values(变量)`。

### 3.2 关键结论

| 检查点 | 结论 |
| --- | --- |
| 原生 SQL | 仅 2 处：`school/views.py` 的健康检查 `SELECT 1`（常量）；`school/tests/test_data_protection.py` 的测试辅助函数（表名/列名已加白名单，值仍用 `%s`） |
| 业务查询 | 全部 ORM，搜索类输入走 `icontains` 参数绑定；`q=%` 会被转义，不会退化为匹配全部记录 |
| 动态关键字参数 | `access.py` 的 `staff__can_<action>`、`cleanup.py` 的 `FILE_FIELDS`、`administration_views.py` 的字典字段映射，来源均为代码内常量，不接受请求参数 |
| 排序与字段名 | 所有 `order_by`/`values` 使用字面量，不存在把用户输入当字段名的写法 |
| SQL 字符串拼接 | 无 `.raw()` / `.extra()` / `RawSQL`，无拼接语句 |

## 4. 防护链路（请求到数据库）

```text
浏览器 / 客户端
  │  GET 带参数
  ▼
SqlInjectionGuardMiddleware（school/sql_guard.py）
  ├─ 高风险特征 → 400 + 审计 security.sql_injection_blocked（仅登录用户）
  ├─ 低风险特征 → 放行，logger.warning 记录路径/参数名/规则名
  └─ 无特征 → 放行
  ▼
视图 / 表单校验（权限、CSRF、字段白名单）
  ▼
Django ORM（占位符绑定，驱动转义）
  ▼
MySQL（STRICT_TRANS_TABLES + utf8mb4，慢查询 ≥2s 写入 mysql.slow_log）
```

设计取舍：

- **只检查 GET**。表单、JSON、文件上传不参与判断——本项目含 Python 与 SQL 教学章节，学生代码和题面里出现 SQL 关键字是正常内容，按内容拦截会误伤业务。
- **风险分级**。引号恒真条件、`--`/`#` 注释终结、堆叠语句、`SLEEP(`/`BENCHMARK(` 判为高风险；`UNION SELECT`、`information_schema`、`INTO OUTFILE` 判为低风险只记日志，避免教师检索 SQL 关键字被拦。
- **不落原始输入**。审计与日志只写参数名、规则名、路径、IP，防止口令与个人信息进入审计表。
- **可关闭**。`SQL_GUARD_ENABLED=false` 可临时关闭，用于排障；关闭不影响 ORM 参数化这层根本防护。

### 4.1 风险规则

| 规则名 | 置信度 | 说明 |
| --- | --- | --- |
| `quote_tautology` | 高 | `' OR 1=1` 一类引号配平的恒真条件 |
| `quote_comment` | 高 | 引号后紧跟 `--`、`#`、`/*` 截断语句 |
| `stacked_statement` | 高 | `; DROP/UPDATE/DELETE/...` 堆叠语句 |
| `time_delay` | 高 | `SLEEP(`、`BENCHMARK(`、`pg_sleep(`、`WAITFOR DELAY` |
| `union_select` | 低 | `UNION [ALL] SELECT` |
| `metadata_probe` | 低 | `information_schema`、`sysobjects`、`pg_catalog` |
| `file_access` | 低 | `INTO OUTFILE`、`LOAD_FILE(` |

## 5. 数据库巡检流程（SOP）

### 5.1 检查应用账号权限

账号只应持有业务库的增删改查权限。发现 `FILE`、`PROCESS`、`SUPER`、`SHUTDOWN`、`CREATE USER`、`RELOAD`、`REPLICATION *`、`ALL PRIVILEGES ON *.*`、`WITH GRANT OPTION` 会判为风险。

```bash
# 校园 Ubuntu（/opt/coursejudge）
cd /opt/coursejudge
sudo docker compose --env-file .env -f compose.yaml exec -T web \
  python manage.py db_security_check --fail-on-risk
```

```powershell
# 本地 Windows（SQLite 会自动跳过权限检查）
.\.venv\Scripts\python.exe manage.py db_security_check
```

### 5.2 扫描慢查询日志中的注入特征

应用账号无权读取 `mysql` 库，日志由维护人员用 root 取出后交给巡检命令扫描（`--slow-log -` 表示读标准输入）：

```bash
cd /opt/coursejudge
sudo docker compose --env-file .env -f compose.yaml exec -T db \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B -e "SELECT sql_text FROM mysql.slow_log ORDER BY start_time DESC LIMIT 500"' \
  | sudo docker compose --env-file .env -f compose.yaml exec -T web \
      python manage.py db_security_check --slow-log - --skip-privileges --fail-on-risk
```

### 5.3 结果判读

| 输出 | 含义 | 处置 |
| --- | --- | --- |
| `[通过] 未发现全局高危权限` | 账号权限收敛 | 无需操作 |
| `[风险] FILE on *.*` 等 | 应用账号越权 | 用 root 执行 `REVOKE` 回收，只保留业务库权限 |
| `[风险] quote_tautology（high）：...` | 日志里出现注入特征 | 按第 6 节应急流程处理 |
| `[跳过] 当前数据库为 sqlite` | 本地开发库 | 正常，权限检查只在 MySQL 生效 |
| 退出码非 0（`--fail-on-risk`） | 存在风险 | 接入定时巡检时作为告警信号 |

建议频率：**每周一次**常规巡检，**每次发布后**加做一次，**发现异常时**立即执行。

### 5.4 日志容量

`mysql.slow_log` 只记录执行超过 2 秒的语句。过大时用 root 清空，不要删除 `mysql_data` 卷：

```bash
sudo docker compose --env-file .env -f compose.yaml exec -T db \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "TRUNCATE TABLE mysql.slow_log"'
```

## 6. 发现可疑注入时的应急流程

1. **确认是否被拦**：高风险特征应返回 HTTP 400，并留下 `security.sql_injection_blocked` 审计记录（`detail.params` 为参数名，`detail.rules` 为规则名，`ip` 为来源地址）。
2. **定位来源**：管理员进入“审计日志”按动作筛选，或用 `--slow-log` 巡检确认语句是否真正到达数据库。
3. **判断影响**：若慢日志中无对应语句，说明被中间件拦住、未执行；若有，立即按数据泄露/篡改预案处理并保留证据。
4. **止损**：校园网防火墙封禁来源 IP（现场网络由管理员操作）、停用涉事账号、必要时改密。
5. **复核**：运行 `manage.py test school.tests.test_sql_injection`，把本次载荷补进 `PAYLOADS` 回归；更新 `docs/VALIDATION.md` 记录时间、载荷与结论。

## 7. 自查命令与当前结果

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test school.tests.test_sql_injection
.\.venv\Scripts\python.exe manage.py test school.tests
```

2026-11-21 本地（SQLite）执行结果：

| 检查 | 结果 |
| --- | --- |
| `manage.py check` | 0 issues |
| `makemigrations --check --dry-run` | No changes detected |
| `test_sql_injection` | 17 项通过 |
| `test school.tests` | 788 项通过，13 项 Docker 测试按开关跳过 |
| Ruff（新增文件与生产代码） | 通过；`test_data_protection.py` 保留原有的 `dict()` 写法，属存量告警 |

手工验证拦截（需登录后带 Cookie；未登录时同样返回 400）：

```bash
curl -i "http://127.0.0.1:8000/students/?q=%27%20OR%201%3D1%20--"
# 期望：HTTP 400，页面提示“请求参数包含疑似 SQL 注入内容，已被安全策略拦截。”
curl -i "http://127.0.0.1:8000/students/?q=UNION%20SELECT%20%E7%9A%84%E7%94%A8%E6%B3%95"
# 期望：HTTP 200 或 302（低风险关键字只记日志，不拦截）
```

## 8. 配置项

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `SQL_GUARD_ENABLED` | `true` | 关闭后不再检测 GET 参数，ORM 参数化仍然生效 |
| MySQL `--slow-query-log` | 开启 | 执行超过 `--long-query-time=2` 秒的语句写入 `mysql.slow_log` |
| MySQL `--log-output=TABLE` | TABLE | 日志落表，便于 root 用 SQL 取用与清空 |
| MySQL `--general-log` | `0` | 不记录全量语句，避免个人信息落盘 |

## 9. 边界与未完成项

- 本次为**代码审查 + 回归测试**，未做第三方渗透测试，也未对运行中实例做扫描；测评结论以测评机构报告为准。
- **未更新学校机器**，慢查询日志参数要等现场更新脚本重启 db 后才生效；首次巡检前确认 `mysql.slow_log` 表已存在。
- Nginx / 防火墙层面的注入规则属于现场网络，未写入仓库；仓库内只提供应用层检测。
- MySQL 企业版 `audit_log` 插件未使用（社区版镜像不含），审计依赖应用层 `AuditLog` 与慢查询日志。
- 只有执行超过 2 秒的语句会进慢查询日志，快速注入语句不会留下痕迹；这类请求依靠应用层审计与 Web 访问日志交叉确认。
- 依赖 CVE 扫描（`PyMySQL` 等）尚未接入镜像构建流程。

## 10. 相关文档

- [部署与运行](../DEPLOYMENT.md)：“数据库审计与注入巡检”“上线前验收”
- [校园更新说明](../../deploy/linux/README.md)：现场巡检命令与回滚边界
- [验证记录](../VALIDATION.md)：每轮测试项数、真实 Docker 与学校机器是否更新
- [代码地图](../../README.md)：模块职责与命令行一览
