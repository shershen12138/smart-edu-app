# 学生代码质量评测智能体

面向教学辅助系统的静态评测工具：用 **pylint + AST 知识点检测 + 题库语义规则** 分析学生提交的 `.py`，
按评分量表给每个学生打分，输出 **Markdown 缺陷表** 与 **个人代码完成度雷达图**。

工具独立运行，不依赖 Django，不读写数据库，不改动学生文件。

## 输出什么

- `reports/<课程>/评测报告.md`：每个学生一张表，表头固定四项——作业编号、该题目需要用到的 Python 基础知识点、缺陷及所在代码行、修改建议。
- `reports/<课程>/radar/studentXX.png`：每个学生一张雷达图，维度即评分量表的各项。
- 命令行摘要：量表来源、学生人数、每人总分与等级。

当前已配置题库：`03-列表`（15 道函数题，func301～func315）。

## 目录结构

```text
tools/code_quality_agent/
├── __main__.py          命令行入口
├── config.py            路径与课程配置
├── curriculum.py        题库规格：每题的知识点标签
├── static_analysis.py   函数切块、AST 解析、知识点检测器
├── rules.py             题意规则（越界、返回码、排序键、整除等）
├── lint.py              pylint 适配与中文消息映射
├── rubric.py            量表解析、五维打分、加权总分
├── charts.py            雷达图渲染
├── report.py            Markdown 报告
├── pipeline.py          编排：发现文件 → 分析 → 规则 → 打分
└── models.py            数据契约
```

## 输入数据约定

```text
data/
├── 03-列表/             学生代码，文件名即学生名（学生01.py）
├── 03评分量表.md        评分量表（可为空，见“替换评分量表”）
exercise requirements/
└── 03-列表/
    └── 03-列表/         题库包：func_info_list.txt、*习题说明.docx、gold.py、data/func3xx.txt
```

学生文件名去掉 `.py` 即为报告中的学生名；作业编号沿用题库函数名（`func301` 表示第 3 章第 1 题）。

## 环境准备

需要 Python 3.12 或更高版本，以及两个第三方库：`pylint`（静态检查）与 `matplotlib`（雷达图）。

已按项目约定使用虚拟环境时：

```powershell
# Windows
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
# Ubuntu
.venv/bin/python -m pip install -r requirements-dev.txt
```

没有虚拟环境、只想跑这个工具时：

```powershell
python -m pip install pylint matplotlib
```

验证安装：

```powershell
python -m pylint --version
python -c "import matplotlib; print(matplotlib.__version__)"
```

## 启动

在仓库根目录执行（注意不是工具目录内）：

```powershell
# Windows
.\.venv\Scripts\python.exe -m tools.code_quality_agent --course 03-列表
```

```bash
# Ubuntu
.venv/bin/python -m tools.code_quality_agent --course 03-列表
```

没有虚拟环境时把解释器换成 `python`：

```powershell
python -m tools.code_quality_agent --course 03-列表
```

预期输出：

```text
课程：03-列表
量表：03评分量表.md 为空（0 字节），使用内置默认量表
学生：5 人
  学生01: 57.6 分（E）
  学生02: 79.1 分（C）
  学生03: 87.3 分（B）
  学生04: 72.3 分（C）
  学生05: 52.2 分（E）
报告：D:\...\reports\03-列表\评测报告.md
图表：D:\...\reports\03-列表\radar
```

打开 `reports/03-列表/评测报告.md` 预览即可（VS Code 用 `Ctrl+Shift+V`）。报告里的图片是相对路径，需保持 `radar/` 与报告同目录。

### 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--course` | `03-列表` | 课程目录名，需同时在 `config.COURSES` 与 `curriculum.COURSE_SPECS` 中配置 |
| `--rubric` | `data/<课程>评分量表.md` | 指定另一份量表文件 |
| `--out` | `reports/<课程>` | 报告与图表输出目录 |

