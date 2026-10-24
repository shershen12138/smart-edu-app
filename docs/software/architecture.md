# 技术方案调研报告 · 课码 Python 作业在线批阅系统

调研日期：2026-10-24 ｜ 代码基线：`smart-edu-app-main/`（协作分支 `codex/simplified-coursework`）

## 1. 文档目的

1. 完整盘点当前系统的分层技术栈，作为新同学入门与对外交接的统一口径。
2. 对**核心技术选型逐项给出论证**（为什么选它、放弃了什么、代价是什么）。
3. 对照 AI Agent 参考技术栈，明确本系统"用 AI，但不做 Agent 平台"的边界。
4. 输出团队未来 1 周的新技术自学计划与可验收 Milestone。

---

## 2. 结论摘要

- 系统是 **Python 3.12 + Django 5.2 单体 Web 应用 + Celery 异步判题 + Docker 沙箱** 的组合，前端为服务端渲染，**不是 SPA，也没有独立 REST API 层**。
- AI 能力目前以**离线 CLI 工具**形态存在（`tools/rubric_agent/`），走 DeepSeek 生成评分标准，**不进入 Web 请求链路**，属于"设计期辅助"而非"运行时智能"。
- 这套选型是**交付约束驱动**的结果：学校目标是 Ubuntu 校园服务器离线部署、前端零 Node 构建、任教教师直接使用。因此"简单、可离线、可排障"优先级高于"技术先进"。
- 主要技术债集中在：明文密码副本、缺失限流与可观测性、`docker.sock` 挂载到 worker。这些是下周自学计划的重点输入。

---

## 3. 分层技术栈现状

| 层级 | 主要职责 | 实际技术 | 关键证据 |
| --- | --- | --- | --- |
| 前端交互层 | 页面渲染、作业提交、结果查看、报表导出 | Django 模板（`templates/` 43 个 HTML）、原生 JS/CSS（`static/app.js`、`static/portal.js`）、whitenoise 静态托管 | `config/settings.py:44-58`、`README.md:33` |
| Web/API 层 | 路由、表单、鉴权、权限、业务服务 | Django MTV 传统视图（`school/portal/`）、自定义 `User` 模型 + Session 认证、CSRF/HSTS 中间件、waitress WSGI | `config/settings.py:72,86-98`、`school/middleware.py`、`school/permissions.py` |
| 异步任务层 | 判题排队、结果回写、定时派发 | Celery 5.6 + Redis Broker，`beat` 每 15s 执行 `dispatch_pending`；`acks_late` + `prefetch=1` 保证不丢任务 | `config/settings.py:111-119`、`school/tasks.py` |
| 判题沙箱层 | 隔离执行不可信学生代码 | 每份提交启动一次性 `python:3.12-slim` 容器，只读挂载、`--network none`、降权 `--user 65534`、多层资源 ulimit | `school/judge.py:59-101` |
| 数据层 | 业务持久化、缓存、私有文件 | MySQL 8.4（PyMySQL，环境未配置时回退 SQLite）、Redis 7（缓存 + Broker）、本地 `PRIVATE_STORAGE` | `config/settings.py:60-71,120-123`、`compose.yaml` |
| AI/模型层 | 按题目材料生成评分标准 | DeepSeek `deepseek-chat`，标准库 `urllib` 手写客户端 + `response_format: json_object` + 指数退避 | `tools/rubric_agent/deepseek.py`、`config.py:19-24` |
| 基础设施层 | 容器化与校园离线部署 | Docker / docker-compose（db/redis/web/worker/beat 五服务）、`deploy/linux/` 更新与备份脚本、ruff + Django 测试 | `compose.yaml`、`deploy/linux/README.md` |

---

## 4. 核心技术选型论证

### 4.1 Python 3.12 + Django 5.2（MTV 单体）

**选择理由**

- 业务主体是**表单驱动的后台管理系统**（账号/班级/作业/评分/报表），Django 的 ORM、Admin、迁移、Session、权限、CSRF 全部内置，等价于把 6 个组件的成本压到 1 个框架。
- 判题适配器需要与同一套模型交互，同进程同语言调用避免了"判题服务 × Web 服务"的跨语言契约维护。
- 仓库已积累 13 个迁移（`school/migrations/`），数据是强关系型的，ORM 收益明显。

**放弃的备选**

