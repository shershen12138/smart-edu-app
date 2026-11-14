# -*- coding: utf-8 -*-
"""任务 3：场景法端到端测试 —— 学生"弱项练习"关键业务流程。

被测业务流程：登录 → 查看弱项画像 → 生成训练计划 → 查看训练题 →
提交代码 → 机器批阅 → 查看逐用例批阅结果。

场景矩阵（详见 tests/TEST_PLAN.md）：
- S1 基本流：有弱项 → 离线生成计划 → 提交正确代码 → 全部用例通过（AC）
- S2 备选流 1：提交部分正确的代码 → 部分用例通过（WA，按比例计分）
- S3 备选流 2：提交空代码 → 表单校验拒绝，不产生批阅记录
- S4 备选流 3：无弱项的学生 → 无法生成训练计划
- S5 备选流 4：越权访问他人训练题 / 批阅结果 → 403
- S6 备选流 5：未登录访问训练页 → 跳转登录页

真实容器批阅不在本用例范围内（批阅结果通过 mock run_case 模拟，
与 school/tests/test_practice_agent.py 的既有做法一致）。
"""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.course_models import (
    Coursework,
    CourseworkItem,
    CourseworkQuestionResult,
    CourseworkRubric,
    CourseworkSubmission,
    PracticeAttempt,
    PracticePlan,
    QualityReport,
)
from school.judge import CaseOutcome
from school.models import (
    Classroom,
    ClassStaff,
    ClassStudent,
    Problem,
    ProblemVersion,
    User,
    UserRole,
)
from school.portal import practice_agent
from school.storage import save_private

TEST_OVERRIDES = dict(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    LLM_BASE_URL='',
    LLM_API_KEY='',
    LLM_MODEL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)

CORRECT_CODE = 'print(input().split()[1:4])'
WRONG_CODE = 'print(input())'


