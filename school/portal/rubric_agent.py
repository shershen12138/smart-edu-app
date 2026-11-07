"""题目分析智能体：把教师上传的题目交给大模型，产出可执行的评分标准。

设计边界：
- 只在配置了 OpenAI 兼容端点时调用模型；未配置时抛 LLMNotConfigured，
  需要演示或离线运行时必须显式 `offline=True`，结果标记为“规则兜底”；
- 模型输出必须落到固定维度池，避免每次生成不同维度导致雷达图无法比较；
- 生成结果保存到数据库（CourseworkRubric），同时供质量评测读取。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from django.utils import timezone

from school.course_models import CourseworkRubric

from tools.code_quality_agent import curriculum
from tools.code_quality_agent import models as agent_models

PROMPT_VERSION = 'v1'

DIMENSION_POOL: dict[str, str] = {
    'knowledge': '知识点覆盖',
    'syntax': '语法与规范',
    'boundary': '边界与健壮性',
    'logic': '题意正确性',
    'structure': '代码结构',
    'readability': '可读性',
}

DEFAULT_WEIGHTS = {
    'knowledge': 25,
    'syntax': 20,
    'boundary': 15,
    'logic': 25,
    'structure': 5,
    'readability': 10,
}

# 雷达图的 6 个主能力：由“作业考察的知识点”归纳而来，每项绑定一个评分维度，
# 从而既能换轴名，又能直接用该维度的分数作图。
# (能力名, 绑定维度 key, 说明, 归类关键词)
ABILITY_RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        '数据组织与容器操作',
        'knowledge',
        '列表、字典、集合、元组、切片、排序与去重等数据结构操作',
        '列表 字典 集合 元组 切片 索引 排序 去重 保序 二维 键值 插入 合并 反转 队列 栈',
    ),
    (
        '流程控制与分支循环',
        'logic',
        '条件分支、循环遍历、累加计数与多分支返回',
        '循环 for while 分支 条件 判断 遍历 计数 累加 嵌套 枚举 阶梯 统计 分类 范围',
    ),
    (
        '字符串与内置方法',
        'syntax',
        '字符串处理、类型与进制转换、常用内置函数',
        '字符串 字符 ASCII 编码 进制 转换 内置 格式化 拼接 split join len max min',
    ),
    (
        '函数设计与结构',
        'structure',
        '函数定义、参数与返回值、职责拆分与结构组织',
        '函数 封装 返回值 参数 结构 模块 调用 定义',
    ),
    (
        '边界与异常处理',
        'boundary',
        '空列表、越界、非法输入与特殊值等边界情况',
        '边界 健壮 鲁棒 异常 空列表 越界 特殊值 非法 合法性',
    ),
    (
        '规范与可读性',
        'readability',
        '命名、注释、缩进与代码风格',
        '命名 注释 缩进 规范 可读 风格 格式',
    ),
)

LEVEL_TEXT = {
    'knowledge': (
        '全部题目要求的知识点都正确使用，写法与题意一致',
        '绝大多数知识点使用正确，个别题目写法可优化',
        '主要知识点已覆盖，存在 1-2 题未体现要求的方法',
        '知识点覆盖不足，多题未使用题目要求的方法',
        '基本未体现题目要求的知识点',
    ),
    'syntax': (
        '无语法错误，pylint 无 error 级问题',
        '无语法错误，仅少量规范提示',
        '可正常运行，存在少量未定义名或未使用变量',
        '存在语法错误，部分函数无法解析',
        '多处语法错误，文件无法整体运行',
    ),
    'boundary': (
        '空列表、单元素、偶数长度、上界等边界均处理正确',
        '边界基本正确，个别场景未覆盖',
        '存在 1-2 处越界或上界差一错误',
        '多处边界处理错误，容易在样例以外数据上失败',
        '几乎未考虑边界情况',
    ),
    'logic': (
        '返回值、比较方向、类型判断等与题意完全一致',
        '仅个别细节与题意有偏差',
        '存在 2-3 处与题意不一致的实现',
        '多处逻辑与题目要求相反或顺序错误',
        '核心逻辑与题意不符，结果不可用',
    ),
    'structure': (
        '函数职责单一，缩进层次清晰，无重复代码',
        '结构较清晰，个别函数偏长',
        '存在少量重复或嵌套偏深',
        '函数过长、嵌套过深，结构混乱',
        '未按题目拆分函数，代码难以维护',
    ),
    'readability': (
        '命名达意，无未使用变量，格式规范',
        '命名基本达意，存在少量规范提示',
        '单字母变量较多，可读性一般',
        '命名随意、缺少必要注释，阅读困难',
        '代码格式混乱，难以阅读',
    ),
}

JSON_SCHEMA_HINT = """{
  "knowledge_points": [
    {"name": "列表切片", "detail": "1 起始计数换算为 0 起始下标", "tasks": ["func301"]}
  ],
  "abilities": [
    {"label": "数据组织与容器操作", "detail": "列表、切片与排序等容器操作",
     "dimension": "knowledge", "points": ["列表切片"]}
  ],
  "dimensions": [
    {"key": "knowledge", "label": "知识点覆盖", "weight": 25,
     "five": "5 分表现", "four": "4 分表现", "three": "3 分表现",
     "two": "2 分表现", "one": "1 分表现"}
  ],
  "markdown": "完整的 Markdown 文本"
}"""


class LLMNotConfigured(RuntimeError):
    """没有可用的模型端点或密钥。"""


class LLMError(RuntimeError):
    """端点调用失败。"""


class RubricParseError(ValueError):
    """模型返回内容无法解析成合法评分标准。"""


def default_dimensions() -> list[agent_models.Dimension]:
    """没有作业评分标准时的兜底维度：与题目分析智能体的 6 个维度一致。

    不再读取仓库里的通用量表文件，避免所有作业共用同一套维度。
    """
    return [
        agent_models.Dimension(key, label, DEFAULT_WEIGHTS[key] / 100)
        for key, label in DIMENSION_POOL.items()
    ]


def llm_configured() -> bool:
    return bool(settings.LLM_BASE_URL and settings.LLM_API_KEY and settings.LLM_MODEL)


def llm_status() -> str:
    if llm_configured():
        return f'已配置：{settings.LLM_MODEL} @ {settings.LLM_BASE_URL}'
    return '未配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，只能使用规则兜底'


def coursework_context(coursework) -> dict[str, Any]:
    items = [
        {
            'function': item.function_name,
            'title': item.title,
            'points': item.points,
        }
        for item in coursework.items.all()
    ]
    return {
        'title': coursework.title,
        'category': coursework.category,
        'description': coursework.description,
        'grading_mode': coursework.get_grading_mode_display(),
        'items': items,
    }


def build_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    dimension_lines = '、'.join(f'{key}（{label}）' for key, label in DIMENSION_POOL.items())
    system = (
        '你是高校 Python 课程的助教，负责把作业题目拆解成可执行、可比较的评分标准。'
        '只输出 JSON，不要输出解释性文字。'
    )
    user = f"""题目信息（来自教师上传的作业，JSON）：
{json.dumps(context, ensure_ascii=False, indent=2)}