| 备选 | 放弃原因 |
| --- | --- |
| FastAPI + React 前后端分离 | 需要独立前端构建、部署产物、跨域与 Token 方案；学校要求是**单机 Docker 一键起服务**，多进程多产物会直接推高运维与排障成本 |
| Django REST Framework | 当前无多端消费者（无 App、无第三方集成），引入 DRF 只是增加序列化层，不产生业务收益 |
| Flask 轻量方案 | 省下的框架约束会以手写权限/迁移/表单的形式还回来 |

**代价**：单体耦合，任何判题逻辑改动都要重启同一镜像；后续若开放多租户，需先把 `school/portal/` 的服务层抽出来。

### 4.2 Django 模板 + 原生 JS（不做 SPA）

**选择理由**

- 页面数量约 43 个、交互以"表单提交 + 分页列表 + 弹窗"为主，无复杂状态共享需求。
- 零 Node 构建链意味着：`docker build` 不需要 `npm install`，校园离线部署包只需 Python 依赖。这是`README.md:33`明确写入的交付约束。
- whitenoise 直接托管静态资源，少一个 Nginx/对象存储组件。

**代价**：交互富度受限（如实时批阅进度目前用轮询/整页刷新思路实现），后续要做"判题实时进度条""在线代码编辑器"时，会到达模板方案的天花板。届时应**按页面局部引入**（如 htmx 或单页挂载 React），而不是整体重写。

### 4.3 Celery + Redis（异步与调度）

**选择理由**

- 判题是**秒级 CPU 密集 + Docker 冷启动**操作，绝不能阻塞 WSGI 请求线程。
- Redis 同时承担 Broker 和 Django 缓存，一套组件解决两个问题，符合"少组件"原则。
- 配置显式打开 `acks_late`、`prefetch_multiplier=1`、`reject_on_worker_lost`（`settings.py:113-116`），针对"判题任务长且不能在 worker 崩溃时丢单"这一具体需求做了强化，说明选型是经过针对性调参而非默认套模板。

**代价与风险**

- 任务**幂等性依赖业务代码保证**：`dispatch_pending` 每 15s 重入，若将来去掉去重/UPSERT 保护，会出现重复判题。
- `beat` 单点；多副本部署会出现重复派发，需要外部锁或改单点。

### 4.4 一次性 Docker 容器作为判题沙箱

**选择理由（这是全系统最关键的安全选型）**

学生代码是不可信输入，直接在宿主机执行等于把服务器交给学生。当前实现在 `school/judge.py` 中叠加了纵深防御：

- 网络：`--network none`
- 文件系统：`--read-only` + 只读 bind mount + `noexec,nosuid,nodev` tmpfs
- 权限：`--cap-drop ALL`、`no-new-privileges`、`--user 65534:65534`
- 资源：`--pids-limit 16`、`--cpus 1`、`--memory/--memory-swap`、`ulimit cpu/nofile/fsize`
- 输出：采集流时按 `output_kb` 截断，防止日志炸弹
- **明确不留宿主机降级路径**（`judge.py:1` 注释即设计声明）：Docker 不可用时判题失败，而不是退回裸执行

**放弃的备选**

| 备选 | 放弃原因 |
| --- | --- |
| `subprocess` + `resource.setrlimit` | 隔离强度不足（共享内核命名空间、文件系统可见），且 Python 层无法防住 fork 炸弹与本地提权 |
| gVisor / Kata / Firecracker | 安全更强，但校园服务器内核与离线镜像受限，运维复杂度过高 |
| 远程 OJ / Judge0 | 引入外部服务依赖，不满足离线部署要求 |

**已知风险**：worker 容器挂载了 `/var/run/docker.sock`（`compose.yaml:50`），等价于给 worker 进程宿主机 root 权限。一旦 Web/Worker 侧出现 RCE 或依赖投毒，沙箱边界会被整体绕过。这是**当前最高优先级的技术债**。

### 4.5 MySQL 8.4 + dj-database-url（SQLite 本地回退）

**选择理由**

