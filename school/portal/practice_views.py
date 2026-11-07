"""学生端与教师端：知识点弱项画像与个性化训练题。"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from django.db.models import Q

from school.course_models import PracticeAttempt, PracticeProblem
from school.judge import InfrastructureError
from school.models import Classroom, ProblemVersion
from school.storage import read_private, save_private

from . import knowledge_profile, practice_agent
from .access import allowed, require_role, role
from .common_views import page
from .practice_agent import LLMNotConfigured, PracticeParseError
from .rubric_agent import LLMError


class PracticeSubmitForm(forms.Form):
    code = forms.CharField(
        label='代码',
        widget=forms.Textarea(attrs={'rows': 16, 'spellcheck': 'false'}),
    )


def _problem_for_student(request, pk) -> PracticeProblem:
    problem = get_object_or_404(PracticeProblem.objects.select_related('plan'), pk=pk)
    if problem.plan.student_id != request.user.pk or role(request.user) != 'student':
        raise PermissionDenied
    return problem


def _sample_cases(problem):
    return [
        {
            'input': _case_text(case.input_path),
            'output': _case_text(case.output_path),
        }
        for case in problem.cases.filter(is_sample=True).order_by('order')
    ]


def _bank_has_matches(weak) -> bool:
    """题库中是否存在带用例、知识点标签能匹配任一弱项的现成题。"""
    names = [item['name'] for item in weak]
    if not names:
        return True
    query = Q()
    for name in names:
        query |= Q(knowledge__icontains=name)
    return ProblemVersion.objects.filter(query, cases__isnull=False).exists()


def _case_text(key):
    try:
        return read_private(key)
    except Exception:
        return ''


@login_required
@require_http_methods(['GET', 'POST'])
def practice_home(request):
    require_role(request.user, 'student')
    if request.method == 'POST':
        offline = request.POST.get('mode') == 'offline'
        try:
            plan = practice_agent.generate_practice_plan(request.user, offline=offline)
        except LLMNotConfigured as exc:
            messages.error(request, str(exc))
        except (LLMError, PracticeParseError) as exc:
            messages.error(request, f'生成失败：{exc}')
        else:
            if plan is None:
                messages.info(request, '当前没有得分率偏低的弱项知识点，暂不需要生成训练题。')
            elif offline:
                messages.warning(request, '已按规则兜底生成训练题，结果标注为“规则兜底”，不是大模型结论。')
            else:
                messages.success(request, '已调用大模型生成本次个性化训练题。')
        return redirect('practice')

    profile = knowledge_profile.student_knowledge_profile(request.user)
    weak = knowledge_profile.weak_points(profile)
    mastered = knowledge_profile.mastered_points(profile)
    plan = practice_agent.latest_plan(request.user)
    problems = list(plan.problems.all()) if plan else []
    grouped: dict[str, list] = {}
    for problem in problems:
        grouped.setdefault(problem.knowledge_point, []).append(problem)
    return page(
        request,
        'practice',
        '个性化训练',
        weak=weak,
        mastered=mastered,
        plan=plan,
        grouped=grouped,
        llm_ready=practice_agent.llm_configured(),
        llm_status=practice_agent.status_text(),
        bank_ready=_bank_has_matches(weak),
        back_url=reverse('dashboard'),
    )


@login_required
def practice_problem(request, pk):
    problem = _problem_for_student(request, pk)
    attempts = problem.attempts.filter(student=request.user).order_by('-created_at')[:10]
    form = (
        PracticeSubmitForm(initial={'code': problem.template_code}) if not attempts else None
    )
    return page(
        request,
        'practice_problem',
        problem.title,
        problem=problem,
        samples=_sample_cases(problem),
        attempts=attempts,
        form=form,
        back_url=reverse('practice'),
        back_label='返回训练计划',
    )


@login_required
@require_http_methods(['POST'])
def practice_submit(request, pk):
    problem = _problem_for_student(request, pk)
    form = PracticeSubmitForm(request.POST)
    if not form.is_valid():
        messages.error(request, '提交内容为空或格式不正确。')
        return redirect('practice_problem', pk=pk)
    attempt = PracticeAttempt.objects.create(
        problem=problem,
        student=request.user,
        code_path=save_private(form.cleaned_data['code'], suffix='.py'),
    )
    try:
        practice_agent.grade_attempt(attempt)
    except InfrastructureError:
        messages.error(
            request,
            '批阅服务暂不可用（需要 Docker 与 python:3.12-slim 镜像），稍后可重试。',
        )
        return redirect('practice_problem', pk=pk)
    messages.success(
        request, f'批阅完成：通过 {attempt.passed_cases}/{attempt.total_cases} 组用例。'
    )
    return redirect('practice_result', pk=attempt.pk)


@login_required
def practice_result(request, pk):
    attempt = get_object_or_404(
        PracticeAttempt.objects.select_related('problem'), pk=pk
    )
    if attempt.student_id != request.user.pk:
        raise PermissionDenied
    return page(
        request,
        'practice_result',
        '训练题批阅结果',
        attempt=attempt,
        problem=attempt.problem,
        samples=_sample_cases(attempt.problem),
        back_url=reverse('practice_problem', args=[attempt.problem_id]),
        back_label='返回题目',
    )


@login_required
def practice_overview(request, class_id):
    classroom = get_object_or_404(
        Classroom, pk=class_id, deleted_at__isnull=True, archived=False
    )
    if not allowed(request.user, classroom, 'view_grades'):
        raise PermissionDenied
    summary = knowledge_profile.class_knowledge_summary(classroom)
    students = []
    for member in classroom.members.filter(active=True).select_related('student'):
        plan = practice_agent.latest_plan(member.student)
        students.append({'student': member.student, 'plan': plan})
    return page(
        request,
        'class_practice',
        f'{classroom.name} · 知识点弱项分布',
        classroom=classroom,
        summary=summary,
        students=students,
        back_url=reverse('results'),
    )