示例：

```powershell
python -m tools.code_quality_agent --course 03-列表 --rubric "D:\量表\期中量表.md" --out "D:\评阅结果\第3章"
```

## 评分口径

| 维度 | 默认权重 | 判定方式 |
| --- | --- | --- |
| 知识点覆盖 | 30% | 题目要求的知识点命中率（AST 检测）；文件整体无法解析时按 50% 计 |
| 语法与静态缺陷 | 20% | 每条语法错误或 lint error 扣 40 分 |
| 边界与健壮性 | 15% | 越界、range 上界、整数不可迭代等，每条扣 25 分 |
| 题意一致性 | 25% | 返回码、比较方向、类型过滤、排序键等与题意冲突，每条扣 25 分 |
| 代码规范 | 10% | pylint 规范提示；命名问题按一类计，避免一次扣光 |

总分 = 各维度得分 × 权重之和，等级 A≥90、B≥80、C≥70、D≥60、E<60。

## 替换评分量表

`data/03评分量表.md` 目前是空文件，工具会自动使用上面的内置量表并在报告开头注明。
填入真实量表后重跑即可生效，支持两种写法。

Markdown 表格：

```markdown
| 维度 | 权重 | 说明 |
| --- | --- | --- |
| 知识点掌握 | 40 | 是否用对语法 |
| 语法规范 | 20 | 能否通过编译与 lint |
| 边界健壮 | 20 | 空列表、越界、上界 |
| 逻辑正确 | 15 | 与题意一致 |
| 代码规范 | 5 | 命名与可读性 |
```

列表写法：

```markdown
- 知识点掌握：40%
- 语法规范：20%
- 边界健壮：20%
- 逻辑正确：15%
- 代码规范：5%
```

维度名通过关键词映射到内置五维（知识点、语法、边界、逻辑、规范），权重会自动归一化。
识别不到任何维度时退回内置量表，并在报告里说明原因。

## 扩展新课程（04-分支结构 / 05-循环结构）

1. 在 `curriculum.py` 增加一组 `TaskSpec`，为每题声明 `task_id`、题干摘要与所需知识点标签；新标签需在 `POINT_LABELS` 和 `static_analysis.KNOWLEDGE_DETECTORS` 中同时登记。
2. 在 `rules.py` 为有明确题意陷阱的题注册规则函数（返回 `(行号, 缺陷, 建议, 维度)`），并在 `RULES` 中登记。
3. 在 `config.COURSES` 增加课程与量表文件名。
4. 重新运行命令即可，报告与图表流程不用改。

## 限制与安全边界

- **不执行学生代码**。评测完全静态，缺陷是"静态推断"，报告中使用"疑似/应核对"措辞，不声称运行通过或失败。
- 若后续接入运行期验证，应复用 `school/judge.py` 的受限容器（`--network none`、只读根、降权用户），不要在主机直接 `exec` 学生代码。
- 语法错误的函数不会影响同文件其他函数的分析；但整份文件无法编译时，知识点按 50% 计、规范维度封顶 50 分，并在报告中标注。
- 规则针对题库设计，不能自动发现题意之外的业务逻辑错误；未注册规则的题只做 lint 与知识点检测。

## 常见问题

**提示 `pylint 不可用`**：当前解释器没装 pylint。用同一个解释器安装，或确认命令里的 `python` 是预期的那一个。

**报告里没有 lint 结果**：学生文件整体无法解析时 pylint 会跳过，报告会写明"pylint 已跳过"。

**雷达图中文变方框**：系统缺少中文字体。Windows 装 Microsoft YaHei、Ubuntu 装 `fonts-noto-cjk` 后重跑。

**想只跑某个学生**：把该学生的 `.py` 复制到临时目录，用 `--out` 指定输出，或先移出其他文件再运行。

**输出目录不存在**：工具会自动创建 `reports/<课程>/radar/`。