任务：
1. 分析这道作业考察以及涉及的知识点，逐条写清楚，并标注涉及哪些函数题；
2. 评分维度池（key（中文名））：{dimension_lines}。生成 5 分制评分量表时，维度控制在 6 个，key 必须从该池中选择且不重复；
3. 从第 1 步的知识点中归纳 6 个主能力，作为雷达图的 6 根轴：每个能力给出名称、说明、涵盖的知识点名称，并从维度池中各选一个 key（6 个能力互不重复），该能力的分数取所绑定维度的分数；
4. 权重合计必须等于 100；
5. 每个维度的 5/4/3/2/1 分描述要能直接据此判断学生代码，不使用“较好”“一般”这类空话；
6. markdown 必须包含三节，表头固定：
   ## 一、作业考察的知识点
   （表格列：序号 | 知识点 | 说明 | 涉及题目）
   ## 二、5 分制量表
   （表格列：维度 | 权重 | 5 分 | 4 分 | 3 分 | 2 分 | 1 分）
   ## 三、主能力（雷达图维度）
   （表格列：主能力 | 对应评分维度 | 涵盖知识点）

输出 JSON，结构如下：
{JSON_SCHEMA_HINT}
"""
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def chat(messages: list[dict[str, str]], temperature: float = 0.2) -> str:
    if not llm_configured():
        raise LLMNotConfigured('未配置大模型端点，无法调用题目分析智能体。')
    base = settings.LLM_BASE_URL
    url = base if base.endswith('/chat/completions') else base + '/chat/completions'
    body = json.dumps(
        {
            'model': settings.LLM_MODEL,
            'messages': messages,
            'temperature': temperature,
        }
    ).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {settings.LLM_API_KEY}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.LLM_TIMEOUT) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:200]
        raise LLMError(f'大模型返回 HTTP {exc.code}：{detail}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f'无法连接大模型端点：{exc}') from exc
    try:
        return payload['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError('大模型返回格式不符合对话补全约定。') from exc


def _extract_json(text: str) -> str:
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find('{'), text.rfind('}')
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise RubricParseError('模型输出中没有找到 JSON 对象。')


def normalize_dimensions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise RubricParseError('dimensions 必须是数组。')
    seen: set[str] = set()
    dimensions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key', '')).strip()
        if key not in DIMENSION_POOL or key in seen:
            continue
        seen.add(key)
        try:
            weight = float(item.get('weight', 0))
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            weight = float(DEFAULT_WEIGHTS[key])
        levels = {}
        for mark, field in (('5', 'five'), ('4', 'four'), ('3', 'three'), ('2', 'two'), ('1', 'one')):
            levels[mark] = str(item.get(field, '')).strip() or LEVEL_TEXT[key][5 - int(mark)]
        dimensions.append(
            {
                'key': key,
                'label': DIMENSION_POOL[key],
                'weight': weight,
                'levels': levels,
            }
        )
    if len(dimensions) < 5:
        raise RubricParseError(f'有效维度只有 {len(dimensions)} 个，至少需要 5 个。')
    dimensions = dimensions[:6]
    total = sum(item['weight'] for item in dimensions)
    for item in dimensions:
        item['weight'] = round(item['weight'] / total * 100, 1)
    return dimensions


def normalize_points(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    points = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name', '')).strip()
        if not name:
            continue
        tasks = item.get('tasks') or []
        points.append(
            {
                'name': name,
                'detail': str(item.get('detail', '')).strip(),
                'tasks': [str(task) for task in tasks if str(task).strip()],
            }
        )
    return points[:20]


def rule_abilities(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按关键词把知识点归到 6 个主能力。

    每个能力绑定一个评分维度，保证雷达图始终是 6 根轴；没有大模型时用它兜底，
    旧评分标准（没有 abilities 字段）也按同样规则在出报告时补算。
    """
    grouped: dict[str, list[str]] = {label: [] for label, _, _, _ in ABILITY_RULES}
    for point in points:
        text = f"{point.get('name', '')} {point.get('detail', '')}"
        for label, _, _, keywords in ABILITY_RULES:
            if any(word in text for word in keywords.split()):
                grouped[label].append(str(point.get('name', '')).strip())
                break
    abilities = []
    for label, dimension, detail, _ in ABILITY_RULES:
        covered = [name for name in grouped[label] if name]
        abilities.append(
            {
                'label': label,
                'detail': detail,
                'dimension': dimension,
                'points': covered,
            }
        )
    return abilities