@override_settings(**TEST_OVERRIDES)
class PracticeScenarioE2ETests(TestCase):
    """场景法：学生弱项练习闭环。"""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

        self.teacher = self._make_user('teacher', 'teacher')
        self.student = self._make_user('student', 'student')
        self.other = self._make_user('other', 'student')
        self.classroom = Classroom.objects.create(code='S1', name='场景班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        ClassStudent.objects.create(classroom=self.classroom, student=self.other)

        self._seed_weak_record()
        self._seed_bank_problem()

    def _make_user(self, username, role):
        user = User.objects.create_user(
            username=username,
            full_name=username,
            student_no=username,
            password='Password-2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def _seed_weak_record(self):
        """给 self.student 造一次暴露弱项"列表切片"的作业提交记录。"""
        work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='切片作业',
            description='实现切片函数',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timedelta(days=1),
            status='open',
        )
        item = CourseworkItem.objects.create(
            coursework=work, function_name='func301', title='合并并截取', points=10, order=1
        )
        CourseworkRubric.objects.create(
            coursework=work,
            markdown='# 评分标准',
            knowledge_points=[{'name': '列表切片', 'detail': '', 'tasks': ['func301']}],
            dimensions=[],
            source='rule',
        )
        entry = CourseworkSubmission.objects.create(
            coursework=work,
            student=self.student,
            sequence=1,
            source_path='objects/x.py',
            source_hash='hash',
            status='done',
        )
        CourseworkQuestionResult.objects.create(
            submission=entry,
            function_name=item.function_name,
            title=item.title,
            order=item.order,
            points=item.points,
            score=3,
            passed_cases=1,
            total_cases=4,
            verdict='WA',
        )
        QualityReport.objects.create(
            submission=entry,
            source_sha256='hash',
            payload={
                'tasks': [
                    {
                        'task_id': 'func301',
                        'points': [
                            {'tag': '', 'label': '列表切片', 'ok': False, 'judged': True}
                        ],
                    }
                ],
            },
        )

    def _seed_bank_problem(self):
        problem = Problem.objects.create(
            code='PRACTICE-S1',
            classroom=self.classroom,
            created_by=self.teacher,
        )
        version = ProblemVersion.objects.create(
            problem=problem,
            title='切片基础',
            statement='读入一行整数，输出第 2 到 4 个元素。',
            input_format='一行整数',
            output_format='空格分隔',
            knowledge='列表切片',
            template_code=CORRECT_CODE,
            reference_path=save_private(CORRECT_CODE, suffix='.py'),
        )
        version.cases.create(
            order=1,
            input_path=save_private('1 2 3 4 5'),
            output_path=save_private('2 3 4'),
            is_sample=True,
        )
        version.cases.create(
            order=2,
            input_path=save_private('9 8 7 6 5'),
            output_path=save_private('8 7 6'),
        )

    def _generate_plan(self):
        """S1 前置步骤：登录并离线生成训练计划，返回第一道训练题。"""
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('practice')).status_code, 200)
        response = self.client.post(reverse('practice'), {'mode': 'offline'})
        self.assertRedirects(response, reverse('practice'))
        plan = PracticePlan.objects.filter(student=self.student).order_by('-pk').first()
        self.assertIsNotNone(plan, '应当成功生成训练计划')
        self.assertEqual(plan.source, 'rule')
        problems = list(plan.problems.order_by('order'))
        self.assertTrue(problems, '训练计划应包含至少一道题')
        return problems[0]

    def test_s1_happy_path_full_pass(self):
        """S1 基本流：生成计划 → 提交正确代码 → 全部用例通过 → 结果页可见。"""
        problem = self._generate_plan()
        self.assertEqual(problem.knowledge_point, '列表切片')

        response = self.client.get(reverse('practice_problem', args=[problem.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, problem.title)

        with mock.patch.object(
            practice_agent,
            'run_case',
            side_effect=[CaseOutcome('AC', 5, '2 3 4'), CaseOutcome('AC', 6, '8 7 6')],
        ):
            response = self.client.post(
                reverse('practice_submit', args=[problem.pk]), {'code': CORRECT_CODE}
            )
        attempt = PracticeAttempt.objects.filter(
            problem=problem, student=self.student
        ).order_by('-pk').first()
        self.assertIsNotNone(attempt)
        self.assertRedirects(response, reverse('practice_result', args=[attempt.pk]))

        attempt.refresh_from_db()
        self.assertEqual(attempt.verdict, 'AC')
        self.assertEqual(attempt.passed_cases, 2)
        self.assertEqual(attempt.total_cases, 2)
        self.assertEqual(float(attempt.score), 100.0)

        response = self.client.get(reverse('practice_result', args=[attempt.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '批阅结果')

    def test_s2_partial_pass_scores_by_ratio(self):
        """S2 备选流：部分用例通过 → 按通过比例计分（1/2 = 50 分，WA）。"""
        problem = self._generate_plan()
        with mock.patch.object(
            practice_agent,
            'run_case',
            side_effect=[CaseOutcome('AC', 5, '2 3 4'), CaseOutcome('WA', 6, '9 8 7 6 5')],
        ):
            response = self.client.post(
                reverse('practice_submit', args=[problem.pk]), {'code': WRONG_CODE}
            )
        attempt = PracticeAttempt.objects.filter(
            problem=problem, student=self.student
        ).order_by('-pk').first()
        self.assertRedirects(response, reverse('practice_result', args=[attempt.pk]))
        attempt.refresh_from_db()
        self.assertEqual(attempt.verdict, 'WA')
        self.assertEqual(attempt.passed_cases, 1)
        self.assertEqual(float(attempt.score), 50.0)

    def test_s3_empty_code_rejected_without_attempt(self):
        """S3 备选流：空代码提交 → 表单校验拒绝，不产生批阅记录。"""
        problem = self._generate_plan()
        response = self.client.post(
            reverse('practice_submit', args=[problem.pk]), {'code': ''}
        )
        self.assertRedirects(response, reverse('practice_problem', args=[problem.pk]))
        self.assertFalse(PracticeAttempt.objects.filter(problem=problem).exists())

    def test_s4_student_without_weak_points_cannot_generate(self):
        """S4 备选流：没有弱项的学生 → 无法生成训练计划。"""
        self.client.force_login(self.other)
        self.client.post(reverse('practice'), {'mode': 'offline'})
        self.assertFalse(PracticePlan.objects.filter(student=self.other).exists())

    def test_s5_cross_student_access_forbidden(self):
        """S5 备选流：越权访问他人训练题与批阅结果 → 403。"""
        problem = self._generate_plan()
        attempt = PracticeAttempt.objects.create(
            problem=problem,
            student=self.student,
            code_path=save_private(CORRECT_CODE, suffix='.py'),
        )
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse('practice_problem', args=[problem.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse('practice_result', args=[attempt.pk])).status_code, 403
        )

    def test_s6_anonymous_redirects_to_login(self):
        """S6 备选流：未登录访问训练页 → 跳转登录页。"""
        response = self.client.get(reverse('practice'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])
