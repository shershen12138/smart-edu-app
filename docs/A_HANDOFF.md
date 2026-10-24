# A 开发交接 · 简化版

2026-10-06 补充：首次协作安装见 [安装指南](GETTING_STARTED.md)，现行规则以 [需求说明](REQUIREMENTS.md) 为准。最新迁移到 `0009`，新增永久删除与文件清理、教学班归档/恢复、名单统计分页、教师期望/实际结果和非机器批阅批量下载。学校已有 Linux 环境使用 [校园更新脚本](../deploy/linux/README.md)，不重新初始化账号。

本次变更基于 codex/a-teaching-workflow，工作分支 codex/simplified-coursework。2026-09-28 需求替代此前助教、题库审核、补交和成绩发布流程。

## 前后端边界

当前业务全部从 config/urls.py 进入 school/portal/views.py。教师创建作业时选择机器批阅或非机器批阅；上传即对学生可见。机器批阅学生提交一个 `.py`，非机器批阅学生提交一个答案 ZIP。

school/course_models.py 新增 DataDictionary、DictionaryItem、EvaluationPackage、Coursework、CourseworkItem、CourseworkSubmission、CourseworkQuestionResult、CourseworkCaseResult。迁移 0003～0006 同时添加软删除、临时密码副本和队列处理标识。User/Classroom/ClassStaff/ClassStudent 继续复用；旧表和旧回归测试保留，不通过当前路由开放。

## B / 批阅对接

1. school/portal/parsers.py 静态解析章节目录和教师上传的 ZIP；`import_course_packages` 仍可批量导入私有配置，网页请求不执行压缩包中的 Python。
2. 第 1～9 章教师上传完整机器批阅 ZIP。工作进程在 Docker 中验证 `gold.py` 并预计算带类型的标准结果；包验证完成前提交状态为 waiting，不给分。
3. `bind_course_package 作业ID 配置代码` 在后台建立题目项，并把 waiting 提交加入队列。已批阅/正在批阅的记录不允许更换规则。
4. 第 10 章人工批阅材料 ZIP 包含一份题目 DOCX 和数据文件。学生答案 ZIP 必须包含同一目录下的 `1001.py`～`1005.py`；教师在提交详情页逐题评分并填写评语。
5. 每次提交把 title、revision、items、reference_path、max_score 快照存入 snapshot。测试输入随用例结果展示；reference_path 和参考答案只供后台，不返回学生页面。
6. `school.portal.grading` 复刻原批卷器的严格类型、`1e-6` 浮点误差及列表/元组递归比较，并按通过用例比例计分。标准答案只在包验证时运行一次；学生容器不含答案。继续保持 Docker 隔离、基础设施异常不记零分、结果原子落库。
7. `evaluate` 使用 worker_token 防止失效进程覆盖新结果。run_judge 用于本地队列；学校 Docker 部署已使用 Celery evaluate_coursework / dispatch_coursework。不存在网页进程直接执行学生文件的路径。
8. 当参考程序异常时整次标为 error，教师可重试；结果完成自动可见，不再要求发布成绩。

## 协作与私有数据

新增代码、模板、迁移、测试提交到 Gitee；.runtime 中数据库、明文密码副本、源码上传、压缩包和测试答案不会上传。另一台开发机须单独取得题目包并执行导入命令。不要把账号重置命令加入日常启动脚本，也不要自动重建协作者数据库。

三个默认账号 admin/teacher/student，初始密码 123456，首次登录必改；用户自己邀请 Gitee 协作者。个人密码仅在本机运行时保存，源码仓库只有明确要求的默认测试密码。

## 当前验收边界

数据库迁移、业务回归和 UI 检查见 VALIDATION.md。第 1～9 章走 Docker 机器批阅，第 10 章走教师人工批阅。Docker Linux 引擎不可用时，机器批阅包验证和学生批阅保持等待或异常状态，不回退到主机执行。