def normalize_abilities(
    raw: Any,
    points: list[dict[str, Any]],
    allowed: set[str] | None = None,
) -> list[dict[str, Any]]:
    """校验模型给出的 6 个主能力；不足 6 个或维度重复时退回规则归类。"""
    if not isinstance(raw, list):
        return rule_abilities(points)
    allowed = allowed or set(DIMENSION_POOL)
    abilities: list[dict[str, Any]] = []
    used: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get('label', '')).strip()
        dimension = str(item.get('dimension', '')).strip()
        if not label or dimension not in allowed or dimension in used:
            continue
        used.add(dimension)
        abilities.append(
            {
                'label': label,
                'detail': str(item.get('detail', '')).strip(),
                'dimension': dimension,
                'points': [
                    str(name).strip()
                    for name in item.get('points') or []
                    if str(name).strip()
                ][:8],
            }
        )
        if len(abilities) == 6:
            break
    if len(abilities) < 6:
        return rule_abilities(points)
    return abilities


def render_markdown(
    context: dict[str, Any],
    points: list[dict],
    dimensions: list[dict],
    abilities: list[dict],
) -> str:
    lines = [
        f"# {context['title']} · 评分标准",
        '',
        f'> 题量：{len(context['items'])} 题 · 批阅方式：{context['grading_mode']}',
        '',
        '## 一、作业考察的知识点',
        '',
        '| 序号 | 知识点 | 说明 | 涉及题目 |',
        '| --- | --- | --- | --- |',
    ]
    for index, point in enumerate(points, start=1):
        tasks = '、'.join(point['tasks']) or '全部题目'
        lines.append(f"| {index} | {point['name']} | {point['detail']} | {tasks} |")
    lines.extend(
        [
            '',
            '## 二、5 分制量表',
            '',
            '| 维度 | 权重 | 5 分 | 4 分 | 3 分 | 2 分 | 1 分 |',
            '| --- | --- | --- | --- | --- | --- | --- |',
        ]
    )
    for dimension in dimensions:
        levels = dimension['levels']
        lines.append(
            f"| {dimension['label']} | {dimension['weight']:.0f}% | "
            f"{levels['5']} | {levels['4']} | {levels['3']} | "
            f"{levels['2']} | {levels['1']} |"
        )
    lines.extend(
        [
            '',
            '## 三、主能力（雷达图维度）',
            '',
            '| 主能力 | 对应评分维度 | 涵盖知识点 |',
            '| --- | --- | --- |',
        ]
    )
    for ability in abilities:
        covered = '、'.join(ability.get('points') or []) or '全部知识点'
        dimension = ability.get('dimension', '')
        label = DIMENSION_POOL.get(dimension, dimension)
        lines.append(f"| {ability.get('label', '')} | {label} | {covered} |")
    lines.extend(
        [
            '',
            '> 评分说明：5 分制按维度打分，换算为百分制后按权重加权求和；'
            '雷达图各轴为“主能力”，分数取所绑定评分维度的得分。',
        ]
    )
    return '\n'.join(lines) + '\n'


