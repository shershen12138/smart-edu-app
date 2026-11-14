"""综合能力画像的维度定义与「题目 → 能力维度」映射规则。

两个维度体系，互相独立、都由题目承载：

- 布鲁姆认知水平六维：记忆 / 理解 / 应用 / 分析 / 评估 / 创造；
- 计算思维四维：抽象 / 分解 / 算法 / 模式识别（键与题库打标一致）。

映射口径：先按知识点 Tag 反查它在《Python教学Tag库》里所属的模块，
再用模块表 ``MODULE_CAPABILITY`` 得到该模块默认考察的布鲁姆层级与思维维度；
Tag 无法归一时按题目名称关键词兜底，仍无法判断时默认「应用 + 算法」。

这张表只决定「题目考什么」，不决定「学生得多少分」——分数由评测报告里
逐题得分率按分值加权聚合，保证可复现、可解释。
"""

from __future__ import annotations

import re
from functools import lru_cache

from tools.taglib import loader as taglib

# 映射口径调整后递增，令学生画像签名失效并自动重算。
VERSION = 'cap-1'

# (键, 中文名, 判定说明)
BLOOM_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ('remember', '记忆', '语法、关键字、内置函数与常用写法能否准确回忆'),
    ('understand', '理解', '能否解释语义规则，如类型转换、取模整除、作用域'),
    ('apply', '应用', '能否把学过的模板与写法套用到新题目并跑通用例'),
    ('analyze', '分析', '能否拆解多步任务、定位缺陷并说明错误原因'),
    ('evaluate', '评估', '能否判断边界、健壮性与复杂度，主动检查代码质量'),
    ('create', '创造', '能否自主设计数据结构与解法，写出非模板化的实现'),
)

THINKING_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ('abstraction', '抽象', '把现实问题抽取为变量、数据结构与规则，忽略无关细节'),
    ('decomposition', '分解', '把复杂任务拆成若干简单、可执行的子任务'),
    ('algorithm', '算法', '按明确步骤与控制流解决问题，覆盖边界与异常'),
    ('pattern', '模式识别', '发现重复规律与共性，并迁移到相似问题'),
)

BLOOM_LABELS = {key: label for key, label, _note in BLOOM_DIMENSIONS}
THINKING_LABELS = {key: label for key, label, _note in THINKING_DIMENSIONS}

# 等级：分数区间下界 → (等级, 说明)
LEVELS: tuple[tuple[float, str, str], ...] = (
    (85.0, 'A', '优秀'),
    (70.0, 'B', '良好'),
    (55.0, 'C', '及格'),
    (0.0, 'D', '待提升'),
)

