"""学生综合能力画像：布鲁姆六维 + 计算思维四维，供弱项分析页顶部展示。

分层设计（对应用户确认的方案）：

1. **规则层（确定性）**：从每份评测报告的逐题明细与判题结果取「题目 → 得分率」，
   题目能力维度由知识点 Tag → 模块映射得到（``capability_rules``），
   按任务分值加权聚合出六维 / 四维分数。没有覆盖的维度不记 0 分，返回 None。
2. **代码层（确定性）**：解析全部提交源码的 AST，统计函数、嵌套、推导式、
   魔法数字等结构事实，作为证据展示并送入大模型，不直接改分。
3. **诊断层（大模型，可选）**：把错误点、逐题得分与代码片段交给学生自己配置的
   模型，产出诊断摘要与带出处的观察；校验失败或未配置时退回规则诊断。

分数永远来自 1、2 两层，大模型只解释「为什么」和「怎么改」，保证可复现。
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import threading
from typing import Any

from django.db import close_old_connections, transaction
from django.utils import timezone

from school import storage
from school.course_models import Coursework, StudentCapabilityProfile
from school.models import User

from . import capability_rules, llm_client, quality_service
from .access import classes_for
from .llm_client import LLMError, LLMNotConfigured, chat

logger = logging.getLogger(__name__)

# 诊断提示词版本：调整口径后递增，旧画像自动重算。
PROMPT_VERSION = 'cap-llm-1'

# 送给大模型的代码上限，避免一次请求过大：单题 80 行、全部 400 行。
MAX_CODE_LINES = 80
MAX_TOTAL_CODE_LINES = 400
MAX_OBSERVATIONS = 6

_PENDING_STUDENTS: set[int] = set()
_SCHEDULE_LOCK = threading.Lock()


class DiagnosisError(ValueError):
    """大模型返回的诊断内容不可用。"""


def _clean(text: Any) -> str:
    return str(text or '').strip()


def _read_code(key: str) -> str:
    if not key:
        return ''
    try:
        return storage.read_private(key)
    except OSError:
        # 历史提交可能只剩记录、私有文件已清理：跳过代码证据即可。
        logger.debug('提交源码文件缺失 key=%s', key)
        return ''
    except Exception:
        logger.debug('读取提交源码失败 key=%s', key, exc_info=True)
        return ''


def _reported_entry(work, student_id):
    """该学生在本任务第一次带评测报告的提交（与弱项分析同口径）。"""
    return (
        work.entries.filter(
            student_id=student_id, status='done', quality_report__isnull=False
        )
        .order_by('sequence', 'pk')
        .first()
    )


def _rubric_labels(work) -> dict[str, list[str]]:
    """评分标准里每个函数考察的知识点（报告缺少标签时的兜底）。"""
    rubric = getattr(work, 'rubric', None)
    if rubric is None:
        return {}
    mapping: dict[str, list[str]] = {}
    for item in rubric.knowledge_points or []:
        if not isinstance(item, dict):
            continue
        name = _clean(item.get('name'))
        if not name:
            continue
        for function in item.get('tasks') or []:
            mapping.setdefault(_clean(function), []).append(name)
    return mapping


def _task_labels(detail: dict, fallback: list[str] | None) -> list[str]:
    labels: list[str] = []
    for point in detail.get('points') or []:
        if not isinstance(point, dict):
            continue
        label = _clean(point.get('label'))
        if label and label not in labels:
            labels.append(label)
    if labels:
        return labels
    return [name for name in (fallback or []) if name]


def _task_rate(question) -> float | None:
    """逐题得分率：优先判题得分，其次用例通过比例；无判定返回 None。"""
    if question is None:
        return None
    total = int(getattr(question, 'points', 0) or 0)
    score = getattr(question, 'score', None)
    if total > 0 and score is not None:
        return min(max(float(score) / total, 0.0), 1.0)
    cases = int(getattr(question, 'total_cases', 0) or 0)
    if cases > 0:
        return min(max(int(getattr(question, 'passed_cases', 0) or 0) / cases, 0.0), 1.0)
    return None


def collect_tasks(student) -> list[dict[str, Any]]:
    """收集该学生所有任务里可用的判题证据（每题一条）。"""
    works = (
        Coursework.objects.filter(
            classroom__in=classes_for(student),
            deleted_at__isnull=True,
            status='open',
        )
        .select_related('rubric')
        .prefetch_related('items', 'entries')
        .order_by('-pk')
    )
    tasks: list[dict[str, Any]] = []
    for work in works:
        entry = _reported_entry(work, student.pk)
        if entry is None:
            continue
        report = getattr(entry, 'quality_report', None)
        if report is None:
            continue
        payload = report.payload or {}
        by_task = {
            _clean(item.get('task_id')): item
            for item in payload.get('tasks') or []
            if isinstance(item, dict)
        }
        questions = {
            question.function_name: question for question in entry.questions.all()
        }
        rubric_labels = _rubric_labels(work)
        code = _read_code(entry.source_path)
        for item in work.items.all():
            detail = by_task.get(item.function_name, {})
            labels = _task_labels(detail, rubric_labels.get(item.function_name))
            bloom, thinking = capability_rules.classify_labels(labels, item.title)
            tasks.append(
                {
                    'work_id': work.pk,
                    'work_title': work.title,
                    'task_id': item.function_name,
                    'title': item.title,
                    'weight': float(item.points or 1),
                    'rate': _task_rate(questions.get(item.function_name)),
                    'labels': labels,
                    'issues': [
                        {
                            'line': _clean(issue.get('line')),
                            'message': _clean(issue.get('message')),
                            'advice': _clean(issue.get('advice')),
                            'severity': _clean(issue.get('severity')),
                        }
                        for issue in detail.get('issues') or []
                        if isinstance(issue, dict) and _clean(issue.get('message'))
                    ],
                    'code': code,
                    'code_hash': entry.source_hash,
                    'report_stamp': report.generated_at.isoformat()
                    if report.generated_at
                    else '',
                    'bloom': bloom,
                    'thinking': thinking,
                }
            )
    return tasks


def _walk_depth(node: ast.AST, depth: int = 0) -> int:
    """统计控制流最大嵌套深度（For/While/If/Try/With）。"""
    nested = isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.Try, ast.With))
    current = depth + 1 if nested else depth
    deepest = current
    for child in ast.iter_child_nodes(node):
        deepest = max(deepest, _walk_depth(child, current))
    return deepest


def _ast_facts(code: str) -> dict[str, int]:
    """单份源码的结构事实；语法不通过时返回空字典（该文件不计入）。"""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return {}
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    recursive = sum(1 for function in functions if function.name in calls)
    handlers = [
        handler
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    magic = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if not isinstance(node.value, bool) and node.value not in (0, 1, -1):
                magic += 1
    return {
        'lines': len(code.splitlines()),
        'functions': len(functions),
        'classes': sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef)),
        'comprehensions': sum(
            1
            for node in ast.walk(tree)
            if isinstance(
                node,
                (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
            )
        ),
        'loops': sum(
            1 for node in ast.walk(tree) if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        ),
        'tries': sum(1 for node in ast.walk(tree) if isinstance(node, ast.Try)),
        'bare_except': sum(1 for handler in handlers if handler.type is None),
        'magic_numbers': magic,
        'max_depth': _walk_depth(tree),
        'recursive_functions': recursive,
        'dict_literals': sum(1 for node in ast.walk(tree) if isinstance(node, (ast.Dict, ast.Set))),
    }


def code_facts(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总全部提交源码的结构事实（同一份源码只统计一次）。"""
    totals = {
        'files': 0,
        'lines': 0,
        'functions': 0,
        'classes': 0,
        'comprehensions': 0,
        'loops': 0,
        'tries': 0,
        'bare_except': 0,
        'magic_numbers': 0,
        'max_depth': 0,
        'recursive_functions': 0,
        'dict_literals': 0,
    }
    seen: set[int] = set()
    parsed = 0
    for task in tasks:
        if task['work_id'] in seen:
            continue
        seen.add(task['work_id'])
        facts = _ast_facts(task.get('code') or '')
        if not facts:
            continue
        parsed += 1
        for key, value in facts.items():
            if key == 'max_depth':
                totals[key] = max(totals[key], value)
            else:
                totals[key] += value
    totals['files'] = parsed
    totals['tasks'] = len(tasks)
    return totals


