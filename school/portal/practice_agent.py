"""训练题智能体：根据学生知识点强弱画像，调用大模型生成个性化训练题。

设计边界（与题目分析智能体 rubric_agent 保持一致）：
- 只在配置了 OpenAI 兼容端点时调用模型；未配置时抛 LLMNotConfigured，
  演示或离线运行必须显式 `offline=True`，结果标注来源，不把兜底当成模型结论；
- 生成的训练题必须带 stdin/stdout 测试用例，落库后经 school.judge.run_case
  在受限 Docker 中批阅，按用例通过比例计分，不计入正式作业成绩；
- 规则兜底根据现有题库（数据库题库表 + 分层题库文档 Python题库.md）
  按知识点关键词匹配现成题，不凭空编题。
"""

from __future__ import annotations

import json
import re
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from school.course_models import PracticeAttempt, PracticeCase, PracticePlan, PracticeProblem
from school.judge import InfrastructureError, run_case
from school.models import ProblemVersion, User
from school.storage import read_private, save_private

from . import knowledge_profile, question_bank
from .rubric_agent import LLMNotConfigured, chat, llm_configured, llm_status

PROMPT_VERSION = 'v1'

MAX_QUESTIONS_PER_POINT = 2
MAX_CASES_PER_QUESTION = 5

PRACTICE_SCHEMA_HINT = """{
  "questions": [
    {"knowledge_point": "列表切片",
     "title": "区间裁剪",
     "statement": "题面正文，必须写清输入格式、输出格式与样例说明",
     "difficulty": "基础",
     "template_code": "def main():\\n    ...",
     "reference_code": "完整可运行的参考答案",
     "explanation": "针对该知识点的解题思路（学生批阅后不可见）",
     "test_cases": [
       {"input": "1 5\\n1 2 3 4 5", "output": "2 3 4", "is_sample": true},
       {"input": "...", "output": "...", "is_sample": false}
     ]}
  ]
}"""


class PracticeParseError(ValueError):
    """模型返回内容无法解析成合法训练题。"""


class NoWeakPoint(RuntimeError):
    """学生当前没有可训练的弱项知识点。"""


def practice_context(student: User) -> dict[str, Any]:
    profile = knowledge_profile.student_knowledge_profile(student)
    weak = knowledge_profile.weak_points(profile)
    mastered = knowledge_profile.mastered_points(profile)
    return {'profile': profile, 'weak': weak, 'mastered': mastered}


def existing_titles(student: User) -> list[str]:
    return list(
        PracticeProblem.objects.filter(plan__student=student)
        .values_list('title', flat=True)
        .order_by('pk')[:200]
    )


def build_messages(weak: list[dict], mastered: list[dict], titles: list[str]) -> list[dict[str, str]]:
    system = (
        '你是高校 Python 课程的助教，负责根据学生的知识点强弱画像生成个性化训练题。'
        '只输出 JSON，不要输出解释性文字。'
    )
    user = f"""学生知识点画像（JSON）：
弱项（得分率低于阈值，需要针对性训练）：
{json.dumps(weak, ensure_ascii=False, indent=2)}

已掌握（用于控制难度并做综合变式，不要再出这些知识点的单纯复述题）：
{json.dumps(mastered, ensure_ascii=False, indent=2)}

该学生最近生成过的训练题（避免重复出题）：
{json.dumps(titles, ensure_ascii=False)}

任务：为每个弱项知识点生成 {MAX_QUESTIONS_PER_POINT} 道训练题，要求：
1. 第一道直接针对该知识点的核心用法（难度“基础”），第二道结合学生已掌握的知识点做综合变式（难度“进阶”）；
2. 题目均为标准输入 stdin / 标准输出 stdout 的文本判定题，题面写清输入格式、输出格式和约定；
3. 每题给 3-5 组测试用例，至少 1 组 is_sample=true 的样例（会展示给学生），其余隐藏；
4. test_cases 中的 input/output 必须是普通文本（\\n 表示换行），expected 输出要与题意严格一致；
5. template_code 给出完整可运行的初始框架（含读取输入的代码）；
6. reference_code 必须是自己可以独立运行并全部通过上述用例的完整程序。

输出 JSON，结构如下：
{PRACTICE_SCHEMA_HINT}
"""
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def _extract_json(text: str) -> str:
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find('{'), text.rfind('}')
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise PracticeParseError('模型输出中没有找到 JSON 对象。')


