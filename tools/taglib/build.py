# -*- coding: utf-8 -*-
"""生成《Python 考点 Tag 库》Markdown 与机器可读 tags.json。

数据源：spec_a.py / spec_b.py / spec_c.py
产物：
    <项目根>/Python考点Tag库.md
    <项目根>/tags/tags.json

自检（任一失败即中止）：
    1) tag ID / 中文名 / 英文键 / 旧标签 全局唯一；
    2) Python题库.md 中出现的每一个旧标签都能归一到一个叶子 tag；
    3) 每道题至少命中 1 个 tag，每个单元至少 1 个模块。
"""

import json
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from spec_a import UNITS_A
from spec_b import UNITS_B
from spec_c import UNITS_C

ROOT = Path(__file__).resolve().parents[2]
QBANK = ROOT / "data" / "Python题库.md"
OUT_MD = ROOT / "Python考点Tag库.md"
OUT_JSON = ROOT / "tags" / "tags.json"

UNITS_RAW = UNITS_A + UNITS_B + UNITS_C

LEVELS = ("基础", "进阶", "易错")

# 雷达图六轴（与 school/portal/rubric_agent.py 的 ABILITY_RULES 保持一致）
ABILITY_RULES = (
    ("数据组织与容器操作", "knowledge", "列表、字典、集合、元组、切片、排序与去重等数据结构操作",
     "列表 字典 集合 元组 切片 索引 排序 去重 保序 二维 键值 插入 合并 反转 队列 栈"),
    ("流程控制与分支循环", "logic", "条件分支、循环遍历、累加计数与多分支返回",
     "循环 for while 分支 条件 判断 遍历 计数 累加 嵌套 枚举 阶梯 统计 分类 范围"),
    ("字符串与内置方法", "syntax", "字符串处理、类型与进制转换、常用内置函数",
     "字符串 字符 ASCII 编码 进制 转换 内置 格式化 拼接 split join len max min"),
    ("函数设计与结构", "structure", "函数定义、参数与返回值、职责拆分与结构组织",
     "函数 封装 返回值 参数 结构 模块 调用 定义"),
    ("边界与异常处理", "boundary", "空列表、越界、非法输入与特殊值等边界情况",
     "边界 健壮 鲁棒 异常 空列表 越界 特殊值 非法 合法性"),
    ("规范与可读性", "readability", "命名、注释、缩进与代码风格",
     "命名 注释 缩进 规范 可读 风格 格式"),
)

# 易混 tag 对照（人工维护，帮助归一时不串味）
CONFUSABLE = (
    ("列表去重 vs 集合去重", "U04.M04.T01 / U05.M02.T01",
     "要求保序用列表去重（dict.fromkeys）；只要唯一性可用 set"),
    ("浅拷贝 vs 深拷贝", "U04.M03.T04", "嵌套结构改内层会同时影响副本，需 copy.deepcopy"),
    ("可变默认参数 vs 默认参数", "U06.M02.T01 / U06.M02.T06", "列表/字典作默认值必须用 None 哨兵"),
    ("方法重写 vs 运算符重载", "U08.M04.T01 / U08.M03.T02", "重写覆盖父类同名方法；重载实现 dunder 让内置语法生效"),
    ("属性 vs 类属性", "U08.M01.T03 / U08.M01.T04", "可变类属性被所有实例共享，是常见脏状态来源"),
    ("try else vs finally", "U09.M01.T04", "else 只在无异常时执行；finally 无论如何都执行"),
    ("列表推导式 vs 生成器表达式", "U07.M03.T01 / U07.M02.T02", "前者立即求值占内存；后者惰性、只能遍历一次"),
    ("sort vs sorted", "U04.M05.T01 / U04.M05.T02", "sort 原地修改返回 None；sorted 返回新列表"),
    ("break vs continue", "U02.M04.T01 / U02.M04.T02", "break 结束整层循环；continue 只跳过本轮"),
    ("切片 vs 索引", "U04.M02.T01 / U04.M01.T02", "切片越界不报错（返回空），索引越界抛 IndexError"),
    ("is vs ==", "U01.M05.T04", "is 比较身份（None 用它）；== 比较值"),
    ("递归 vs 递推", "U06.M04.T01 / U12.M01.T03", "递归自调用；递推用前一项算后一项，通常改写成循环"),
    ("断言 vs 异常", "U09.M04.T03 / U09.M03.T01", "assert 用于内部不变量，用户输入校验要用 raise"),
    ("浅层遍历 vs 索引遍历", "U04.M01.T03", "需要下标用 enumerate，不要 range(len(lst))"),
)