_CODE_HINTS = {
    'abstraction': '字典/集合字面量 {dict_literals} 处，魔法数字 {magic_numbers} 处',
    'decomposition': '自定义函数 {functions} 个，类 {classes} 个，最大嵌套 {max_depth} 层',
    'algorithm': '循环 {loops} 处，递归函数 {recursive_functions} 个，异常处理 {tries} 处',
    'pattern': '推导式 {comprehensions} 处，常量字面量 {magic_numbers} 处',
}


def _score_dimensions(
    tasks: list[dict[str, Any]],
    attr: str,
    dimensions: tuple[tuple[str, str, str], ...],
) -> list[dict[str, Any]]:
    """按任务分值加权聚合某一维度体系；无证据的维度 score=None。"""
    total_weight = sum(task['weight'] for task in tasks) or 0.0
    rows: list[dict[str, Any]] = []
    for key, label, note in dimensions:
        numerator = denominator = 0.0
        for task in tasks:
            share = float(task[attr].get(key, 0) or 0)
            rate = task['rate']
            if share <= 0 or rate is None:
                continue
            weight = task['weight'] * share
            numerator += weight * rate
            denominator += weight
        score = round(numerator / denominator * 100, 1) if denominator else None
        coverage = denominator / total_weight if total_weight else 0.0
        letter, level_label = capability_rules.level_of(score if score is not None else 0)
        rows.append(
            {
                'key': key,
                'label': label,
                'note': note,
                'score': score,
                'level': letter if score is not None else '',
                'level_label': level_label if score is not None else '',
                'coverage': round(coverage, 4),
                'coverage_percent': round(coverage * 100, 1),
                'coverage_text': capability_rules.coverage_text(coverage),
                'covered': score is not None,
                'evidence': _axis_evidence(tasks, attr, key, score),
            }
        )
    return rows