- 学校既定基础设施是 MySQL（`REQUIREMENTS.md:37`），生产环境统一。
- `dj_database_url` 解析 `DATABASE_URL`，未设置时自动落到 SQLite（`settings.py:60-64`），使**新同学零外部依赖即可跑起全套功能**，同时在 mysqldump/utf8mb4/严格模式下贴近生产行为，避免"本地能跑线上炸"。
- 生产侧显式设置 `charset=utf8mb4` 与 `STRICT_TRANS_TABLES`（`settings.py:65-69`），把 SQLite 宽松行为在开发期就暴露出来。

**代价**：SQLite 与 MySQL 在并发写、事务隔离上不等价，UAT 必须在 MySQL 上做（这也是 `README.md:122` 要求 MySQL 回归的原因）。

### 4.6 DeepSeek + 手写 HTTP 客户端 + Schema 校验自修复（AI 层）

**选择理由**

- **不用 LangChain / LangGraph / LlamaIndex**：评分标准生成的链路是**固定四步**（加载素材 → 构造提示词 → 调用模型 → 校验落盘，见 `tools/rubric_agent/service.py:1-4`），没有动态路由、没有多轮工具调用、没有检索需求。引入编排框架只会增加抽象层与依赖体积，收益为负。
- **不用 OpenAI SDK**：仅一个 POST 调用，标准库 `urllib` 足够，离线安装更简单；对 API Key 的处理也可以完全自控（只在 `.env`，`describe()` 输出脱敏摘要，见 `tools/rubric_agent/config.py:80-86`）。
- **核心设计是"标签闭环"**：模型只能从 `curriculum.POINT_LABELS` 既有标签中选择，`schema.validate_payload` 对自造标签直接拦截；校验失败时**把错误回喂模型要求重输出**（最多 `max_attempts` 次），耗尽则抛异常退出，**不写半成品、不用占位值伪造评分标准**（`README.md:102`）。这保证了 AI 输出与下游静态分析工具口径一致。
- **隐私边界前置**：默认只上传题目包内容与聚合统计（各题定义/语法错误人数），不上传学生源码全文；提供 `--no-student-stats`、`--dry-run` 开关。

**代价**

- 模型层无抽象接口（写死 DeepSeek），切换供应商需改 `deepseek.py`；后续建议抽一个最小的 `LLMClient` 协议。
- 无 token 预算与成本观测，批量生成长章节时费用不可预估。
- 无评测集，Prompt 改动后缺乏回归依据。

### 4.7 docker-compose + 脚本化交付（不做 K8s）

**选择理由**

- 交付对象是**单台校园 Ubuntu 服务器**，五服务（db/redis/web/worker/beat）编排量远未到达 K8s 的收益阈值。
- 校园场景存在离线/半离线更新，`deploy/linux/` 的备份-迁移-重启脚本比 K8s YAML 更贴近现场运维同学的能力模型。

**代价**：无自动扩缩容。集中提交场景下 worker 数量靠人工调整，需要在上线前做一次压测确定并发worker数。

### 4.8 明确不引入的技术（对照 AI Agent 参考技术栈）

| 参考技术 | 决策 | 论证 |
| --- | --- | --- |
| React / Next.js | 暂不引入 | 零 Node 构建是硬交付约束；当前业务页面无 SPA 强需求 |
| FastAPI / Kong / 独立 API 网关 | 暂不引入 | 无多端消费者；单体内 Session 鉴权足够 |
| LangChain / LangGraph | 暂不引入 | 链路固定、无工具调用与动态编排需求，自研 100 行流水线可维护性与透明度更高 |
| 向量库（pgvector / Milvus / Chroma） | 暂不引入 | 无检索语义需求；评分标准的"知识约束"已由标签白名单 + Schema 校验解决 |
| LiteLLM / one-api 多模型代理 | 暂不引入 | 单一供应商（DeepSeek），代理层属于过早抽象；仅在接第二家模型时再引入 |
| Kubernetes / Prometheus / Vault | 暂不引入 | 单机交付场景下运维成本 > 收益；但**日志/指标缺失已被记为技术债** |

**总原则**：本系统是"Web 系统 + 一个设计期 AI 工具"，不是 Agent 应用。当且仅当出现以下信号时才启动架构演进——多模型/多供应商、实时判题反馈需要长连接、AI 能力进入在线请求链路、worker 需横向扩展。

### 4.9 已识别技术债（作为下一阶段输入）