# 《Python教学Tag库》模块 → (布鲁姆层级, 计算思维维度)。
# 模块清单与 data/Python教学Tag库_v1.0.md 的 15 单元 / 77 模块一一对应。
MODULE_CAPABILITY: dict[str, tuple[str, str]] = {
    # U01 环境搭建与开发工具
    'U01-M01': ('remember', 'decomposition'),
    'U01-M02': ('remember', 'decomposition'),
    'U01-M03': ('understand', 'decomposition'),
    'U01-M04': ('evaluate', 'abstraction'),
    # U02 变量与基础数据类型
    'U02-M01': ('understand', 'abstraction'),
    'U02-M02': ('understand', 'abstraction'),
    'U02-M03': ('remember', 'abstraction'),
    'U02-M04': ('apply', 'pattern'),
    'U02-M05': ('apply', 'abstraction'),
    'U02-M06': ('understand', 'abstraction'),
    # U03 运算符与表达式
    'U03-M01': ('apply', 'algorithm'),
    'U03-M02': ('apply', 'algorithm'),
    'U03-M03': ('apply', 'algorithm'),
    'U03-M04': ('understand', 'abstraction'),
    # U04 流程控制
    'U04-M01': ('apply', 'algorithm'),
    'U04-M02': ('apply', 'algorithm'),
    'U04-M03': ('analyze', 'algorithm'),
    'U04-M04': ('analyze', 'pattern'),
    # U05 容器数据类型
    'U05-M01': ('apply', 'algorithm'),
    'U05-M02': ('apply', 'algorithm'),
    'U05-M03': ('understand', 'abstraction'),
    'U05-M04': ('apply', 'abstraction'),
    'U05-M05': ('apply', 'abstraction'),
    'U05-M06': ('analyze', 'pattern'),
    # U06 函数
    'U06-M01': ('understand', 'decomposition'),
    'U06-M02': ('analyze', 'decomposition'),
    'U06-M03': ('analyze', 'abstraction'),
    'U06-M04': ('analyze', 'abstraction'),
    'U06-M05': ('create', 'pattern'),
    'U06-M06': ('apply', 'pattern'),
    # U07 模块、包与标准库
    'U07-M01': ('understand', 'decomposition'),
    'U07-M02': ('understand', 'decomposition'),
    'U07-M03': ('apply', 'algorithm'),
    'U07-M04': ('apply', 'abstraction'),
    'U07-M05': ('apply', 'decomposition'),
    'U07-M06': ('apply', 'pattern'),
    'U07-M07': ('analyze', 'pattern'),
    # U08 文件与数据持久化
    'U08-M01': ('apply', 'algorithm'),
    'U08-M02': ('apply', 'decomposition'),
    'U08-M03': ('apply', 'abstraction'),
    'U08-M04': ('analyze', 'abstraction'),
    # U09 异常处理与调试
    'U09-M01': ('understand', 'algorithm'),
    'U09-M02': ('evaluate', 'decomposition'),
    'U09-M03': ('evaluate', 'decomposition'),
    # U10 面向对象编程
    'U10-M01': ('understand', 'abstraction'),
    'U10-M02': ('analyze', 'abstraction'),
    'U10-M03': ('analyze', 'abstraction'),
    'U10-M04': ('evaluate', 'abstraction'),
    'U10-M05': ('apply', 'abstraction'),
    'U10-M06': ('create', 'abstraction'),
    # U11 高阶特性
    'U11-M01': ('analyze', 'abstraction'),
    'U11-M02': ('create', 'abstraction'),
    'U11-M03': ('analyze', 'abstraction'),
    'U11-M04': ('understand', 'abstraction'),
    # U12 数据处理、可视化与办公自动化
    'U12-M01': ('apply', 'abstraction'),
    'U12-M02': ('apply', 'abstraction'),
    'U12-M03': ('analyze', 'decomposition'),
    'U12-M04': ('apply', 'pattern'),
    'U12-M05': ('apply', 'decomposition'),
    # U13 网络请求与爬虫
    'U13-M01': ('understand', 'abstraction'),
    'U13-M02': ('apply', 'algorithm'),
    'U13-M03': ('analyze', 'pattern'),
    'U13-M04': ('evaluate', 'decomposition'),
    'U13-M05': ('create', 'decomposition'),
    # U14 算法与编程题专项
    'U14-M01': ('evaluate', 'algorithm'),
    'U14-M02': ('apply', 'algorithm'),
    'U14-M03': ('analyze', 'algorithm'),
    'U14-M04': ('create', 'abstraction'),
    'U14-M05': ('analyze', 'pattern'),
    'U14-M06': ('create', 'decomposition'),
    'U14-M07': ('create', 'decomposition'),
    'U14-M08': ('analyze', 'pattern'),
    'U14-M09': ('apply', 'algorithm'),
    # U15 工程实践与项目实战
    'U15-M01': ('analyze', 'decomposition'),
    'U15-M02': ('evaluate', 'decomposition'),
    'U15-M03': ('understand', 'decomposition'),
    'U15-M04': ('create', 'decomposition'),
}

# 单元兜底：模块表缺项时按单元给默认层级。
_UNIT_DEFAULT: dict[str, tuple[str, str]] = {
    'U01': ('remember', 'decomposition'),
    'U02': ('understand', 'abstraction'),
    'U03': ('apply', 'algorithm'),
    'U04': ('apply', 'algorithm'),
    'U05': ('apply', 'abstraction'),
    'U06': ('analyze', 'decomposition'),
    'U07': ('apply', 'abstraction'),
    'U08': ('apply', 'decomposition'),
    'U09': ('evaluate', 'decomposition'),
    'U10': ('analyze', 'abstraction'),
    'U11': ('analyze', 'abstraction'),
    'U12': ('apply', 'abstraction'),
    'U13': ('apply', 'decomposition'),
    'U14': ('create', 'algorithm'),
    'U15': ('create', 'decomposition'),
}

