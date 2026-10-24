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
2. 生成 5 分制评分量表，维度控制在 6 个，key 必须从下列维度池中选择且不重复：
   {dimension_lines}
3. 权重合计必须等于 100；
4. 每个维度的 5/4/3/2/1 分描述要能直接据此判断学生代码，不使用“较好”“一般”这类空话；
5. markdown 必须包含两节，表头固定：
   ## 一、作业考察的知识点
   （表格列：序号 | 知识点 | 说明 | 涉及题目）
   ## 二、5 分制量表
   （表格列：维度 | 权重 | 5 分 | 4 分 | 3 分 | 2 分 | 1 分）

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


def render_markdown(context: dict[str, Any], points: list[dict], dimensions: list[dict]) -> str:
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
            '> 评分说明：5 分制按维度打分，换算为百分制后按权重加权求和；'
            '雷达图各轴即本表维度。',
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
    markdown = str(data.get('markdown', '')).strip()
    if '5 分制量表' not in markdown or '知识点' not in markdown:
        markdown = render_markdown(context, points, dimensions)
    return {'points': points, 'dimensions': dimensions, 'markdown': markdown}


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
    return {
        'points': points,
        'dimensions': dimensions,
        'markdown': render_markdown(context, points, dimensions),
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
            'source': source,
            'model': model,
            'prompt_version': PROMPT_VERSION,
        },
    )
    return rubric
