# docs/ 文档索引

这里放安装、部署、需求、验证与课程作业用文档。**代码本身不在这里**，模块功能与实现见根目录 [README.md](../README.md) 的“代码地图”。

## 按用途找文档

| 你要做的事 | 看哪份 | 内容与写法 |
| --- | --- | --- |
| 在自己的 Windows / Ubuntu 电脑装起来 | [GETTING_STARTED.md](GETTING_STARTED.md) | 逐步命令：虚拟环境、依赖、`.env`、`migrate`、`runserver`、`run_judge`、测试账号、故障排查；含可直接复制给 AI 的安装请求 |
| 更新已经部署好的实验室 Ubuntu 电脑 | [../deploy/linux/README.md](../deploy/linux/README.md) | **已有环境的更新器**，不是安装器；现场根目录 `/opt/coursejudge`，说明脚本行为、备份位置与更新后逐项检查 |
| 一台全新正式服务器部署 | [DEPLOYMENT.md](DEPLOYMENT.md) | 场景先行的正式部署说明；不能拿校园更新脚本当首次安装 |
| 查当前要做什么功能 | [REQUIREMENTS.md](REQUIREMENTS.md) | 以聊天澄清为准的现行需求表：管理员/教师/学生三端功能、计分与删除归档规则；旧助教、审批、成绩发布批次已作废 |
| 了解上一轮改了什么、怎么对接 | [A_HANDOFF.md](A_HANDOFF.md) | 开发交接：前后端边界、批阅对接 6 个环节（解析 → 验证 → 绑定 → 提交 → 快照 → 计分）、私有数据约定 |
| 看做到哪一步、验证了什么 | [VALIDATION.md](VALIDATION.md) | 按日期倒序的验证记录：测试项数、真实 Docker 结果、迁移演练、浏览器实测，以及**未验证的边界**（学校现场、跨网段、并发压测） |
| 了解系统设计与取舍 | [software/architecture.md](software/architecture.md) | 技术方案调研：架构分层、Docker 沙箱、数据模型与替代方案对比 |
| 看一次第三方代码评审记录 | [software/CodeReview.md](software/CodeReview.md) | 历史评审报告；其中个别结论已被后续提交修复，只作过程记录 |
| 看需求/软件工程作业材料 | [requirements/](requirements/) | 问题定义、功能规格、非功能规格、管理员与教师用户故事 |
| 看项目管理材料 | [mgmt/](mgmt/) | 沟通管理计划、风险登记册 |
| 只看界面长什么样、不启动服务 | [software/prototype/README.md](software/prototype/README.md) | AI 生成的交互式原型：直接双击 HTML，示例数据、不连后端、不跑学生代码 |

## 阅读顺序建议

1. 新人：`GETTING_STARTED.md` → 根 `README.md` 的“代码地图” → `REQUIREMENTS.md`
2. 接手开发：`A_HANDOFF.md` → `VALIDATION.md` 最近一条 → `software/architecture.md`
3. 现场运维：`../deploy/linux/README.md` → `DEPLOYMENT.md`

## 维护约定

- 代码改动涉及行为时，同步更新 `REQUIREMENTS.md`；跑过验证后追加 `VALIDATION.md`，写清**测试项数、是否用了真实 Docker、有没有更新学校机器**，三者不能混为一谈。
- 迁移编号以 `school/migrations/` 实际文件为准（当前到 `0018_userllmconfig`）。`A_HANDOFF.md`、`REQUIREMENTS.md` 正文里的 `0009` 是当时的编号，属历史记录，不再据此判断现状。
- 文档里的命令要与 `manage.py` 实际子命令一致；新增管理命令时同步根 `README.md` 的“命令行”表。
- 不要把真实题目包、学生数据、`.env`、密钥或数据库备份放进 `docs/`。