# ---------------------------------------------------------------- 构建索引
def build_index():
    units = []
    ids = {}
    names = {}
    ens = {}
    legacy_map = {}
    problems = []

    for u_code, u_name, u_stage, u_goal, u_abilities, modules in UNITS_RAW:
        if not u_code.startswith("U"):
            problems.append("单元编号不合规: {}".format(u_code))
        unit = {
            "id": u_code,
            "name": u_name,
            "stage": u_stage,
            "goal": u_goal,
            "abilities": list(u_abilities),
            "modules": [],
        }
        for m_idx, (m_code, m_name, m_goal, m_prereq, tags) in enumerate(modules, 1):
            module_id = "{}.{}".format(u_code, m_code)
            module = {
                "id": module_id,
                "name": m_name,
                "goal": m_goal,
                "prereq": list(m_prereq),
                "tags": [],
            }
            for t_idx, tag in enumerate(tags, 1):
                name, en, level, desc, legacy, syn = tag
                tag_id = "{}.T{:02d}".format(module_id, t_idx)
                if tag_id in ids:
                    problems.append("重复 tag ID: {}".format(tag_id))
                if name in names:
                    problems.append("重复 tag 名: {} ({})".format(name, tag_id))
                if en in ens:
                    problems.append("重复英文键: {} ({})".format(en, tag_id))
                if level not in LEVELS:
                    problems.append("非法难度: {} ({})".format(level, tag_id))
                ids[tag_id] = True
                names[name] = tag_id
                ens[en] = tag_id
                for old in legacy:
                    if old in legacy_map:
                        problems.append("旧标签被映射两次: {} -> {} / {}".format(
                            old, legacy_map[old], tag_id))
                    legacy_map[old] = tag_id
                module["tags"].append({
                    "id": tag_id,
                    "name": name,
                    "en": en,
                    "level": level,
                    "desc": desc,
                    "aliases": sorted({x for x in syn if x != name}),
                    "legacy": list(legacy),
                })
            if not module["tags"]:
                problems.append("模块无 tag: {}".format(module_id))
            unit["modules"].append(module)
        units.append(unit)

    # 模块前置引用必须存在
    module_ids = {m["id"] for u in units for m in u["modules"]}
    for u in units:
        for m in u["modules"]:
            for pre in m["prereq"]:
                if pre not in module_ids:
                    problems.append("前置模块不存在: {} -> {}".format(m["id"], pre))

    return units, ids, names, ens, legacy_map, problems


def parse_qbank():
    """返回 [(题号, 标题, [旧标签...]), ...]"""
    if not QBANK.exists():
        return []
    text = QBANK.read_text(encoding="utf-8")
    rows = []
    for block in text.split("### 1、题目标题：")[1:]:
        head = block.split("\n", 1)[0].strip()
        m = re.search(r"Q\d+-\d+", head)
        qid = m.group(0) if m else head[:12]
        t = re.search(r"\*\*3、题目考察的知识点标签\*\*\s*\n+([^\n]+)", block)
        tags = re.findall(r"`([^`]+)`", t.group(1)) if t else []
        rows.append((qid, head, tags))
    return rows


def md_cell(text):
    return str(text).replace("|", "\\|")