def _normalize_cases(raw: Any) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return cases
    for item in raw:
        if not isinstance(item, dict):
            continue
        stdin = str(item.get('input', '')).strip()
        expected = str(item.get('output', '')).strip()
        if not stdin or not expected:
            continue
        cases.append(
            {
                'input': stdin,
                'output': expected,
                'is_sample': bool(item.get('is_sample')),
            }
        )
        if len(cases) >= MAX_CASES_PER_QUESTION:
            break
    return cases


def parse_practice(text: str, weak_names: list[str]) -> list[dict[str, Any]]:
    """解析模型输出，丢弃结构不合法或偏离弱项的题目，每个弱项最多保留 2 题。"""
    data = json.loads(_extract_json(text))
    if not isinstance(data, dict) or not isinstance(data.get('questions'), list):
        raise PracticeParseError('模型输出的 JSON 缺少 questions 数组。')
    allowed = set(weak_names)
    per_point: dict[str, int] = {}
    questions: list[dict[str, Any]] = []
    for item in data['questions']:
        if not isinstance(item, dict):
            continue
        point = str(item.get('knowledge_point', '')).strip()
        title = str(item.get('title', '')).strip()
        statement = str(item.get('statement', '')).strip()
        cases = _normalize_cases(item.get('test_cases'))
        if point not in allowed or not title or not statement or not cases:
            continue
        if per_point.get(point, 0) >= MAX_QUESTIONS_PER_POINT:
            continue
        per_point[point] = per_point.get(point, 0) + 1
        difficulty = str(item.get('difficulty', '')).strip()
        if difficulty not in ('基础', '进阶'):
            difficulty = '进阶'
        questions.append(
            {
                'knowledge_point': point,
                'title': title,
                'statement': statement,
                'template_code': str(item.get('template_code', '')).strip(),
                'reference_code': str(item.get('reference_code', '')).strip(),
                'explanation': str(item.get('explanation', '')).strip(),
                'difficulty': difficulty,
                'cases': cases,
            }
        )
    if not questions:
        raise PracticeParseError('模型没有给出任何可用的训练题。')
    return questions


from .knowledge_profile import weak_keywords


def _match_versions(name: str) -> list[tuple[int, ProblemVersion]]:
    """按关键词给题库题目打分：knowledge 命中权重 2，title 命中权重 1。

    返回按得分降序的 (得分, 题目版本)，无命中时为空列表。
    """
    keywords = weak_keywords(name)
    if not keywords:
        return []
    scored: list[tuple[int, ProblemVersion]] = []
    for version in ProblemVersion.objects.all().order_by('problem__code', 'number'):
        knowledge = (version.knowledge or '').lower()
        title = (version.title or '').lower()
        score = 2 * sum(1 for keyword in keywords if keyword in knowledge)
        score += sum(1 for keyword in keywords if keyword in title)
        if score > 0:
            scored.append((score, version))
    scored.sort(key=lambda pair: (-pair[0], pair[1].problem_id, pair[1].number))
    return scored


def bank_matches_exist(weak: list[dict]) -> bool:
    """题库（数据库题库表 + 分层题库文档）中是否存在可匹配任一弱项的题目。"""
    for item in weak:
        if _match_versions(item['name']) or question_bank.find_questions(
            item['name'], limit=1
        ):
            return True
    return False


def rule_based(weak: list[dict]) -> list[dict[str, Any]]:
    """离线兜底：根据现有题库按知识点关键词匹配现成题，不凭空编题。

    两个来源按顺序补足，每个弱项最多 MAX_QUESTIONS_PER_POINT 题：
    1. 数据库题库表 ProblemVersion（教师录入的正式题库，命中 knowledge 标签优先）；
    2. 分层训练题库文档 Python题库.md（团队维护、答案与用例实测通过），
       按题目考点标签与弱项关键词反查。
    完全匹配不到时不出题，弱项本身已记录在画像快照中，避免造假数据。
    """
    questions: list[dict[str, Any]] = []
    used_bank_codes: set[str] = set()
    for item in weak:
        taken: list[dict[str, Any]] = []
        seen_problems: set[int] = set()
        for _score, version in _match_versions(item['name']):
            if version.problem_id in seen_problems:
                continue
            seen_problems.add(version.problem_id)
            if not version.cases.exists():
                continue
            if len(taken) >= MAX_QUESTIONS_PER_POINT:
                break
            taken.append(
                {
                    'knowledge_point': item['name'],
                    'title': version.title,
                    'statement': version.statement,
                    'template_code': version.template_code,
                    'reference_code': '',
                    'explanation': version.explanation,
                    'difficulty': '基础' if version.difficulty == '基础' else '进阶',
                    'cases': [
                        {
                            'input': _read_case(case.input_path),
                            'output': _read_case(case.output_path),
                            'is_sample': case.is_sample,
                        }
                        for case in version.cases.all()[:MAX_CASES_PER_QUESTION]
                    ],
                }
            )
        remaining = MAX_QUESTIONS_PER_POINT - len(taken)
        if remaining > 0:
            for bank_question in question_bank.find_questions(
                item['name'], limit=remaining, exclude=used_bank_codes
            ):
                used_bank_codes.add(bank_question['code'])
                taken.append(
                    {
                        'knowledge_point': item['name'],
                        'title': bank_question['title'],
                        'statement': bank_question['statement'],
                        'template_code': '',
                        'reference_code': bank_question['reference_code'],
                        'explanation': bank_question['explanation'],
                        'difficulty': bank_question['difficulty'],
                        'cases': bank_question['cases'],
                    }
                )
        questions.extend(taken)
    return questions


