import json
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
    PracticeCase,
    PracticePlan,
    PracticeProblem,
)
from school.judge import CaseOutcome
from school.models import (
    ClassStaff,
    ClassStudent,
    Classroom,
    Problem,
    ProblemVersion,
    User,
    UserRole,
)
from school.portal import knowledge_profile, practice_agent
from school.storage import read_private, save_private

TEST_OVERRIDES = dict(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    LLM_BASE_URL='',
    LLM_API_KEY='',
    LLM_MODEL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)


def make_user(username, role):
    user = User.objects.create_user(
        username=username,
        full_name=username,
        student_no=username,
        password='Password-2026!',
        must_change_password=False,
    )
    UserRole.objects.create(user=user, role=role)
    return user


@override_settings(**TEST_OVERRIDES)
class KnowledgeProfileTests(TestCase):
    def setUp(self):
        self.teacher = make_user('teacher', 'teacher')
        self.student = make_user('student', 'student')
        self.classroom = Classroom.objects.create(code='R1', name='画像班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='列表练习',
            description='实现列表相关函数',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        self.item_a = CourseworkItem.objects.create(
            coursework=self.work, function_name='func301', title='合并并截取', points=10, order=1
        )
        self.item_b = CourseworkItem.objects.create(
            coursework=self.work, function_name='func303', title='回文判断', points=10, order=2
        )
        CourseworkRubric.objects.create(
            coursework=self.work,
            markdown='# 评分标准',
            knowledge_points=[
                {'name': '列表切片', 'detail': '', 'tasks': ['func301']},
                {'name': '回文判断', 'detail': '', 'tasks': ['func303']},
            ],
            dimensions=[],
            source='rule',
        )

    def _submit(self, student, sequence, scores):
        entry = CourseworkSubmission.objects.create(
            coursework=self.work,
            student=student,
            sequence=sequence,
            source_path='objects/x.py',
            source_hash='hash',
            status='done',
        )
        for function_name, score in scores.items():
            item = self.item_a if function_name == 'func301' else self.item_b
            CourseworkQuestionResult.objects.create(
                submission=entry,
                function_name=function_name,
                title=item.title,
                order=item.order,
                points=item.points,
                score=score,
                passed_cases=0,
                total_cases=4,
                verdict='WA',
            )
        return entry

    def test_profile_takes_best_score_across_attempts(self):
        self._submit(self.student, 1, {'func301': 3, 'func303': 9})
        self._submit(self.student, 2, {'func301': 7, 'func303': 5})
        profile = knowledge_profile.student_knowledge_profile(self.student)
        self.assertEqual(profile['列表切片']['earned'], 7)
        self.assertEqual(profile['列表切片']['total'], 10)
        self.assertEqual(profile['回文判断']['earned'], 9)

    def test_weak_points_sorted_and_filtered(self):
        self._submit(self.student, 1, {'func301': 3, 'func303': 10})
        weak = knowledge_profile.weak_points(
            knowledge_profile.student_knowledge_profile(self.student)
        )
        self.assertEqual([item['name'] for item in weak], ['列表切片'])
        self.assertEqual(weak[0]['percent'], 30.0)

    def test_students_without_done_entries_have_empty_weak_list(self):
        self._submit(self.student, 1, {'func301': 3, 'func303': 9})
        other = make_user('other', 'student')
        ClassStudent.objects.create(classroom=self.classroom, student=other)
        self.assertEqual(knowledge_profile.student_knowledge_profile(other), {})
        self.assertEqual(knowledge_profile.weak_points({}), [])

    def test_class_summary_counts_weak_students(self):
        other = make_user('other', 'student')
        ClassStudent.objects.create(classroom=self.classroom, student=other)
        self._submit(self.student, 1, {'func301': 3, 'func303': 10})
        self._submit(other, 1, {'func301': 9, 'func303': 2})
        summary = knowledge_profile.class_knowledge_summary(self.classroom)
        by_name = {item['name']: item for item in summary}
        self.assertEqual(by_name['列表切片']['avg_percent'], 60.0)
        self.assertEqual(by_name['列表切片']['weak_students'], 1)
        self.assertEqual(by_name['回文判断']['avg_percent'], 60.0)


@override_settings(**TEST_OVERRIDES)
class PracticeAgentTests(TestCase):
    def setUp(self):
        self.teacher = make_user('teacher', 'teacher')
        self.student = make_user('student', 'student')
        self.classroom = Classroom.objects.create(code='R2', name='训练班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='切片作业',
            description='实现切片函数',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        item = CourseworkItem.objects.create(
            coursework=self.work, function_name='func301', title='合并并截取', points=10, order=1
        )
        CourseworkRubric.objects.create(
            coursework=self.work,
            markdown='# 评分标准',
            knowledge_points=[
                {'name': '列表切片', 'detail': '', 'tasks': ['func301']},
            ],
            dimensions=[],
            source='rule',
        )
        entry = CourseworkSubmission.objects.create(
            coursework=self.work,
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

    def _seed_bank_problem(self):
        problem = Problem.objects.create(
            code='PRACTICE-1',
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
            template_code='print(input().split()[1:4])',
            reference_path=save_private('print(input().split()[1:4])', suffix='.py'),
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
        return version

    def test_no_weak_point_returns_none(self):
        other = make_user('other', 'student')
        ClassStudent.objects.create(classroom=self.classroom, student=other)
        self.assertIsNone(practice_agent.generate_practice_plan(other))
        self.assertFalse(PracticePlan.objects.filter(student=other).exists())

    def test_missing_llm_does_not_fake_result(self):
        with self.assertRaises(practice_agent.LLMNotConfigured):
            practice_agent.generate_practice_plan(self.student)
        self.assertFalse(PracticePlan.objects.filter(student=self.student).exists())

    def test_offline_fallback_uses_existing_bank(self):
        self._seed_bank_problem()
        plan = practice_agent.generate_practice_plan(self.student, offline=True)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.source, 'rule')
        self.assertEqual(plan.model, '')
        problems = list(plan.problems.all())
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].knowledge_point, '列表切片')
        self.assertEqual(problems[0].cases.count(), 2)
        case = problems[0].cases.order_by('order').first()
        self.assertEqual(read_private(case.input_path), '1 2 3 4 5')

    def test_offline_fallback_without_bank_raises(self):
        with self.assertRaises(practice_agent.PracticeParseError):
            practice_agent.generate_practice_plan(self.student, offline=True)
        self.assertFalse(PracticePlan.objects.filter(student=self.student).exists())

    def test_llm_generation_with_mock(self):
        payload = {
            'questions': [
                {
                    'knowledge_point': '列表切片',
                    'title': '区间裁剪',
                    'statement': '读入整数序列，输出第 2 到 4 个元素。',
                    'difficulty': '基础',
                    'template_code': 'print(input().split()[1:4])',
                    'reference_code': 'print(input().split()[1:4])',
                    'explanation': '切片起始下标换算',
                    'test_cases': [
                        {'input': '1 2 3 4 5', 'output': '2 3 4', 'is_sample': True},
                        {'input': '9 8 7 6 5', 'output': '8 7 6', 'is_sample': False},
                        {'input': '1', 'output': '1', 'is_sample': False},
                    ],
                },
                {
                    'knowledge_point': '不属于弱项',
                    'title': '无关题',
                    'statement': '题面',
                    'test_cases': [{'input': '1', 'output': '1'}],
                },
            ]
        }
        with mock.patch.object(practice_agent, 'chat', return_value=json.dumps(payload)), \
                mock.patch.object(practice_agent, 'llm_configured', return_value=True):
            plan = practice_agent.generate_practice_plan(self.student)
        self.assertEqual(plan.source, 'llm')
        problems = list(plan.problems.all())
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].title, '区间裁剪')
        self.assertEqual(problems[0].cases.count(), 3)
        self.assertEqual(plan.profile_snapshot['weak'][0]['name'], '列表切片')

    def test_parse_rejects_bad_output(self):
        with self.assertRaises(practice_agent.PracticeParseError):
            practice_agent.parse_practice('没有 JSON 的输出', ['列表切片'])
        with self.assertRaises(practice_agent.PracticeParseError):
            practice_agent.parse_practice(
                json.dumps({'questions': [{'knowledge_point': '列表切片', 'title': '缺用例'}]}),
                ['列表切片'],
            )

    def _direct_problem(self):
        plan = PracticePlan.objects.create(
            student=self.student,
            profile_snapshot={},
            source='llm',
            model='test-model',
        )
        problem = PracticeProblem.objects.create(
            plan=plan,
            knowledge_point='列表切片',
            title='区间裁剪',
            statement='题面',
            order=1,
        )
        for index, (stdin, expected) in enumerate(
            [('1 2 3', '2'), ('4 5 6', '5'), ('7 8 9', '8')], start=1
        ):
            PracticeCase.objects.create(
                problem=problem,
                order=index,
                input_path=save_private(stdin),
                output_path=save_private(expected),
                is_sample=index == 1,
            )
        return problem

    def test_grade_attempt_scores_by_case_ratio(self):
        problem = self._direct_problem()
        attempt = PracticeAttempt.objects.create(
            problem=problem,
            student=self.student,
            code_path=save_private('print(input())', suffix='.py'),
        )
        outcomes = [CaseOutcome('AC', 5), CaseOutcome('WA', 5), CaseOutcome('AC', 5)]
        with mock.patch.object(practice_agent, 'run_case', side_effect=outcomes):
            practice_agent.grade_attempt(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.passed_cases, 2)
        self.assertEqual(attempt.total_cases, 3)
        self.assertEqual(float(attempt.score), 66.7)
        self.assertEqual(attempt.verdict, 'WA')

    def test_grade_attempt_marks_infrastructure_error(self):
        problem = self._direct_problem()
        attempt = PracticeAttempt.objects.create(
            problem=problem,
            student=self.student,
            code_path=save_private('print(input())', suffix='.py'),
        )
        with mock.patch.object(
            practice_agent,
            'run_case',
            side_effect=practice_agent.InfrastructureError('DOCKER_UNAVAILABLE'),
        ):
            with self.assertRaises(practice_agent.InfrastructureError):
                practice_agent.grade_attempt(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.verdict, 'ERROR')