| 项 | 现状 | 影响 |
| --- | --- | --- |
| `STORE_RECOVERY_PASSWORDS` 明文密码副本 | `settings.py:110`，DEBUG 默认开启 | 违反口令存储基本准则，上线前必须关闭并清理历史副本（`README.md:53` 已标注为临时设计） |
| 无限流 | 仅 `DATA_UPLOAD_MAX_MEMORY_SIZE=3MB` 的体积限制 | 截止前集中提交缺少保护，存在刷接口风险 |
| 无可观测性 | 无 Prometheus/ELK/结构化日志采集，仅容器日志轮转 | 线上判题堆积、任务失败无法主动发现 |
| `docker.sock` 暴露给 worker | `compose.yaml:50` | 沙箱隔离的潜在绕过路径 |
| 无 CI/CD | 无 `.github/` 等流水线 | 回归依赖手工执行，质量防线脆弱 |

---

## 5. 团队 1 周自学计划（2026-10-27 ~ 2026-11-02）

### 5.1 学习主线

对照 AI Agent 架构（用户 → 交互层/API → Agent 编排器 → 大模型、工具调用、RAG、记忆、结果验证），本周按架构图的环节一天一个，从模型层向上走。**不做面面俱到的清单**：每天上午看资料、下午动手，当天只要求产出一个能跑的小 demo 或一页纸文档。

### 5.2 每日安排

| 天 | 主题 | 学习与动手 | 当日产出 |
| --- | --- | --- | --- |
| Day 1 | 模型层 | OpenAI 兼容接口（以 DeepSeek 为例）：结构化 JSON 输出、temperature / max_tokens 的取舍、token 计量与成本估算 | 最小调用 demo + 一页参数实验笔记 |
| Day 2 | Agent 编排器 | 参考 CSAIAgent 的架构设计，理解编排器如何调度模型、工具与记忆；把项目现有的"评分标准生成"流水线映射到这套架构上 | 流程映射图 + 一条改进建议 |
| Day 3 | Prompt 与 Skill | 学习 Agent Skills 的写法（技能 = 说明 + 脚本 + 资源的目录约定），把一条手写 Prompt 改造成结构化 Skill | 一个可运行的 Skill demo |
| Day 4 | 工具调用与 RAG | function calling 协议；跑一个最小 RAG（文档切块 + 向量检索）demo，结合本项目评估"要不要 RAG" | demo + 取舍结论（要/不要、为什么） |
| Day 5 | 结果验证与人工确认 | Schema 校验、"校验失败回喂模型自修复"模式、人工确认环节放在哪里（对应架构图右侧分支） | 校验与兜底方案一页纸 |
| Day 6 | Agent 安全检查 | 参考 Security_check 文档，梳理提示注入、密钥泄露、越权输出、数据外发等检查项，对照本项目打勾 | 本项目的 Agent 安全检查清单 |
| Day 7 | 交互层与监控 + 复盘 | 了解对话/上传/结果展示的常见实现与日志监控最小方案；汇总本周 demo，人人 10 分钟分享 | 复盘文档 + 下周计划 |

### 5.3 参考资料

- 软件架构设计：https://github.com/bettermorn/AIAgent/blob/main/code/CSAIAgent/README.md
- Skill 写法：https://github.com/bettermorn/AIAgent/blob/main/code/AgentSkills
- Agent 安全检查：https://github.com/bettermorn/AIAgent/blob/main/code/MultiAgent/Meeting_Assistant/Security_check.md
- 智能体 demo（均带代码链接）：https://space.bilibili.com/482892362/lists/9169501

### 5.4 验收与边界

- **验收**：每天产物入库，周日复盘会人人讲 10 分钟；demo 能跑起来、文档一页纸即可，不追求完备。
- **边界**：不引入新运行时依赖、不动线上环境、不启动重构；本周只产出认知与小 demo，架构决策留到下周按 demo 结果定。

---

## 6. 附：与其他文档的对应关系

| 内容 | 出处 |
| --- | --- |
| 功能与业务流程 | `docs/REQUIREMENTS.md` |
| 交接说明 | `docs/A_HANDOFF.md` |
| 安装 / 部署 / 更新 | `docs/GETTING_STARTED.md`、`docs/DEPLOYMENT.md`、`deploy/linux/README.md` |
| 验证记录 | `docs/VALIDATION.md` |
| 分层技术栈依据 | `config/settings.py`、`compose.yaml`、`school/judge.py`、`tools/rubric_agent/*` |