def main():
    units, ids, names, ens, legacy_map, problems = build_index()
    questions = parse_qbank()

    # ---- 校验：题库旧标签全覆盖 ----
    used_legacy = Counter(t for _, _, tags in questions for t in tags)
    unmapped = sorted(t for t in used_legacy if t not in legacy_map)
    if unmapped:
        problems.append("以下旧标签未归一（{} 个）：\n    ".format(len(unmapped)) + "\n    ".join(unmapped))

    # ---- tag -> 题目 / 题目 -> tag ----
    tag_questions = OrderedDict((tid, []) for tid in ids)
    q_tags = OrderedDict()
    for qid, _, tags in questions:
        mapped = []
        for old in tags:
            tid = legacy_map.get(old)
            if tid and qid not in tag_questions[tid]:
                tag_questions[tid].append(qid)
            if tid and tid not in mapped:
                mapped.append(tid)
        q_tags[qid] = mapped
        if not mapped:
            problems.append("题目未映射到任何 tag: {}".format(qid))

    if problems:
        print("自检失败：")
        for p in problems:
            print("  -", p)
        return 1

    # ---- 统计 ----
    flat = [t for u in units for m in u["modules"] for t in m["tags"]]
    level_stat = Counter(t["level"] for t in flat)
    module_count = sum(len(u["modules"]) for u in units)
    covered = sum(1 for t in flat if tag_questions[t["id"]])

    # 单元 -> 覆盖题数
    unit_questions = {}
    for u in units:
        qs = set()
        for m in u["modules"]:
            for t in m["tags"]:
                qs.update(tag_questions[t["id"]])
        unit_questions[u["id"]] = sorted(qs, key=lambda q: (int(q.split("-")[0][1:]), q))

    # ---- 知识域（题库章节）----
    domains = []
    if QBANK.exists():
        for line in QBANK.read_text(encoding="utf-8").splitlines():
            if line.startswith("## 知识域 "):
                domains.append(line[3:].strip())

    md = []
    add = md.append

    add("# Python 考点 Tag 库（单元 / 模块 / tag 三级）")
    add("")
    add("> **定位**：本系统的唯一考点词表。题目打标、考点分析、薄弱项组题、雷达图归因全部引用这里的 `tag_id`，不再各自造词。")
    add("> **规模**：{} 个单元 · {} 个模块 · **{} 个 tag**；已对齐题库 {} 道题 / {} 个旧标签。".format(
        len(units), module_count, len(flat), len(questions), len(used_legacy)))
    add("> **机器可读**：`tags/tags.json`（同源生成）；生成器 `tools/taglib/`，改规格后 `python tools/taglib/build.py` 可重生。")
    add("")
    add("---")
    add("")

    # ---------------- 〇
    add("## 〇、它要解决的三处接缝")
    add("")
    add("改造前，系统里同时存在三套互不相通的词表：")
    add("")
    add("| 环节 | 改造前的形态 | 问题 |")
    add("|:--|:--|:--|")
    add("| 题库打标 | 每题 2~4 个两级标签，如 `基础语法/整除与取余`（{} 个不同写法） | 前缀随手写：`基础语法`/`内置函数`/`算法`/`数据结构` 混在同一层 |".format(len(used_legacy)))
    add("| 考点分析 agent | 输出自由文本 `knowledge_points[].name`，如“列表切片” | 同一考点换个人就换说法，无法与题库对齐、无法聚合 |")
    add("| 雷达图 | 6 个主能力轴（`ABILITY_RULES` 关键词硬匹配） | 知识点与能力轴之间没有显式映射，只能靠关键词碰运气 |")
    add("")
    add("Tag 库把三者收拢成一条链路：**题目 → tag_id → 模块 → 单元 →（可选）主能力轴**，每一步都有确定映射，且缺少映射会在生成时直接报错。")
    add("")

    # ---------------- 一
    add("## 一、三层结构与命名规则")
    add("")
    add("| 层级 | 编号形式 | 示例 | 职责 | 数量 |")
    add("|:--|:--|:--|:--|:--:|")
    add("| 一级：单元 | `U01` | `U04 列表与序列操作` | 教学板块，对应 1~3 周的学习阶段 | {} |".format(len(units)))
    add("| 二级：模块 | `U04.M02` | `M02 切片` | 一组同源技能，题目/课程的最小组织单位 | {} |".format(module_count))
    add("| 三级：tag | `U04.M02.T02` | `列表步长切片与反转` | 可打标、可组题、可计掌握度的原子考点 | **{}** |".format(len(flat)))
    add("")
    add("命名规则（生成时强制校验）：")
    add("")
    add("1. **中文名是唯一显示名**，不带标点、不带括号解释；同义说法只进 `aliases`，不进名字。")
    add("2. **英文键 `snake_case` 全局唯一**，用于代码常量、数据库字段与前端埋点。")
    add("3. **`tag_id` 永不复用**：废弃时保留编号并标 `deprecated`，不重新分配给新考点（避免历史成绩错位）。")
    add("4. **一个 tag 只描述一件事**：`切片`与`步长切片`分开，因为学生常犯的是后者的错。")
    add("5. **单元按知识板块切，不按难度切**；难度是 tag 的属性（基础 / 进阶 / 易错），不是层级。")
    add("")
    add("难度口径：")
    add("")
    add("| 难度 | 含义 | 典型用途 |")
    add("|:--|:--|:--|")
    add("| 基础 | 首次学习即应掌握，错了说明该模块没学会 | 薄弱项组题的必练项 |")
    add("| 进阶 | 需要组合或理解原理，允许一次试错 | 巩固提升 |")
    add("| 易错 | 普遍踩坑点（负数整除、可变默认参数、深浅拷贝…） | 诊断题与错因归因 |")
    add("")

    # ---------------- 二
    add("## 二、总览")
    add("")
    add("| 单元 | 名称 | 阶段 | 模块数 | tag 数 | 覆盖题目 | 主能力轴 |")
    add("|:--|:--|:--|:--:|:--:|:--:|:--|")
    for u in units:
        add("| {} | {} | {} | {} | {} | {} 题 | {} |".format(
            u["id"], md_cell(u["name"]), md_cell(u["stage"]), len(u["modules"]),
            sum(len(m["tags"]) for m in u["modules"]),
            len(unit_questions[u["id"]]), "、".join(u["abilities"])))
    add("| **合计** | — | — | **{}** | **{}** | **{} 题** | 6 轴 |".format(
        module_count, len(flat), len(questions)))
    add("")
    add("难度分布：基础 {} 个（{:.0%}）· 进阶 {} 个（{:.0%}）· 易错 {} 个（{:.0%}）；题库已命中的 tag {} 个（{:.0%}），其余为课程预留。".format(
        level_stat["基础"], level_stat["基础"] / len(flat),
        level_stat["进阶"], level_stat["进阶"] / len(flat),
        level_stat["易错"], level_stat["易错"] / len(flat),
        covered, covered / len(flat)))
    add("")

    # ---------------- 三
    add("## 三、三级标签树")
    add("")
    add("> 读法：每行一个叶子 tag；模块名在组内首行标出，后续行留空。最后一列给出旧二级标签与常见同义说法，供归一时匹配。")
    add("")
    for u in units:
        add("### {}　{}".format(u["id"], u["name"]))
        add("")
        add("> **阶段**：{}　**目标**：{}　**主能力轴**：{}".format(u["stage"], u["goal"], "、".join(u["abilities"])))
        add("")
        add("| 模块 | tag ID | 三级 tag | 英文键 | 难度 | 说明 | 旧标签 / 同义词 |")
        add("|:--|:--|:--|:--|:--:|:--|:--|")
        for m in u["modules"]:
            for i, t in enumerate(m["tags"]):
                alias = list(t["legacy"]) + t["aliases"]
                add("| {} | `{}` | **{}** | `{}` | {} | {} | {} |".format(
                    "M{} {}".format(m["id"].split(".")[1][1:], md_cell(m["name"])) if i == 0 else "",
                    t["id"], md_cell(t["name"]), t["en"], t["level"], md_cell(t["desc"]),
                    md_cell("、".join(alias)) if alias else "—"))
        add("")

    # ---------------- 四
    add("## 四、题库 12 个知识域 → 单元映射")
    add("")
    add("> 旧题库按“知识域 1~12”组织，Tag 库按“单元”组织。下表由实际打标结果统计得出，可直接用于迁移：新题按单元入库，旧题保留知识域编号但以 tag_id 为准。")
    add("")
    add("| 题库知识域 | 题号 | 命中单元（题数） | 主要模块（命中 tag 数） |")
    add("|:--|:--|:--|:--|")
    for d_idx, d_name in enumerate(domains, 1):
        qs = [q for q, _, _ in questions if q.startswith("Q{}-".format(d_idx))]
        if not qs:
            continue
        ucnt = Counter()
        mcnt = Counter()
        for q in qs:
            for tid in q_tags.get(q, []):
                ucnt[tid.split(".")[0]] += 1
                mcnt[tid.rsplit(".", 1)[0]] += 1
        u_txt = "、".join("{} {}".format(k, v) for k, v in ucnt.most_common())
        m_txt = "、".join("{} {}".format(k, v) for k, v in mcnt.most_common(3))
        add("| {} | {} | {} | {} |".format(md_cell(d_name), "、".join(qs), u_txt, m_txt))
    add("")

    # ---------------- 五
    add("## 五、tag → 题目反查（组题用）")
    add("")
    add("> 只列出题库已命中的 tag。组题 agent 拿到薄弱项 tag 后，直接在此取候选题目；未列出的 tag 说明“暂无对应练习”，需要补题。")
    add("")
    add("| tag ID | 三级 tag | 难度 | 题目 | 题数 |")
    add("|:--|:--|:--:|:--|:--:|")
    for u in units:
        for m in u["modules"]:
            for t in m["tags"]:
                qs = tag_questions[t["id"]]
                if not qs:
                    continue
                add("| `{}` | {} | {} | {} | {} |".format(
                    t["id"], md_cell(t["name"]), t["level"], "、".join(qs), len(qs)))
    add("")

    # ---------------- 六
    add("## 六、旧标签归一表（{} 条，迁移用）".format(len(used_legacy)))
    add("")
    add("> 把题库现有的两级标签逐条映射到叶子 tag。迁移脚本按此表批量替换，不需要人工判断；同一旧标签若曾被用于多道题，归一到同一 tag。")
    add("")
    add("| 旧标签（二级写法） | → tag ID | 归一后的三级路径 | 使用题数 |")
    add("|:--|:--|:--|:--:|")
    path_of = {}
    for u in units:
        for m in u["modules"]:
            for t in m["tags"]:
                path_of[t["id"]] = "{} / {} / {}".format(u["name"], m["name"], t["name"])
    for old, cnt in sorted(used_legacy.items(), key=lambda kv: (-kv[1], kv[0])):
        tid = legacy_map[old]
        add("| `{}` | `{}` | {} | {} |".format(old, tid, md_cell(path_of[tid]), cnt))
    add("")

    # ---------------- 七
    add("## 七、6 个主能力轴 ← 单元映射")
    add("")
    add("> 雷达图仍用 6 轴（`school/portal/rubric_agent.py` 的 `ABILITY_RULES`）。tag 库与 6 轴是**正交**的：tag 描述“考什么”，能力轴描述“哪方面弱”。下表保留原有关键词规则，并补充可用的单元聚合方式。")
    add("")
    add("| 能力轴 | 绑定评分维度 | 现有归类关键词 | 对应单元 | tag 数 |")
    add("|:--|:--|:--|:--|:--:|")
    for name, dim, desc, kws in ABILITY_RULES:
        us = [u for u in units if name in u["abilities"]]
        cnt = sum(len(m["tags"]) for u in us for m in u["modules"])
        add("| {} | `{}` | {} | {} | {} |".format(
            name, dim, md_cell(desc) + "（关键词：" + kws + "）",
            "、".join(u["id"] for u in us) or "—", cnt))
    add("")
    add("聚合口径：`能力得分 = Σ(tag 掌握度 × tag 权重)`，权重默认按该单元内 tag 数均分；若同一能力由多个单元贡献，按题量占比加权。这样雷达图的 6 个轴既能继续用旧关键词兜底，也能在 tag 齐全时走精确路径。")
    add("")

    # ---------------- 八
    add("## 八、两个 agent 的接入契约")
    add("")
    add("### 8.1 考点分析 agent（题目 → tag）")
    add("")
    add("在 `school/portal/rubric_agent.py` 的 `JSON_SCHEMA_HINT` 中，把 `knowledge_points[].name` 升级为带 `tag_id` 的结构：")
    add("")
    add("```json")
    add("{")
    add('  "knowledge_points": [')
    add('    {')
    add('      "tag_id": "U04.M02.T02",')
    add('      "tag_path": "列表与序列操作 / 切片 / 步长切片与反转",')
    add('      "name": "步长切片与反转",')
    add('      "confidence": 0.92,')
    add('      "detail": "1 起始计数换算为 0 起始下标，[::-1] 反转",')
    add('      "tasks": ["func301"]')
    add("    }")
    add("  ]")
    add("}")
    add("```")
    add("")
    add("约束（写进 prompt，并在解析侧硬校验）：")
    add("")
    add("1. **只能从 tag 库取叶子节点**，禁止新造词；prompt 中只注入候选清单（按题目文本预筛 Top-30），避免长上下文。")
    add("2. 每题输出 **3~5 个** tag，按 `confidence` 降序；至少 1 个 `基础` 难度 tag，用于判断“该模块是否学会”。")
    add("3. 命中不了任何叶子时，输出模块级占位 `tag_id = \"U04.M02\"` 并置 `\"unmapped\": true`，由人工补 tag；**不要**回落到自由文本。")
    add("4. `tag_id` 不在库中的结果整条丢弃（不猜测、不模糊匹配到别的考点）。")
    add("")
    add("python 侧校验片段：")
    add("")
    add("```python")
    add("def normalize_points(raw, tag_index):")
    add("    points = []")
    add("    for item in raw or []:")
    add("        tid = str(item.get(\"tag_id\", \"\")).strip()")
    add("        if tid not in tag_index:          # 只接受库里存在的叶子")
    add("            continue")
    add("        points.append({")
    add("            \"tag_id\": tid,")
    add("            \"name\": tag_index[tid][\"name\"],")
    add("            \"detail\": item.get(\"detail\", \"\"),")
    add("            \"tasks\": item.get(\"tasks\", []),")
    add("            \"confidence\": float(item.get(\"confidence\", 0.8)),")
    add("        })")
    add("    return points[:5]")
    add("```")
    add("")
    add("### 8.2 薄弱项组题 agent（tag → 题目）")
    add("")
    add("输入：`weak = [(tag_id, mastery)]`，`mastery ∈ [0,1]` 取自该 tag 的历史得分。")
    add("")
    add("```text")
    add("1. 排序       按 (1 - mastery) × 权重 降序，取前 3 个薄弱 tag 作为必覆盖项")
    add("2. 扩张候选   第 1 层：该 tag 下的题（精确命中）")
    add("             第 2 层：同模块兄弟 tag 的题（同一技能的邻近变体）")
    add("             第 3 层：前置模块的题（prereq 链，先补地基）")
    add("             第 4 层：同单元其他模块的题（保底，仅当上面不足）")
    add("3. 过滤       去掉最近 7 天做过的、已连续两次满分的")
    add("4. 难度配比   mastery < 0.4 → 基础 70% / 进阶 25% / 易错 5%")
    add("              0.4 ≤ mastery < 0.7 → 基础 50% / 进阶 40% / 易错 10%")
    add("              mastery ≥ 0.7 → 基础 30% / 进阶 55% / 易错 15%")
    add("5. 题量       n = clamp(3 + round((1 - mastery) * 7), 3, 10)")
    add("6. 覆盖校验   前 3 个薄弱 tag 各至少 1 题；不足则从第 2 层补齐")
    add("7. 输出       按 tag_id 分组返回，附带每题的命中理由（第几层、命中哪个 tag）")
    add("```")
    add("")
    add("### 8.3 结果回写（掌握度更新）")
    add("")
    add("一次作答结束后，对题目命中的每个 tag 更新掌握度（指数滑动平均，抗单次波动）：")
    add("")
    add("```python")
    add("def update_mastery(old: float, score: float, hits: int) -> float:")
    add("    # score: 本题得分率 0~1；hits: 该 tag 在本题中的权重系数（默认 1.0）")
    add("    alpha = min(0.35, 0.2 * hits)      # 命中越强，更新越快")
    add("    return round(old * (1 - alpha) + score * alpha, 4)")
    add("```")
    add("")

    # ---------------- 九
    add("## 九、机器可读文件")
    add("")
    add("路径：`tags/tags.json`（与本文件同源生成，勿手改）。结构：")
    add("")
    add("| 字段 | 类型 | 说明 |")
    add("|:--|:--|:--|")
    add("| `version` | str | 词表版本，tag 增删时自增 |")
    add("| `units[].id/name/stage/goal/abilities` | — | 一级信息与主能力归属 |")
    add("| `units[].modules[].id/name/goal/prereq` | — | 二级信息与前置模块（组题第 3 层用） |")
    add("| `units[].modules[].tags[]` | obj | `id / name / en / level / desc / aliases / legacy` |")
    add("| `index.by_name / by_en / by_alias / by_legacy` | map | 自由文本归一的四级查找表 |")
    add("| `questions` | map | 题号 → tag_id 列表 |")
    add("| `tag_questions` | map | tag_id → 题号列表 |")
    add("")
    add("归一查找顺序：`by_legacy`（旧二级标签精确）→ `by_alias`（同义词精确）→ `by_name`（名字精确）→ 包含匹配 → 交 LLM 兜底并标记 `unmapped`。")
    add("")

    # ---------------- 十
    add("## 十、维护规则")
    add("")
    add("1. **新增 tag**：在 `tools/taglib/spec_a|b|c.py` 对应模块追加一行（名字、英文键、难度、说明、旧标签、同义词），执行 `python tools/taglib/build.py`。生成器会校验重名、重键、旧标签重复映射。")
    add("2. **改名**：只改中文名，旧名放进 `aliases`，`tag_id` 不变。")
    add("3. **拆分**：`切片` → `切片` + `步长切片`，老 id 保留并把新 id 写进 `replaced_by`，历史成绩按老 id 归档不迁移。")
    add("4. **废弃**：不删行，标 `deprecated`，从 `index` 中排除但仍保留 `by_legacy` 映射，避免旧作业解析失败。")
    add("5. **补题**：第五节里没有题目的 tag 即“考纲有、题库缺”，是下一批命题的工单来源。")
    add("")

    # ---------------- 附录 A
    add("---")
    add("")
    add("## 附录 A　全部 tag 速查（按 ID）")
    add("")
    add("| tag ID | 三级 tag | 所属 | 难度 | 题数 |")
    add("|:--|:--|:--|:--:|:--:|")
    for u in units:
        for m in u["modules"]:
            for t in m["tags"]:
                add("| `{}` | {} | {} / {} | {} | {} |".format(
                    t["id"], md_cell(t["name"]), u["name"], m["name"], t["level"],
                    len(tag_questions[t["id"]])))
    add("")

    # ---------------- 附录 B
    add("## 附录 B　易混 tag 对照")
    add("")
    add("> 打标与错因归因时最容易串味的 14 组，命中时按右列口径区分。")
    add("")
    add("| 易混对 | tag ID | 区分口径 |")
    add("|:--|:--|:--|")
    for pair, tid, how in CONFUSABLE:
        add("| {} | `{}` | {} |".format(md_cell(pair), tid, md_cell(how)))
    add("")

    # ---------------- 附录 C
    add("## 附录 C　与题库、判题器的对接现状")
    add("")
    add("| 产物 | 现状 | 需要补的动作 |")
    add("|:--|:--|:--|")
    add("| `Python题库.md`（44 题 / 440 用例） | 每题已有 2~4 个旧标签，全部可归一（见第六节） | 把标签行替换为 `tag_id` 列表即可完成迁移 |")
    add("| `qbank-package/`（gold/sample/data） | 判题只认函数名与用例，与 tag 无关 | 无需改动 |")
    add("| `school/portal/rubric_agent.py` | `knowledge_points[].name` 为自由文本 | 按 8.1 换成 `tag_id` + 本地校验 |")
    add("| 雷达图 6 轴 | 关键词硬匹配 | 有 tag 后改为按单元聚合，关键词作为兜底 |")
    add("")

    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")

    # ---------------- JSON
    tags_json = {
        "version": "1.0.0",
        "generated_at": "generated-by-tools/taglib/build.py",
        "units": units,
        "index": {
            "by_name": {t["name"]: t["id"] for t in flat},
            "by_en": {t["en"]: t["id"] for t in flat},
            "by_alias": {a: t["id"] for t in flat for a in t["aliases"]},
            "by_legacy": dict(sorted(legacy_map.items())),
        },
        "questions": q_tags,
        "tag_questions": {k: v for k, v in tag_questions.items() if v},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(tags_json, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")

    print("单元 {} 个 / 模块 {} 个 / tag {} 个".format(len(units), module_count, len(flat)))
    print("难度分布: 基础 {基础} 进阶 {进阶} 易错 {易错}".format(**level_stat))
    print("题库: {} 题 / {} 个旧标签，全部归一成功".format(len(questions), len(used_legacy)))
    print("已被题目命中的 tag: {} ({:.0%})".format(covered, covered / len(flat)))
    print("Markdown: {} 行 -> {}".format(len(md), OUT_MD.name))
    print("JSON: {} -> {}".format(OUT_JSON.stat().st_size, OUT_JSON.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
