"""知识点画像：依据评测报告逐题明细的知识点缺陷，按 Tag 库聚合出强弱分布。

数据链路（弱项练习的依据是每份作业的评测报告，教师上传不同任务 →
评分标准不同 → 逐题明细考察的知识点与机器判定结果也不同）：
    CourseworkSubmission(学生, status='done', quality_report 存在)
      → QualityReport.payload['tasks'] 逐题明细
      → 每题的 points 列表：机器可判定（judged）知识点的 ✓/✗
      → ✗ 的项即该题暴露的缺陷，label 已是《Python教学Tag库》标准名
      → 按 Tag 聚合各任务的达成 / 缺陷比例

只做纯数据统计，不调用大模型；弱项判定用固定阈值，便于教师端复用。
"""

from __future__ import annotations

import math
import re

from django.conf import settings

from school.course_models import Coursework, QualityReport
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
    # NaN 与 inf 不参与大小比较，必须显式拒绝，否则阈值静默失效。
    if not math.isfinite(threshold):
        threshold = DEFAULT_WEAK_THRESHOLD
    return min(max(threshold, 0.0), 1.0)


def _first_reported_entry(work, student_id):
    """该学生在本作业第一次带评测报告的提交（着重首次作答暴露的问题）。"""
    return (
        work.entries.filter(
            student_id=student_id, status='done', quality_report__isnull=False
        )
        .order_by('sequence', 'pk')
        .first()
    )


def _report_tag_points(report: QualityReport) -> dict[str, tuple[int, int]]:
    """从评测报告逐题明细取各 Tag 的达成情况：{Tag 名: (✓ 数, 判定数)}。

    逐题明细的 points 列表里，judged=True 的知识点是机器判定过的考察点：
    ✓ 代表学生代码正确用到了该 Tag，✗ 代表该题暴露的缺陷（未达成）。
    label 在生成报告时已归一为《Python教学Tag库》标准名；无法机检（judged=False）
    的知识点既不是缺陷也不是达成，不计入画像。
    """
    payload = report.payload or {}
    tags: dict[str, tuple[int, int]] = {}
    for task in payload.get('tasks') or []:
        for point in task.get('points') or []:
            if not point.get('judged'):
                continue
            tag = str(point.get('label') or '').strip()
            if not tag:
                continue
            ok_count, judged_count = tags.get(tag, (0, 0))
            tags[tag] = (ok_count + (1 if point.get('ok') else 0), judged_count + 1)
    return tags


def _aggregate_tag_points(tag_points: dict[str, tuple[int, int]]) -> dict[str, dict]:
    """把 {Tag: (✓ 数, 判定数)} 聚合成画像结构，弱项/掌握判定都基于它。"""
    profile: dict[str, dict] = {}
    for tag, (ok_count, judged_count) in tag_points.items():
        aggregate = profile.setdefault(tag, {'earned': 0.0, 'total': 0, 'attempts': 0})
        aggregate['earned'] += ok_count * 100
        aggregate['total'] += judged_count * 100
        aggregate['attempts'] += 1
    return profile


def task_profiles(student: User) -> list[dict]:
    """每个任务一份独立画像（学生端弱项练习按任务区分的依据）。

    返回 [{'work': 作业, 'work_title': 标题, 'profile': {Tag: 聚合}}]。
    学生在不同任务里首次提交犯的错不同，各任务报告逐题明细的缺陷
    对应的 Tag 也不同，因此每个任务的弱项练习互不一样。
    """
    works = Coursework.objects.filter(
        classroom__in=classes_for(student),
        deleted_at__isnull=True,
        status='open',
    ).order_by('-pk')
    sections: list[dict] = []
    for work in works:
        entry = _first_reported_entry(work, student.pk)
        if entry is None:
            continue
        sections.append(
            {
                'work': work,
                'work_title': work.title,
                'profile': _aggregate_tag_points(
                    _report_tag_points(entry.quality_report)
                ),
            }
        )
    return sections


def task_profile(student: User, work) -> dict[str, dict]:
    """单份任务的画像；该任务还没有带评测报告的提交时返回空。"""
    entry = _first_reported_entry(work, student.pk)
    if entry is None:
        return {}
    return _aggregate_tag_points(_report_tag_points(entry.quality_report))


def student_knowledge_profile(student: User) -> dict[str, dict]:
    """按 Tag 合并所有任务的画像（跨任务汇总视图）。

    返回 {Tag 名: {'earned': 达成判定数×100, 'total': 判定数×100, 'attempts': 出现任务数}}。
    每份作业取第一次有评测报告的提交——画像着重反映学生首次作答就暴露出的问题；
    教师上传的不同任务评分标准不同，逐题明细考察的知识点与缺陷也不同，逐任务计入。
    """
    profile: dict[str, dict] = {}
    for section in task_profiles(student):
        for tag, aggregate in section['profile'].items():
            merged = profile.setdefault(
                tag, {'earned': 0.0, 'total': 0, 'attempts': 0}
            )
            merged['earned'] += aggregate['earned']
            merged['total'] += aggregate['total']
            merged['attempts'] += aggregate['attempts']
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
    """单份作业的单个学生画像（来自该作业评测报告的逐题明细），供 class_knowledge_summary 复用。"""
    entry = _first_reported_entry(work, student_id)
    if entry is None:
        return {}
    profile: dict[str, dict] = {}
    for tag, (ok_count, judged_count) in _report_tag_points(
        entry.quality_report
    ).items():
        aggregate = profile.setdefault(tag, {'earned': 0.0, 'total': 0, 'attempts': 0})
        aggregate['earned'] += ok_count * 100
        aggregate['total'] += judged_count * 100
        aggregate['attempts'] += 1
    return profile