def _axis_evidence(
    tasks: list[dict[str, Any]], attr: str, key: str, score: float | None, limit: int = 2
) -> list[str]:
    """生成可核对的证据句：按「失分权重」取最典型的题，再补充高频错误。"""
    if score is None:
        return ['暂无覆盖该维度的判题记录']
    candidates = [
        task
        for task in tasks
        if float(task[attr].get(key, 0) or 0) > 0 and task['rate'] is not None
    ]
    evidence: list[str] = []
    scored = sorted(
        candidates,
        key=lambda task: -(task['weight'] * task[attr][key] * (1 - task['rate'])),
    )
    for task in scored[:limit]:
        if task['rate'] >= 0.999:
            continue
        reason = '；'.join(issue['message'] for issue in task['issues'][:1])
        suffix = f"，主要问题：{reason}" if reason else ''
        evidence.append(
            f"{task['task_id']}（{task['title']}）得分率 {round(task['rate'] * 100)}%{suffix}"
        )
    if not evidence:
        evidence.append('该维度涉及题目全部通过')
    return evidence


def _rule_summary(
    bloom: list[dict[str, Any]],
    thinking: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> list[str]:
    """离线诊断：指出最弱的两个维度与最高频错误，措辞与数据一致。"""
    summary: list[str] = []
    for rows, name in ((bloom, '布鲁姆认知'), (thinking, '计算思维')):
        covered = [row for row in rows if row['covered']]
        if not covered:
            continue
        weakest = min(covered, key=lambda row: row['score'])
        summary.append(
            f'{name}维度中「{weakest["label"]}」最弱'
            f'（{weakest["score"]} 分，{weakest["level_label"]}），'
            f'该维度题目得分率偏低。'
        )
    counts: dict[str, int] = {}
    for task in tasks:
        for issue in task['issues']:
            counts[issue['message']] = counts.get(issue['message'], 0) + 1
    if counts:
        message, count = max(counts.items(), key=lambda pair: (pair[1], pair[0]))
        summary.append(f'最高频的静态缺陷是「{message}」，共出现 {count} 次。')
    elif tasks:
        summary.append('评测报告未记录静态缺陷，代码结构稳定，继续保持。')
    return summary[:3]


def _thinking_cards(
    rows: list[dict[str, Any]], facts: dict[str, Any]
) -> list[dict[str, Any]]:
    cards = []
    for row in rows:
        hint = _CODE_HINTS.get(row['key'], '')
        code_hint = hint.format(**facts) if hint and facts.get('files') else ''
        evidence = list(row['evidence'])
        if code_hint:
            evidence.append(f'代码结构：{code_hint}')
        cards.append(
            {
                **row,
                'percent': row['score'] if row['covered'] else 0,
                'evidence': evidence,
                'code_hint': code_hint,
            }
        )
    return cards


def _radar(bloom: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [
        {
            'key': row['key'],
            'label': row['label'],
            'score': row['score'] if row['score'] is not None else 0,
            'weight': round(row['coverage'] * 100),
        }
        for row in bloom
    ]
    geometry = quality_service.radar_geometry(scores)
    for axis, row in zip(geometry['axes'], bloom):
        axis['coverage'] = row['coverage']
        axis['coverage_text'] = row['coverage_text']
        axis['covered'] = row['covered']
    return geometry


def build_payload(
    student,
    tasks: list[dict[str, Any]],
    facts: dict[str, Any],
    diagnosis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """组装画像 payload：分数、雷达几何、能力卡、诊断与元信息。"""
    bloom = _score_dimensions(tasks, 'bloom', capability_rules.BLOOM_DIMENSIONS)
    thinking = _score_dimensions(
        tasks, 'thinking', capability_rules.THINKING_DIMENSIONS
    )
    cards = _thinking_cards(thinking, facts)
    works = {task['work_id'] for task in tasks}
    payload: dict[str, Any] = {
        'version': capability_rules.VERSION,
        'bloom': bloom,
        'thinking': cards,
        'radar': _radar(bloom),
        'summary': _rule_summary(bloom, thinking, tasks),
        'observations': [],
        'suggestion': '',
        'code_facts': facts,
        'meta': {
            'works': len(works),
            'tasks': len(tasks),
            'graded_tasks': sum(1 for task in tasks if task['rate'] is not None),
            'diagnosis': 'rule',
            'prompt_version': PROMPT_VERSION,
            'generated_at': timezone.now().isoformat(timespec='seconds'),
        },
    }
    if diagnosis:
        payload['summary'] = diagnosis['summary']
        payload['observations'] = diagnosis['observations']
        payload['suggestion'] = diagnosis['suggestion']
        payload['meta']['diagnosis'] = 'llm'
    return payload


def _model_stamp(config) -> str:
    """端点与模型名的指纹；改配置后旧诊断自动重算，但不记录 API Key。"""
    if config is None:
        return ''
    return f'{_clean(config.base_url)}|{_clean(config.model)}'


def _signature(tasks: list[dict[str, Any]], model_stamp: str) -> str:
    """画像指纹：报告、源码、映射表与提示词任一处变化都要重算。"""
    parts = [capability_rules.VERSION, PROMPT_VERSION, _clean(model_stamp)]
    for task in sorted(tasks, key=lambda row: (row['work_id'], row['task_id'])):
        parts.append(
            f"{task['work_id']}:{task['task_id']}:{task['code_hash']}:"
            f"{task['report_stamp']}:{task['rate']}"
        )
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


def _save_profile(
    student,
    payload: dict[str, Any],
    source: str,
    model: str,
    signature: str,
) -> StudentCapabilityProfile:
    profile, _ = StudentCapabilityProfile.objects.update_or_create(
        student=student,
        defaults={
            'signature': signature,
            'payload': payload,
            'source': source,
            'model': model,
        },
    )
    return profile


def _extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    raw = fenced.group(1) if fenced else ''
    if not raw:
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            raise DiagnosisError('大模型输出中没有找到 JSON 对象。')
        raw = text[start : end + 1]
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise DiagnosisError(f'大模型输出的 JSON 无法解析：{exc}') from exc
    if not isinstance(data, dict):
        raise DiagnosisError('大模型输出的 JSON 不是对象。')
    return data


def _dimension_label(dimension: str) -> str:
    group, _, key = dimension.partition('.')
    if group == 'bloom':
        return f'布鲁姆·{capability_rules.BLOOM_LABELS.get(key, key)}'
    if group == 'thinking':
        return f'计算思维·{capability_rules.THINKING_LABELS.get(key, key)}'
    return ''


def normalize_diagnosis(text: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """校验大模型诊断：维度、题号、行号必须真实存在，否则丢弃该条。

    全部不可用时抛 DiagnosisError，由调用方保留规则诊断，避免把模型猜测
    当成学生画像。
    """
    data = _extract_json(text)
    task_lines = {
        task['task_id']: len((task.get('code') or '').splitlines()) for task in tasks
    }
    summary = [
        _clean(item)[:120]
        for item in data.get('summary') or []
        if _clean(item)
    ][:3]
    observations: list[dict[str, Any]] = []
    for item in data.get('observations') or []:
        if not isinstance(item, dict):
            continue
        dimension = _clean(item.get('dimension'))
        if not _dimension_label(dimension):
            continue
        task_id = _clean(item.get('task_id'))
        if task_id not in task_lines:
            continue
        try:
            line = int(item.get('line') or 0)
        except (TypeError, ValueError):
            continue
        if line < 0 or line > task_lines[task_id]:
            continue
        comment = _clean(item.get('comment'))
        if not comment:
            continue
        observations.append(
            {
                'dimension': dimension,
                'dimension_label': _dimension_label(dimension),
                'task_id': task_id,
                'line': line,
                'quote': _clean(item.get('quote'))[:120],
                'comment': comment[:160],
                'advice': _clean(item.get('advice'))[:160],
            }
        )
        if len(observations) >= MAX_OBSERVATIONS:
            break
    suggestion = _clean(data.get('suggestion'))[:200]
    if not summary and not observations:
        raise DiagnosisError('大模型没有给出可用的诊断结论。')
    return {
        'summary': summary,
        'observations': observations,
        'suggestion': suggestion,
    }


DIAGNOSIS_SCHEMA = """{
  "summary": ["不超过 50 字，指出最需要改进的 1~3 点"],
  "observations": [
    {"dimension": "bloom.analyze",
     "task_id": "func0101",
     "line": 12,
     "quote": "代码原文片段（可留空）",
     "comment": "这行暴露的问题",
     "advice": "可执行的修改建议"}
  ],
  "suggestion": "一句话总建议"
}"""


def _compact_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """压缩送给大模型的题目与代码，控制单次请求体积。"""
    budget = MAX_TOTAL_CODE_LINES
    compact: list[dict[str, Any]] = []
    for task in tasks:
        code = task.get('code') or ''
        lines = code.splitlines()
        take = min(len(lines), MAX_CODE_LINES, max(budget, 0))
        excerpt = '\n'.join(lines[:take])
        if take and take < len(lines):
            excerpt += f'\n# …（其余 {len(lines) - take} 行省略）'
        budget -= take
        compact.append(
            {
                'task_id': task['task_id'],
                'title': task['title'],
                'score_rate': None
                if task['rate'] is None
                else round(task['rate'] * 100, 1),
                'knowledge': task['labels'],
                'bloom': list(task['bloom']),
                'thinking': list(task['thinking']),
                'issues': task['issues'][:5],
                'code': excerpt,
            }
        )
    return compact


def build_messages(
    student_name: str,
    tasks: list[dict[str, Any]],
    payload: dict[str, Any],
    facts: dict[str, Any],
) -> list[dict[str, str]]:
    system = (
        '你是高校 Python 课程的学习分析师。请依据学生所有任务的评测报告错误点与提交代码，'
        '给出针对性的学习诊断。只输出 JSON，不要输出解释性文字；'
        '不要编造未出现的题号、行号或代码。'
    )
    rule_scores = {
        'bloom': [
            {'维度': row['label'], '得分': row['score'], '覆盖': row['coverage_text']}
            for row in payload['bloom']
        ],
        'thinking': [
            {'维度': row['label'], '得分': row['score'], '覆盖': row['coverage_text']}
            for row in payload['thinking']
        ],
    }
    user = f"""学生：{student_name}

规则算分（分数已由评测报告逐题得分率聚合，请勿修改分数，只做归因）：
{json.dumps(rule_scores, ensure_ascii=False, indent=2)}

代码结构统计：
{json.dumps(facts, ensure_ascii=False)}

各任务证据（含错误点与代码片段）：
{json.dumps(_compact_tasks(tasks), ensure_ascii=False, indent=2)}

任务要求：
1. summary 用 1~3 条中文短句指出最需要改进的地方，必须与上面的得分与错误点一致；
2. observations 最多 6 条，每条必须引用真实存在的 task_id 与代码行号（0 表示文件级问题），
   quote 只摘录代码原文，comment 说明问题，advice 给可执行的改法；
3. dimension 只能取 bloom.remember / bloom.understand / bloom.apply / bloom.analyze /
   bloom.evaluate / bloom.create / thinking.abstraction / thinking.decomposition /
   thinking.algorithm / thinking.pattern；
4. 不要复述分数，不要给出新的分数。

输出 JSON，结构如下：
{DIAGNOSIS_SCHEMA}
"""
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def diagnose(
    student,
    tasks: list[dict[str, Any]],
    payload: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    """调用学生自己的大模型生成诊断；失败抛 LLMError / DiagnosisError。"""
    name = student.get_full_name() or student.username
    text = chat(
        build_messages(name, tasks, payload, facts), user=student, temperature=0.2
    )
    return normalize_diagnosis(text, tasks)


def _refresh(student) -> StudentCapabilityProfile | None:
    tasks = collect_tasks(student)
    if not tasks:
        return None
    facts = code_facts(tasks)
    payload = build_payload(student, tasks, facts)
    source, model = 'rule', ''
    config = llm_client.get_config(student)
    if llm_client.configured(student):
        try:
            diagnosis = diagnose(student, tasks, payload, facts)
        except (LLMError, LLMNotConfigured, DiagnosisError) as exc:
            logger.info('综合能力大模型诊断失败，保留规则诊断 student=%s：%s', student.pk, exc)
        else:
            payload = build_payload(student, tasks, facts, diagnosis=diagnosis)
            source, model = 'llm', config.model if config else ''
    return _save_profile(
        student, payload, source, model, _signature(tasks, _model_stamp(config))
    )


def _refresh_job(student_id: int) -> None:
    try:
        student = User.objects.filter(pk=student_id).first()
        if student is not None:
            _refresh(student)
    except Exception:
        logger.warning('后台综合能力分析失败 student=%s', student_id, exc_info=True)
    finally:
        close_old_connections()
        with _SCHEDULE_LOCK:
            _PENDING_STUDENTS.discard(student_id)


def schedule_refresh(student_id: int) -> bool:
    """事务提交后在后台重算画像，避免阻塞弱项分析页打开。"""
    with _SCHEDULE_LOCK:
        if student_id in _PENDING_STUDENTS:
            return False
        _PENDING_STUDENTS.add(student_id)
    transaction.on_commit(
        lambda: threading.Thread(
            target=_refresh_job, args=(student_id,), daemon=True
        ).start()
    )
    return True


def ensure_profile(student) -> tuple[StudentCapabilityProfile | None, bool]:
    """取该学生的画像，必要时计算或安排重算。

    返回 ``(画像, 是否正在后台刷新)``：
    - 没有画像时先同步生成规则画像，保证页面立刻有分数；
    - 画像过期且已配置大模型时后台重算，期间继续展示旧画像。
    """
    tasks = collect_tasks(student)
    if not tasks:
        return None, False
    config = llm_client.get_config(student)
    signature = _signature(tasks, _model_stamp(config))
    profile = StudentCapabilityProfile.objects.filter(student=student).first()
    if profile is not None and profile.signature == signature:
        return profile, False
    if profile is None:
        # 首次进入先同步给出规则分，页面立刻可用；已配置大模型时再排后台诊断。
        payload = build_payload(student, tasks, code_facts(tasks))
        saved = _save_profile(student, payload, 'rule', '', signature)
        if llm_client.configured(student):
            schedule_refresh(student.pk)
            return saved, True
        return saved, False
    if not llm_client.configured(student):
        # 未配置大模型时后台重算没有额外信息，直接同步更新规则画像。
        payload = build_payload(student, tasks, code_facts(tasks))
        return _save_profile(student, payload, 'rule', '', signature), False
    schedule_refresh(student.pk)
    return profile, True


def view_model(student) -> dict[str, Any]:
    """弱项分析页顶部的渲染上下文；无数据时给出空态说明。"""
    profile, refreshing = ensure_profile(student)
    llm_ready = llm_client.configured(student)
    if profile is None:
        return {
            'ready': False,
            'refreshing': False,
            'llm_ready': llm_ready,
            'empty_reason': '完成一次机器批阅作业后，这里会自动生成你的综合能力分析。',
        }
    payload = profile.payload or {}
    if payload.get('version') != capability_rules.VERSION:
        return {
            'ready': False,
            'refreshing': refreshing,
            'llm_ready': llm_ready,
            'empty_reason': '能力画像正在按最新口径重新生成，请稍后刷新。',
        }
    meta = payload.get('meta') or {}
    source_note = (
        f'大模型诊断（{profile.model}）'
        if profile.source == 'llm'
        else '规则诊断（未使用大模型）'
    )
    return {
        'ready': True,
        'refreshing': refreshing,
        'llm_ready': llm_ready,
        'source': profile.source,
        'source_note': source_note,
        'updated_at': timezone.localtime(profile.generated_at)
        if profile.generated_at
        else None,
        'bloom': payload.get('bloom') or [],
        'thinking': payload.get('thinking') or [],
        'radar': payload.get('radar') or {},
        'summary': payload.get('summary') or [],
        'observations': payload.get('observations') or [],
        'suggestion': payload.get('suggestion') or '',
        'code_facts': payload.get('code_facts') or {},
        'meta': meta,
        'works': meta.get('works', 0),
        'tasks': meta.get('tasks', 0),
        'graded_tasks': meta.get('graded_tasks', 0),
    }
