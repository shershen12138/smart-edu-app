# -*- coding: utf-8 -*-
"""提高覆盖率的补充测试：画像聚合（教师端汇总、任务画像）与 practice_agent 计划/LLM 分支。

LLM 与真实容器批阅均用 mock 模拟（与 school/tests 既有做法一致），
覆盖的是分支逻辑本身，不把模拟结果当作真实批阅通过。
"""
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from school.course_models import (
    Coursework,
    CourseworkItem,
    CourseworkQuestionResult,
    CourseworkRubric,
    CourseworkSubmission,
    PracticeAttempt,
    PracticePlan,
    PracticeProblem,
    QualityReport,
)
from school.judge import CaseOutcome
from school.models import Classroom, ClassStaff, ClassStudent, User, UserRole
from school.portal import knowledge_profile, practice_agent
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


@override_settings(**TEST_OVERRIDES)
class ProfileAggregationTests(TestCase):
    """教师端班级汇总与单任务画像（knowledge_profile）。"""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

        self.teacher = self._make_user('teacher', 'teacher')
        self.student = self._make_user('student', 'student')
        self.classroom = Classroom.objects.create(code='C1', name='覆盖班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom, user=self.teacher,
            role='teacher', can_edit=True, can_view_grades=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.work, self.item = self._make_work('列表切片')

    def _make_user(self, username, role):
        user = User.objects.create_user(
            username=username, full_name=username, student_no=username,
            password='Password-2026!', must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def _make_work(self, tag):
        work = Coursework.objects.create(
            classroom=self.classroom, owner=self.teacher, title='切片作业',
            description='', grading_mode='automatic',
            opens_at=timezone.now(), deadline=timezone.now() + timedelta(days=1),
            status='open',
        )
        item = CourseworkItem.objects.create(
            coursework=work, function_name='func301', title='合并并截取', points=10, order=1
        )
        CourseworkRubric.objects.create(
            coursework=work, markdown='# 评分标准',
            knowledge_points=[{'name': tag, 'detail': '', 'tasks': ['func301']}],
            dimensions=[], source='rule',
        )
        return work, item

    def _seed_report(self, student, work, tag, ok, sequence=1):
        entry = CourseworkSubmission.objects.create(
            coursework=work, student=student, sequence=sequence,
            source_path='objects/x.py', source_hash='hash', status='done',
        )
        CourseworkQuestionResult.objects.create(
            submission=entry, function_name='func301', title='合并并截取',
            order=1, points=10, score=10 if ok else 0,
            passed_cases=4 if ok else 1, total_cases=4, verdict='AC' if ok else 'WA',
        )
        QualityReport.objects.create(
            submission=entry, source_sha256='hash',
            payload={'tasks': [{'task_id': 'func301', 'points': [
                {'tag': '', 'label': tag, 'ok': ok, 'judged': True}]}]},
        )
        return entry

    def test_task_profile_from_report(self):
        self._seed_report(self.student, self.work, '列表切片', ok=False)
        profile = knowledge_profile.task_profile(self.student, self.work)
        self.assertIn('列表切片', profile)
        self.assertEqual(profile['列表切片']['attempts'], 1)
        self.assertAlmostEqual(profile['列表切片']['earned'], 0.0)
        profiles = knowledge_profile.task_profiles(self.student)
        self.assertEqual(len(profiles), 1)

    def test_profile_for_work_without_submission(self):
        self.assertEqual(knowledge_profile._profile_for_work(self.work, self.student.pk), {})

    def test_class_summary_empty_class(self):
        empty = Classroom.objects.create(code='C2', name='空班', term='2026 秋季')
        self.assertEqual(knowledge_profile.class_knowledge_summary(empty), [])

    def test_class_summary_without_reports(self):
        self.assertEqual(knowledge_profile.class_knowledge_summary(self.classroom), [])

    def test_class_summary_aggregates_and_sorts(self):
        self._seed_report(self.student, self.work, '列表切片', ok=False)
        other = self._make_user('student2', 'student')
        ClassStudent.objects.create(classroom=self.classroom, student=other)
        self._seed_report(other, self.work, '列表切片', ok=True, sequence=1)

        summary = knowledge_profile.class_knowledge_summary(self.classroom)
        self.assertEqual(len(summary), 1)
        row = summary[0]
        self.assertEqual(row['name'], '列表切片')
        self.assertEqual(row['student_count'], 2)
        self.assertEqual(row['weak_students'], 1)
        self.assertAlmostEqual(row['avg_percent'], 50.0)
        # 得分率 50% < 0.6 阈值 → 该知识点本身也被视为全班弱项
        self.assertLess(row['avg_percent'], knowledge_profile.weak_threshold() * 100)

    def test_class_summary_skips_work_without_rubric_points(self):
        work, _ = self._make_work('列表切片')
        rubric = work.rubric
        rubric.knowledge_points = []
        rubric.save()
        self._seed_report(self.student, work, '列表切片', ok=False)
        self.assertEqual(knowledge_profile.class_knowledge_summary(self.classroom), [])


@override_settings(**TEST_OVERRIDES)
class PracticeAgentCoverageTests(TestCase):
    """practice_agent：计划查询、上下文、LLM 分支与函数式批阅。"""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

        self.teacher = self._make_user('teacher', 'teacher')
        self.student = self._make_user('student', 'student')
        self.classroom = Classroom.objects.create(code='P1', name='计划班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom, user=self.teacher,
            role='teacher', can_edit=True, can_view_grades=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.work, self.item = self._make_work('列表切片')
        self._seed_report('列表切片', ok=False)

    def _make_user(self, username, role):
        user = User.objects.create_user(
            username=username, full_name=username, student_no=username,
            password='Password-2026!', must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def _make_work(self, tag):
        work = Coursework.objects.create(
            classroom=self.classroom, owner=self.teacher, title='切片作业',
            description='', grading_mode='automatic',
            opens_at=timezone.now(), deadline=timezone.now() + timedelta(days=1),
            status='open',
        )
        item = CourseworkItem.objects.create(
            coursework=work, function_name='func301', title='合并并截取', points=10, order=1
        )
        CourseworkRubric.objects.create(
            coursework=work, markdown='# 评分标准',
            knowledge_points=[{'name': tag, 'detail': '', 'tasks': ['func301']}],
            dimensions=[], source='rule',
        )
        return work, item

    def _seed_report(self, tag, ok):
        entry = CourseworkSubmission.objects.create(
            coursework=self.work, student=self.student, sequence=1,
            source_path='objects/x.py', source_hash='hash', status='done',
        )
        CourseworkQuestionResult.objects.create(
            submission=entry, function_name='func301', title='合并并截取',
            order=1, points=10, score=0, passed_cases=1, total_cases=4, verdict='WA',
        )
        QualityReport.objects.create(
            submission=entry, source_sha256='hash',
            payload={'tasks': [{'task_id': 'func301', 'points': [
                {'tag': '', 'label': tag, 'ok': ok, 'judged': True}]}]},
        )

    # ---- 上下文与查询 ----

    def test_practice_context_with_and_without_work(self):
        with_work = practice_agent.practice_context(self.student, work=self.work)
        self.assertIn('work_title', with_work)
        self.assertEqual(with_work['work_title'], self.work.title)
        without_work = practice_agent.practice_context(self.student)
        self.assertNotIn('work', without_work)
        self.assertEqual(without_work['weak'], with_work['weak'])

    def test_existing_titles(self):
        plan = PracticePlan.objects.create(student=self.student, profile_snapshot={}, source='rule')
        PracticeProblem.objects.create(
            plan=plan, knowledge_point='列表切片', title='旧题目', statement='', order=1,
        )
        self.assertEqual(practice_agent.existing_titles(self.student), ['旧题目'])

    def test_latest_plan_filters_status_and_work(self):
        ready = PracticePlan.objects.create(
            student=self.student, profile_snapshot={'work_id': self.work.pk}, source='rule',
        )
        PracticePlan.objects.create(
            student=self.student, profile_snapshot={}, source='rule', status='draft',
        )
        self.assertEqual(practice_agent.latest_plan(self.student).pk, ready.pk)
        self.assertEqual(practice_agent.latest_plan(self.student, work=self.work).pk, ready.pk)
        other_work = Coursework.objects.create(
            classroom=self.classroom, owner=self.teacher, title='其他作业',
            grading_mode='automatic', opens_at=timezone.now(),
            deadline=timezone.now() + timedelta(days=1), status='open',
        )
        self.assertIsNone(practice_agent.latest_plan(self.student, work=other_work))

    def test_llm_configured_and_status_text(self):
        self.assertFalse(practice_agent.llm_configured(self.student))
        self.assertTrue(isinstance(practice_agent.status_text(self.student), str))

    # ---- LLM 生成分支（mock） ----

    def _llm_payload(self):
        return {
            'questions': [{
                'knowledge_point': '列表切片',
                'title': 'LLM 出题',
                'statement': '输出切片结果',
                'difficulty': '基础',
                'template_code': 'print(input().split()[1:4])',
                'reference_code': 'print(input().split()[1:4])',
                'explanation': '思路',
                'test_cases': [{'input': '1 2 3 4 5', 'output': '2 3 4', 'is_sample': True}],
            }],
        }

    def test_build_messages_contains_profile_and_rules(self):
        messages = practice_agent.build_messages(
            [{'name': '列表切片', 'rate': 0.4}], [{'name': '字典操作'}], ['旧题目'],
        )
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[1]['role'], 'user')
        self.assertIn('列表切片', messages[1]['content'])
        self.assertIn('旧题目', messages[1]['content'])

    def test_llm_generation_stores_plan(self):
        payload = self._llm_payload()
        with mock.patch.object(practice_agent, 'llm_configured', return_value=True), \
                mock.patch.object(practice_agent, 'chat', return_value=json.dumps(payload, ensure_ascii=False)) as chat_mock, \
                mock.patch.object(practice_agent.llm_client, 'get_config',
                                  return_value=SimpleNamespace(model='mock-model')):
            plan = practice_agent.generate_practice_plan(self.student)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.source, 'llm')
        self.assertEqual(plan.model, 'mock-model')
        problems = list(plan.problems.order_by('order'))
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].title, 'LLM 出题')
        self.assertEqual(problems[0].cases.count(), 1)
        # chat 收到 build_messages 的输出（system + user 两条）
        messages = chat_mock.call_args.args[0]
        self.assertEqual([m['role'] for m in messages], ['system', 'user'])

    def test_llm_garbage_output_raises(self):
        with mock.patch.object(practice_agent, 'llm_configured', return_value=True), \
                mock.patch.object(practice_agent, 'chat', return_value='这不是 JSON'):
            with self.assertRaises(practice_agent.PracticeParseError):
                practice_agent.generate_practice_plan(self.student)

    def test_rule_fallback_without_bank_match_raises(self):
        """弱项不在任何题库/词表中且未配 LLM：规则兜底无题可出，明确报错而非伪造计划。"""
        work, _ = self._make_work('量子纠缠调试')
        entry = CourseworkSubmission.objects.create(
            coursework=work, student=self.student, sequence=1,
            source_path='objects/y.py', source_hash='hash2', status='done',
        )
        CourseworkQuestionResult.objects.create(
            submission=entry, function_name='func301', title='合并并截取',
            order=1, points=10, score=0, passed_cases=0, total_cases=4, verdict='WA',
        )
        QualityReport.objects.create(
            submission=entry, source_sha256='hash2',
            payload={'tasks': [{'task_id': 'func301', 'points': [
                {'tag': '', 'label': '量子纠缠调试', 'ok': False, 'judged': True}]}]},
        )
        with self.assertRaises(practice_agent.PracticeParseError):
            practice_agent.generate_practice_plan(self.student, offline=True, work=work)
        self.assertFalse(PracticePlan.objects.filter(
            student=self.student, profile_snapshot__work_id=work.pk).exists())

    # ---- 函数式批阅（mock 判题容器） ----

    def test_grade_function_cases(self):
        plan = PracticePlan.objects.create(student=self.student, profile_snapshot={}, source='rule')
        problem = PracticeProblem.objects.create(
            plan=plan, knowledge_point='列表切片', title='函数题', statement='',
            template_code='def solve(nums):\n    pass\n',
            function_name='solve', function_argc=1, order=1,
        )
        packed = '{"type": "list", "items": []}'
        for index, args_line in enumerate(['[1, 2, 3]', '[4, 5]'], start=1):
            problem.cases.create(
                order=index,
                input_path=save_private(args_line),
                output_path=save_private(packed),
                is_sample=index == 1,
            )
        attempt = PracticeAttempt.objects.create(
            problem=problem, student=self.student,
            code_path=save_private('def solve(nums):\n    return []\n', suffix='.py'),
        )
        outcomes = [CaseOutcome('AC', 5, packed), CaseOutcome('WA', 8, '{"type": "none"}')]
        with mock.patch.object(practice_agent.grading, 'grade_submission',
                               return_value=[[outcomes[0], outcomes[1]]]) as grader:
            practice_agent.grade_attempt(attempt)
        grader.assert_called_once()
        item = grader.call_args.args[1][0]
        self.assertEqual(item['function'], 'solve')
        self.assertEqual(item['inputs'], ['[1, 2, 3]', '[4, 5]'])
        attempt.refresh_from_db()
        self.assertEqual(attempt.passed_cases, 1)
        self.assertEqual(attempt.total_cases, 2)
        self.assertEqual(float(attempt.score), 50.0)
        self.assertEqual(attempt.verdict, 'WA')
        rows = list(attempt.case_results.order_by('order'))
        self.assertEqual([row.verdict for row in rows], ['AC', 'WA'])