@override_settings(**TEST_OVERRIDES)
class PracticeViewTests(TestCase):
    def setUp(self):
        self.teacher = make_user('teacher', 'teacher')
        self.student = make_user('student', 'student')
        self.other = make_user('other', 'student')
        self.classroom = Classroom.objects.create(code='R3', name='视图班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        ClassStudent.objects.create(classroom=self.classroom, student=self.other)
        self.plan = PracticePlan.objects.create(student=self.student, profile_snapshot={})
        self.problem = PracticeProblem.objects.create(
            plan=self.plan,
            knowledge_point='列表切片',
            title='区间裁剪',
            statement='题面',
            order=1,
        )

    def test_home_shows_profile_and_requires_student(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('practice'))
        self.assertEqual(response.status_code, 200)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('practice')).status_code, 403)

    def test_problem_visible_only_to_owner(self):
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse('practice_problem', args=[self.problem.pk])).status_code, 200
        )
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse('practice_problem', args=[self.problem.pk])).status_code, 403
        )

    def test_teacher_overview_permissions(self):
        self.client.force_login(self.teacher)
        self.assertEqual(
            self.client.get(reverse('class_practice', args=[self.classroom.pk])).status_code, 200
        )
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse('class_practice', args=[self.classroom.pk])).status_code, 403
        )

    def test_offline_generation_from_home(self):
        self._seed_weak_record()
        problem = Problem.objects.create(
            code='PRACTICE-2',
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
            reference_path=save_private('print(input())', suffix='.py'),
        )
        version.cases.create(
            order=1,
            input_path=save_private('1 2 3 4 5'),
            output_path=save_private('2 3 4'),
        )
        self.client.force_login(self.student)
        response = self.client.post(reverse('practice'), {'mode': 'offline'})
        self.assertRedirects(response, reverse('practice'))
        plan = PracticePlan.objects.filter(student=self.student).order_by('-pk').first()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.source, 'rule')
        self.assertEqual(plan.problems.count(), 1)

    def _seed_weak_record(self):
        work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='切片作业',
            description='实现切片函数',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
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

    def test_home_without_weak_points_blocks_generation(self):
        other = self.other
        self.client.force_login(other)
        response = self.client.get(reverse('practice'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '当前没有得分率偏低的弱项知识点')
