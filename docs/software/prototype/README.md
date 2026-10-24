# 交互式原型（docs/software/prototype）

由 AI 生成的**交互式界面原型**，用于需求确认、界面评审与演示。原型是静态页面，不连接数据库、不调用后端、不执行任何学生代码，页面中的账号、班级、作业与成绩均为虚构示例数据。

## 打开方式

直接双击 `index.html`，或用浏览器打开以下地址之一：

- 原型首页：`docs/software/prototype/index.html`
- 登录页：`login.html`
- 管理员端：`admin.html`
- 教师端：`teacher.html`
- 学生端：`student.html`

无需安装 Python、Node 或任何依赖；页面只用到原生 HTML / CSS / JavaScript，可离线打开。

## 文件结构

| 文件 | 说明 |
| --- | --- |
| `index.html` | 原型首页：角色入口、可交互点清单、与真实实现的对应关系 |
| `login.html` | 登录与首次登录强制改密流程 |
| `admin.html` | 管理员端：账号、教学班、名单导入、数据字典、归档 |
| `teacher.html` | 教师端：作业列表与创建、提交记录与逐题评分、评分量规与质量报告 |
| `student.html` | 学生端：作业列表、提交、结果、我的质量报告 |
| `assets/prototype.css` | 原型样式，沿用站点 `static/app.css` 的设计令牌（墨绿主色、同色系灰阶） |
| `assets/prototype.js` | 示例数据与交互逻辑：分页、弹窗、Tab、Toast、雷达图、评分计算 |

## 可交互点清单

**登录页**

- 账号或密码为空时拦截并提示；
- 勾选「首次登录」后进入强制改密视图，校验新密码长度（≥10 位）与两次输入一致性，改密完成后回到登录。

**管理员端**

- 名单分页（每页 5 条）、启用 / 停用切换、删除二次确认弹窗；
- 新建学生账号弹窗：姓名与学号必填、学号重复校验，成功后追加到名单并跳到最后一页；
- 名单导入：模拟解析后给出成功 / 失败行预览（学号重复、学号为空），确认导入只写入成功行；
- 数据字典：字典项新增与删除；
- 班级归档：勾选后提示「日常页面与旧链接不再显示」，取消勾选即恢复。

**教师端**

- 批阅方式切换：机器批阅 / 非机器批阅联动上传说明与提示文案；
- 创建作业：填写名称后加入作业列表，列表与统计卡片同步刷新；
- 提交记录：点击学生查看明细（提交次数、通过用例、机器得分）；
- 逐题人工评分：滑块实时计算合计分，支持评语填写与保存；
- 评分量规：六个维度 5 分制滑块，实时计算综合分（5 分制）、百分制与等级，并驱动 canvas 雷达图重绘。

**学生端**

- 机器批阅：仅接受 `.py`，选错类型给出提示并禁用提交按钮；
- 非机器批阅：提示 ZIP 内需包含 `1001.py`～`1005.py`；
- 提交进度条：**原型模拟动画**，页面明确标注不代表真实批阅；
- 结果页只展示得分与评语，不显示期望结果与参考答案（与真实实现一致）。

## 与真实实现的关系

| 原型页面 | 真实实现位置 |
| --- | --- |
| `login.html` | `templates/school/login.html`、`school/views.py` |
| `admin.html` | `school/portal/administration_views.py`、`templates/portal/` |
| `teacher.html` | `school/portal/learning_views.py`、`rubric_views.py`、`quality_views.py` |
| `student.html` | `school/portal/learning_views.py`、`templates/portal/work.html` |
| 六维量规与雷达图 | `school/portal/rubric_agent.py`、`tools/code_quality_agent/` |

真实系统的机器批阅依赖 Docker Linux 引擎与题目包，由 `manage.py run_judge` 工作进程完成；原型只演示界面与交互流程，任何成绩与进度都不具备真实含义。

## 维护约定

- 页面使用示例数据，修改交互逻辑时只改 `assets/prototype.js` 中的 `DATA` 与对应 `init*` 函数；
- 样式统一写在 `assets/prototype.css`，颜色沿用站点设计令牌，避免引入外部 CDN 与字体；
- 新增页面时，在 `index.html` 的角色卡片与「与真实实现的对应关系」表格中同步登记。