def _read_case(key: str) -> str:
    try:
        return read_private(key)
    except Exception:
        return ''


@transaction.atomic
def _store_plan(student: User, weak: list[dict], profile: dict, questions: list[dict],
                source: str, model: str) -> PracticePlan:
    plan = PracticePlan.objects.create(
        student=student,
        classroom=None,
        profile_snapshot={'weak': weak, 'mastered': knowledge_profile.mastered_points(profile)},
        status='ready',
        source=source,
        model=model,
    )
    order = 0
    for question in questions:
        order += 1
        problem = PracticeProblem.objects.create(
            plan=plan,
            knowledge_point=question['knowledge_point'],
            title=question['title'][:120],
            statement=question['statement'],
            template_code=question.get('template_code', ''),
            reference_code=question.get('reference_code', ''),
            explanation=question.get('explanation', ''),
            difficulty=question.get('difficulty', '基础'),
            order=order,
            time_ms=int(getattr(settings, 'COURSEWORK_CASE_TIME_MS', 2000)),
        )
        for index, case in enumerate(question['cases'], start=1):
            PracticeCase.objects.create(
                problem=problem,
                order=index,
                input_path=save_private(case['input']),
                output_path=save_private(case['output']),
                is_sample=bool(case.get('is_sample')),
            )
    return plan


def generate_practice_plan(student: User, offline: bool = False) -> PracticePlan | None:
    """计算画像并生成训练计划；没有弱项时返回 None。"""
    context = practice_context(student)
    weak = context['weak']
    if not weak:
        return None

    if offline or not llm_configured():
        if not offline:
            raise LLMNotConfigured(
                '未配置大模型端点。请设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，'
                '或显式使用规则兜底。'
            )
        questions = rule_based(weak)
        source, model = 'rule', ''
    else:
        text = chat(
            build_messages(weak, context['mastered'], existing_titles(student)),
            temperature=0.3,
        )
        questions = parse_practice(text, [item['name'] for item in weak])
        source, model = 'llm', settings.LLM_MODEL

    if not questions:
        if source == 'rule':
            raise PracticeParseError('题库中没有匹配弱项知识点的现成题，规则兜底无法出题。')
        raise PracticeParseError('模型返回的题目均不可用。')
    return _store_plan(student, weak, context['profile'], questions, source, model)


def grade_attempt(attempt: PracticeAttempt) -> PracticeAttempt:
    """在受限 Docker 中批阅一次训练题提交，按用例通过比例计分。

    与正式批阅一致：只经 school.judge.run_case，绝不在宿主机直接执行学生代码。
    """
    problem = attempt.problem
    code = read_private(attempt.code_path)
    cases = list(problem.cases.order_by('order'))
    passed = 0
    try:
        for case in cases:
            outcome = run_case(
                code,
                read_private(case.input_path),
                read_private(case.output_path),
                problem,
            )
            if outcome.verdict == 'AC':
                passed += 1
    except InfrastructureError as exc:
        attempt.verdict = 'ERROR'
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=['verdict', 'finished_at'])
        raise
    total = len(cases)
    score = round(passed / total * 100, 1) if total else 0.0
    attempt.passed_cases = passed
    attempt.total_cases = total
    attempt.score = score
    attempt.verdict = 'AC' if total and passed == total else 'WA'
    attempt.finished_at = timezone.now()
    attempt.save()
    return attempt


def latest_plan(student: User) -> PracticePlan | None:
    return PracticePlan.objects.filter(student=student, status='ready').first()


def status_text() -> str:
    return llm_status()