def parse_response(text: str, context: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(_extract_json(text))
    if not isinstance(data, dict):
        raise RubricParseError('模型输出的 JSON 顶层不是对象。')
    points = normalize_points(data.get('knowledge_points'))
    if not points:
        raise RubricParseError('模型没有给出任何知识点。')
    dimensions = normalize_dimensions(data.get('dimensions'))
    abilities = normalize_abilities(data.get('abilities'), points)
    markdown = str(data.get('markdown', '')).strip()
    if (
        '5 分制量表' not in markdown
        or '知识点' not in markdown
        or '主能力' not in markdown
    ):
        markdown = render_markdown(context, points, dimensions, abilities)
    return {
        'points': points,
        'abilities': abilities,
        'dimensions': dimensions,
        'markdown': markdown,
    }


def rule_based(context: dict[str, Any]) -> dict[str, Any]:
    """离线兜底：基于题库规格与函数名推断知识点，不声称是模型结果。"""
    known = {}
    for specs in curriculum.COURSE_SPECS.values():
        for spec in specs:
            known[spec.task_id] = spec

    points: list[dict[str, Any]] = []
    for item in context['items']:
        spec = known.get(item['function'])
        if spec is None:
            points.append(
                {
                    'name': '通用程序设计',
                    'detail': f"{item['title']}：函数定义、返回值与基本逻辑",
                    'tasks': [item['function']],
                }
            )
            continue
        for tag in spec.points:
            label = curriculum.POINT_LABELS.get(tag, tag)
            existing = next((point for point in points if point['name'] == label), None)
            if existing:
                existing['tasks'].append(item['function'])
            else:
                points.append(
                    {
                        'name': label,
                        'detail': spec.title,
                        'tasks': [item['function']],
                    }
                )

    dimensions = []
    for key, label in DIMENSION_POOL.items():
        levels = {str(5 - index): text for index, text in enumerate(LEVEL_TEXT[key])}
        dimensions.append(
            {
                'key': key,
                'label': label,
                'weight': float(DEFAULT_WEIGHTS[key]),
                'levels': levels,
            }
        )
    abilities = rule_abilities(points)
    return {
        'points': points,
        'abilities': abilities,
        'dimensions': dimensions,
        'markdown': render_markdown(context, points, dimensions, abilities),
    }


def ensure_heading(markdown: str, context: dict[str, Any]) -> str:
    """模型可能直接返回“## 一、”，补上一级标题与题目信息，保证文件可独立阅读。"""
    text = markdown.strip()
    if text.startswith('# '):
        return text + '\n'
    heading = (
        f"# {context['title']} · 评分标准\n\n"
        f"> 题量：{len(context['items'])} 题 · 批阅方式：{context['grading_mode']}\n\n"
    )
    return heading + text + '\n'


def build_ability_messages(
    context: dict[str, Any],
    points: list[dict[str, Any]],
    dimension_keys: list[str],
) -> list[dict[str, str]]:
    system = (
        '你是高校 Python 课程助教，负责把作业考察的知识点归纳成雷达图的主能力。'
        '只输出 JSON，不要解释。'
    )
    user = f"""作业：{context['title']}
考察知识点：
{json.dumps(points, ensure_ascii=False)}
可用评分维度 key：{'、'.join(dimension_keys)}

请把这些知识点归纳成 6 个主能力，作为雷达图的 6 根轴：
1. label 不超过 8 个汉字，要体现这道作业的具体内容，不要写“综合能力”；
2. points 填属于该能力的知识点名称；
3. dimension 从可用 key 中各选一个，6 个互不重复。

输出 JSON：
{{"abilities": [{{"label": "字符串进制转换", "detail": "……", "dimension": "syntax", "points": ["……"]}}]}}
"""
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def generate_abilities(coursework, offline: bool = False) -> list[dict[str, Any]]:
    """按该任务已有的考察知识点重新归纳 6 个主能力并存库。

    只更新 abilities，不改动教师确认过的量表与知识点。
    """
    rubric = getattr(coursework, 'rubric', None)
    if rubric is None:
        raise RubricParseError('该作业还没有评分标准，无法归纳主能力。')
    points = rubric.knowledge_points or []
    if not points:
        raise RubricParseError('该作业的评分标准没有知识点。')
    keys = [
        str(item.get('key'))
        for item in rubric.dimensions or []
        if isinstance(item, dict) and item.get('key')
    ]
    allowed = set(keys) or set(DIMENSION_POOL)
    if offline or not llm_configured():
        abilities = rule_abilities(points)
    else:
        context = coursework_context(coursework)
        text = chat(build_ability_messages(context, points, sorted(allowed)))
        data = json.loads(_extract_json(text))
        abilities = normalize_abilities(data.get('abilities'), points, allowed)
    CourseworkRubric.objects.filter(pk=rubric.pk).update(abilities=abilities)
    rubric.abilities = abilities
    return abilities


def generate_for(coursework, offline: bool = False, force: bool = True) -> CourseworkRubric:
    existing = CourseworkRubric.objects.filter(coursework=coursework).first()
    if existing and not force:
        return existing

    context = coursework_context(coursework)
    if not context['items']:
        raise RubricParseError('该作业还没有题目清单，无法分析知识点。')

    if offline or not llm_configured():
        if not offline:
            raise LLMNotConfigured(
                '未配置大模型端点。请设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，'
                '或显式使用规则兜底。'
            )
        result = rule_based(context)
        source, model = 'rule', ''
    else:
        text = chat(build_messages(context))
        result = parse_response(text, context)
        source, model = 'llm', settings.LLM_MODEL

    rubric, _ = CourseworkRubric.objects.update_or_create(
        coursework=coursework,
        defaults={
            'markdown': ensure_heading(result['markdown'], context),
            'knowledge_points': result['points'],
            'dimensions': result['dimensions'],
            'abilities': result['abilities'],
            'source': source,
            'model': model,
            'prompt_version': PROMPT_VERSION,
        },
    )
    return rubric