# 名称关键词兜底：按顺序取第一个命中的层级。
_BLOOM_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (('递归', '回溯', '动态规划', '装饰器', '生成器', '项目', '设计', '优化'), 'create'),
    (('测试', '规范', '健壮', '边界', '复杂度', '审查', '重构'), 'evaluate'),
    (('调试', '异常', '排序', '查找', '嵌套', '统计', '多条件'), 'analyze'),
    (('函数', '文件', '字典', '列表', '字符串', '正则', '库', '数据'), 'apply'),
    (('运算', '转换', '作用域', '类与对象', '模块', '变量', '类型'), 'understand'),
)

_THINKING_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (('递归', '回溯', '动态规划', '综合', '项目', '函数', '模块'), 'decomposition'),
    (('排序', '查找', '遍历', '循环', '运算', '统计', '文件'), 'algorithm'),
    (('字符串', '正则', '模式', '去重', '计数', '切片'), 'pattern'),
    (('类', '对象', '字典', '集合', '类型', '数据', '设计'), 'abstraction'),
)

_MODULE_CODE_RE = re.compile(r'^(U\d+-M\d+)')


@lru_cache(maxsize=1)
def tag_module_index() -> dict[str, str]:
    """Tag 标准名 → 模块编号（如 ``U05-M02``）。"""
    index: dict[str, str] = {}
    for _unit, module, tags in taglib.tag_modules():
        match = _MODULE_CODE_RE.match(module)
        if not match:
            continue
        code = match.group(1)
        for tag in tags:
            index[tag] = code
    return index


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {key: round(value / total, 4) for key, value in weights.items() if value > 0}


def _keyword_hit(text: str, rules: tuple[tuple[tuple[str, ...], str], ...]) -> str:
    for words, key in rules:
        if any(word in text for word in words):
            return key
    return ''


def classify_labels(
    labels: list[str] | tuple[str, ...], title: str = ''
) -> tuple[dict[str, float], dict[str, float]]:
    """把题目知识点与名称映射成布鲁姆 / 计算思维权重。

    返回 ``(bloom_weights, thinking_weights)``，各自归一化（合计 1）；
    多个知识点来自不同模块时按个数平分，无法判断时回退「应用 + 算法」。
    """
    bloom: dict[str, float] = {}
    thinking: dict[str, float] = {}
    index = tag_module_index()
    for raw in labels:
        name = str(raw or '').strip()
        if not name:
            continue
        tag = taglib.normalize_tag(name) or name
        module = index.get(tag, '')
        capability = MODULE_CAPABILITY.get(module) if module else None
        if capability is None and module[:3] in _UNIT_DEFAULT:
            capability = _UNIT_DEFAULT[module[:3]]
        if capability is None:
            bloom_key = _keyword_hit(name, _BLOOM_KEYWORDS) or 'apply'
            thinking_key = _keyword_hit(name, _THINKING_KEYWORDS) or 'algorithm'
        else:
            bloom_key, thinking_key = capability
        bloom[bloom_key] = bloom.get(bloom_key, 0.0) + 1.0
        thinking[thinking_key] = thinking.get(thinking_key, 0.0) + 1.0

    if not bloom:
        text = str(title or '')
        bloom_key = _keyword_hit(text, _BLOOM_KEYWORDS) or 'apply'
        thinking_key = _keyword_hit(text, _THINKING_KEYWORDS) or 'algorithm'
        bloom[bloom_key] = 1.0
        thinking[thinking_key] = 1.0
    return _normalize_weights(bloom), _normalize_weights(thinking)


def level_of(score: float) -> tuple[str, str]:
    """分数 → (等级字母, 中文说明)。"""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 'D', '待提升'
    for floor, letter, label in LEVELS:
        if value >= floor:
            return letter, label
    return 'D', '待提升'


def coverage_text(coverage: float) -> str:
    """覆盖率 → 样本说明，避免把「没考到」误读成「不会」。"""
    try:
        value = float(coverage)
    except (TypeError, ValueError):
        value = 0.0
    percent = round(max(0.0, min(1.0, value)) * 100)
    if percent <= 0:
        return '暂无该维度的判题记录'
    if percent < 30:
        return f'样本较少（覆盖 {percent}% 分值）'
    return f'覆盖 {percent}% 分值'
