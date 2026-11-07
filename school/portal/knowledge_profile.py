"""知识点画像：把机器批阅结果按知识点聚合，算出学生的强弱分布。

数据链路：
    CourseworkSubmission(学生, status='done')
      → CourseworkQuestionResult(function_name, score, points)
      → CourseworkItem(function_name, points)
      → CourseworkRubric.knowledge_points(tasks=[function_name])

只做纯数据统计，不调用大模型；弱项判定用固定阈值，便于教师端复用。
"""

from __future__ import annotations

import re

from django.conf import settings

from school.course_models import Coursework
from school.models import User

from .access import classes_for

DEFAULT_WEAK_THRESHOLD = 0.6
DEFAULT_MIN_ATTEMPTS = 1

# 把"切片与 1 起始计数换算"这类弱项名拆成关键词，供题库反查复用。
_TOKEN_SPLIT_RE = re.compile(r'[\s/、，,（）()\[\]【】·。.:：;；]+')
_TOKEN_STRIP = '与和的或及·、'
_TOKEN_STOPWORDS = {'相关', '及其', '应用', '使用', '练习'}


def weak_keywords(name: str) -> list[str]:
    """把弱项知识点名称拆成关键词列表，如 'for 遍历' → ['for', '遍历']。"""
    tokens: list[str] = []
    for raw in _TOKEN_SPLIT_RE.split(name):
        token = raw.strip(_TOKEN_STRIP).strip().lower()
        if not token or token in _TOKEN_STOPWORDS or len(token) == 1:
            continue
        tokens.append(token)
    return tokens


def weak_threshold() -> float:
    value = getattr(settings, 'PRACTICE_WEAK_THRESHOLD', DEFAULT_WEAK_THRESHOLD)
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        threshold = DEFAULT_WEAK_THRESHOLD
    return min(max(threshold, 0.0), 1.0)


def student_knowledge_profile(student: User) -> dict[str, dict]:
    """按知识点聚合该学生在已批阅作业上的表现。

    返回 {知识点名: {'earned': 得分合计, 'total': 满分合计, 'attempts': 覆盖题数}}。
    每道函数题取历次提交的最高分，避免重试次数拉低画像。
    """
    works = Coursework.objects.filter(
        classroom__in=classes_for(student),
        deleted_at__isnull=True,
        status='open',
    ).select_related('rubric').prefetch_related('items')
    profile: dict[str, dict] = {}
    for work in works:
        rubric = getattr(work, 'rubric', None)
        if rubric is None or not rubric.knowledge_points:
            continue
        best: dict[str, float] = {}
        points_by_task: dict[str, int] = {}
        for item in work.items.all():
            points_by_task[item.function_name] = item.points
        for entry in work.entries.filter(student=student, status='done'):
            for question in entry.questions.all():
                if question.score is None:
                    continue
                earned = float(question.score)
                if earned > best.get(question.function_name, -1):
                    best[question.function_name] = earned
        if not best:
            continue
        for point in rubric.knowledge_points:
            name = str(point.get('name', '')).strip()
            if not name:
                continue
            aggregate = profile.setdefault(name, {'earned': 0.0, 'total': 0, 'attempts': 0})
            for task in point.get('tasks') or []:
                total = points_by_task.get(task)
                if total is None:
                    continue
                aggregate['total'] += total
                if task in best:
                    aggregate['earned'] += best[task]
                    aggregate['attempts'] += 1
    return profile


def weak_points(profile: dict[str, dict]) -> list[dict]:
    """返回弱项列表：得分率低于阈值且真实尝试过的知识点，按得分率升序。"""
    threshold = weak_threshold()
    weak = []
    for name, aggregate in profile.items():
        if aggregate['attempts'] < DEFAULT_MIN_ATTEMPTS or aggregate['total'] <= 0:
            continue
        rate = aggregate['earned'] / aggregate['total']
        if rate >= threshold:
            continue
        weak.append(
            {
                'name': name,
                'rate': round(rate, 4),
                'percent': round(rate * 100, 1),
                'earned': round(aggregate['earned'], 1),
                'total': aggregate['total'],
                'attempts': aggregate['attempts'],
            }
        )
    weak.sort(key=lambda item: (item['rate'], item['name']))
    return weak


def mastered_points(profile: dict[str, dict]) -> list[dict]:
    """返回得分率不低于阈值的知识点，用于出题时控制难度与避免重复。"""
    threshold = weak_threshold()
    mastered = []
    for name, aggregate in profile.items():
        if aggregate['total'] <= 0:
            continue
        rate = aggregate['earned'] / aggregate['total']
        if rate < threshold:
            continue
        mastered.append({'name': name, 'percent': round(rate * 100, 1)})
    mastered.sort(key=lambda item: (-item['percent'], item['name']))
    return mastered


def class_knowledge_summary(classroom) -> list[dict]:
    """教师端：全班每个知识点的平均得分率与弱项人数，按平均得分率升序。"""
    students = list(
        classroom.members.filter(active=True).values_list('student_id', flat=True)
    )
    if not students:
        return []
    works = Coursework.objects.filter(
        classroom=classroom, deleted_at__isnull=True, status='open'
    ).select_related('rubric').prefetch_related('items')
    totals: dict[str, dict] = {}
    for work in works:
        rubric = getattr(work, 'rubric', None)
        if rubric is None or not rubric.knowledge_points:
            continue
        for student_id in students:
            profile = _profile_for_work(work, student_id)
            for name, aggregate in profile.items():
                cell = totals.setdefault(name, {'earned': 0.0, 'total': 0, 'weak': 0})
                cell['earned'] += aggregate['earned']
                cell['total'] += aggregate['total']
                if (
                    aggregate['attempts'] >= DEFAULT_MIN_ATTEMPTS
                    and aggregate['total'] > 0
                    and aggregate['earned'] / aggregate['total'] < weak_threshold()
                ):
                    cell['weak'] += 1
    summary = []
    for name, cell in totals.items():
        if cell['total'] <= 0:
            continue
        summary.append(
            {
                'name': name,
                'avg_percent': round(cell['earned'] / cell['total'] * 100, 1),
                'weak_students': cell['weak'],
                'student_count': len(students),
            }
        )
    summary.sort(key=lambda item: (item['avg_percent'], item['name']))
    return summary


def _profile_for_work(work, student_id) -> dict[str, dict]:
    """单份作业的单个学生画像，供 class_knowledge_summary 复用。"""
    rubric = getattr(work, 'rubric', None)
    if rubric is None or not rubric.knowledge_points:
        return {}
    best: dict[str, float] = {}
    points_by_task = {item.function_name: item.points for item in work.items.all()}
    for entry in work.entries.filter(student_id=student_id, status='done'):
        for question in entry.questions.all():
            if question.score is None:
                continue
            earned = float(question.score)
            if earned > best.get(question.function_name, -1):
                best[question.function_name] = earned
    if not best:
        return {}
    profile: dict[str, dict] = {}
    for point in rubric.knowledge_points:
        name = str(point.get('name', '')).strip()
        if not name:
            continue
        aggregate = profile.setdefault(name, {'earned': 0.0, 'total': 0, 'attempts': 0})
        for task in point.get('tasks') or []:
            total = points_by_task.get(task)
            if total is None:
                continue
            aggregate['total'] += total
            if task in best:
                aggregate['earned'] += best[task]
                aggregate['attempts'] += 1
    return profile
