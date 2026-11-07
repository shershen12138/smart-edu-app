import ast
import json
from types import SimpleNamespace
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
    PracticeCaseResult,
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
from school.portal import knowledge_profile, practice_agent, question_bank
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
        # 数据库题库表命中 1 题，分层题库文档补足到每弱项 2 题
        self.assertEqual(len(problems), 2)
        self.assertEqual(problems[0].knowledge_point, '列表切片')
        self.assertEqual(problems[0].cases.count(), 2)
        case = problems[0].cases.order_by('order').first()
        self.assertEqual(read_private(case.input_path), '1 2 3 4 5')
        # 补足的题来自分层题库文档：函数式题，框架/答案/函数签名齐全
        self.assertTrue(problems[1].title.startswith('Q4-'))
        self.assertTrue(problems[1].reference_code)
        self.assertTrue(problems[1].function_name)
        self.assertGreaterEqual(problems[1].function_argc, 1)
        self.assertIn('def ', problems[1].template_code)

    def test_grade_attempt_function_mode(self):
        """函数式题：调用 grading 批量判题，返回值按类型比对并记录逐用例明细。"""
        problem = PracticeProblem.objects.create(
            plan=self.plan_for_function_problem(),
            knowledge_point='列表切片',
            title='Q4-02 列表切片四连击',
            statement='题面',
            template_code='def func0402(nums):\n    # TODO: 在此实现\n    pass\n',
            difficulty='进阶',
            function_name='func0402',
            function_argc=1,
            order=1,
        )
        packed = json.dumps({'type': 'list', 'items': []}, ensure_ascii=False)
        for index, args_line in enumerate(['[1,2,3,4,5]', '[10,20,30]'], start=1):
            PracticeCase.objects.create(
                problem=problem,
                order=index,
                input_path=save_private(args_line),
                output_path=save_private(packed),
                is_sample=index == 1,
            )
        attempt = PracticeAttempt.objects.create(
            problem=problem,
            student=self.student,
            code_path=save_private('def func0402(nums):\n    return []\n', suffix='.py'),
        )
        outcomes = [
            CaseOutcome('AC', 12, '{"type":"list"}'),
            CaseOutcome('WA', 8, '{"type":"none"}'),
        ]
        with mock.patch.object(
            practice_agent.grading, 'grade_submission', return_value=[outcomes]
        ) as grader:
            practice_agent.grade_attempt(attempt)
        grader.assert_called_once()
        item = grader.call_args.args[1][0]
        self.assertEqual(item['function'], 'func0402')
        self.assertEqual(item['argc'], 1)
        self.assertEqual(item['inputs'], ['[1,2,3,4,5]', '[10,20,30]'])
        attempt.refresh_from_db()
        self.assertEqual(attempt.passed_cases, 1)
        self.assertEqual(attempt.total_cases, 2)
        self.assertEqual(float(attempt.score), 50.0)
        self.assertEqual(attempt.verdict, 'WA')
        rows = list(attempt.case_results.order_by('order'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].verdict, 'AC')
        self.assertEqual(rows[0].actual_output, '{"type":"list"}')
        self.assertEqual(rows[1].verdict, 'WA')

    def plan_for_function_problem(self):
        return PracticePlan.objects.create(
            student=self.student,
            profile_snapshot={},
            source='rule',
        )

    def test_analyze_attempt_quality_caches_payload(self):
        plan = self.plan_for_function_problem()
        problem = PracticeProblem.objects.create(
            plan=plan,
            knowledge_point='列表切片',
            title='Q4-02 列表切片四连击',
            statement='题面',
            function_name='func0402',
            function_argc=1,
            order=1,
        )
        attempt = PracticeAttempt.objects.create(
            problem=problem,
            student=self.student,
            code_path=save_private('def func0402(nums):\n    return []\n', suffix='.py'),
        )
        analysis = SimpleNamespace(
            total=88.4,
            grade='B',
            scores={'knowledge': 90.0, 'syntax': 85.0},
            style_notes=[],
            results=[
                SimpleNamespace(
                    spec=SimpleNamespace(task_id='func0402', title='列表切片四连击'),
                    parsed=True,
                    covered=['列表/切片'],
                    missing=['列表/步长切片'],
                    issues=[],
                )
            ],
        )
        dimensions = [SimpleNamespace(key='knowledge', label='知识点覆盖')]
        with mock.patch.object(
            practice_agent.quality_agent,
            'analyze',
            return_value=(analysis, dimensions, '使用内置默认量表'),
        ):
            payload = practice_agent.analyze_attempt_quality(attempt)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['total'], 88.4)
        self.assertEqual(payload['grade'], 'B')
        self.assertEqual(payload['tasks'][0]['function'], 'func0402')
        self.assertEqual(payload['tasks'][0]['covered'], ['列表/切片'])
        attempt.refresh_from_db()
        self.assertEqual(attempt.quality['total'], 88.4)
        # 二次调用直接读缓存，不再触发分析
        with mock.patch.object(
            practice_agent.quality_agent, 'analyze'
        ) as second_call:
            again = practice_agent.analyze_attempt_quality(attempt)
        second_call.assert_not_called()
        self.assertEqual(again['grade'], 'B')

    def test_format_value(self):
        packed = json.dumps(
            {'type': 'list', 'items': [{'type': 'int', 'value': 1}]}, ensure_ascii=False
        )
        self.assertEqual(practice_agent.format_value(packed), '[1]')
        self.assertEqual(practice_agent.format_value('plain output'), 'plain output')
        self.assertEqual(practice_agent.format_value(''), '')

    def test_rule_based_without_match_returns_empty(self):
        """题库表与分层题库文档都匹配不到时不出题，不造假数据。"""
        self.assertEqual(practice_agent.rule_based([{'name': '量子纠缠纠错'}]), [])

    def test_offline_keyword_match_ignores_label_wording(self):
        """题库标签写“for 循环”，弱项叫“for 遍历”，也应按关键词匹配到。"""
        problem = Problem.objects.create(
            code='PRACTICE-3',
            classroom=self.classroom,
            created_by=self.teacher,
        )
        version = ProblemVersion.objects.create(
            problem=problem,
            title='遍历求和',
            statement='读入一行整数，输出所有元素之和。',
            input_format='一行整数',
            output_format='一个整数',
            knowledge='for 循环',
            reference_path=save_private('print(sum(map(int, input().split())))', suffix='.py'),
        )
        version.cases.create(
            order=1,
            input_path=save_private('1 2 3'),
            output_path=save_private('6'),
        )
        self.assertTrue(practice_agent.bank_matches_exist([{'name': 'for 遍历'}]))
        questions = practice_agent.rule_based([{'name': 'for 遍历'}])
        # 第一题来自数据库题库表（版本题优先），其余由分层题库文档补足
        self.assertGreaterEqual(len(questions), 1)
        self.assertEqual(questions[0]['title'], '遍历求和')
        self.assertEqual(questions[0]['knowledge_point'], 'for 遍历')
        self.assertEqual(questions[0]['cases'][0]['input'], '1 2 3')

    def test_keyword_match_prefers_knowledge_over_title(self):
        """knowledge 标签命中得分高于题名命中，排序时排在前。"""
        problem = Problem.objects.create(
            code='PRACTICE-4',
            classroom=self.classroom,
            created_by=self.teacher,
        )
        by_knowledge = ProblemVersion.objects.create(
            problem=problem,
            title='综合练习一',
            statement='题面一。',
            input_format='',
            output_format='',
            knowledge='for 循环 列表遍历',
            reference_path=save_private('print(input())', suffix='.py'),
        )
        by_title = ProblemVersion.objects.create(
            problem=problem,
            number=2,
            title='for 循环遍历求和',
            statement='题面二。',
            input_format='',
            output_format='',
            knowledge='列表',
            reference_path=save_private('print(input())', suffix='.py'),
        )
        by_knowledge.cases.create(
            order=1, input_path=save_private('1'), output_path=save_private('1')
        )
        by_title.cases.create(
            order=1, input_path=save_private('2'), output_path=save_private('2')
        )
        matched = practice_agent._match_versions('for 遍历')
        self.assertEqual([version.pk for _score, version in matched][0], by_knowledge.pk)

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
        self.assertEqual(plan.problems.count(), 2)

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

    def test_home_explains_disabled_reasons(self):
        self._seed_weak_record()
        self.client.force_login(self.student)
        response = self.client.get(reverse('practice'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('主按钮为什么禁用', body)
        self.assertIn('LLM_BASE_URL', body)
        # 分层题库文档已覆盖该弱项，题库提示不应出现
        self.assertNotIn('“根据现有题库生成训练题”为什么会失败', body)

    def test_problem_page_shows_editor_and_framework(self):
        self.problem.function_name = 'func0402'
        self.problem.function_argc = 1
        self.problem.template_code = 'def func0402(nums):\n    # TODO: 在此实现\n    pass\n'
        self.problem.save()
        self.client.force_login(self.student)
        response = self.client.get(reverse('practice_problem', args=[self.problem.pk]))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('code-editor', body)
        self.assertIn('data-code-input', body)
        self.assertIn('def func0402(nums):', body)
        # 已有批阅记录时编辑器仍然可用（重新练习）
        self.assertIn('提交批阅', body)

    def test_result_page_shows_cases_quality_and_retry(self):
        PracticeCase.objects.create(
            problem=self.problem,
            order=1,
            input_path=save_private('[1,2,3]'),
            output_path=save_private('{"type":"list","items":[]}'),
            is_sample=True,
        )
        attempt = PracticeAttempt.objects.create(
            problem=self.problem,
            student=self.student,
            code_path=save_private('def f():\n    return []\n', suffix='.py'),
            score=50.0,
            passed_cases=1,
            total_cases=2,
            verdict='WA',
        )
        PracticeCaseResult.objects.create(
            attempt=attempt,
            order=1,
            verdict='AC',
            elapsed_ms=9,
            actual_output='{"type":"list","items":[]}',
        )
        PracticeCaseResult.objects.create(
            attempt=attempt,
            order=2,
            verdict='WA',
            elapsed_ms=7,
        )
        quality = {
            'total': 88.4,
            'grade': 'B',
            'note': '使用内置默认量表',
            'scores': {'knowledge': 90.0},
            'dimension_labels': {'knowledge': '知识点覆盖'},
            'tasks': [
                {
                    'function': 'func0402',
                    'title': '列表切片四连击',
                    'parsed': True,
                    'covered': ['列表/切片'],
                    'missing': [],
                    'issues': [
                        {'line': '2', 'message': '缺少实现', 'advice': '补全函数体'}
                    ],
                }
            ],
            'style_notes': [],
        }
        self.client.force_login(self.student)
        with mock.patch.object(
            practice_agent, 'analyze_attempt_quality', return_value=quality
        ):
            response = self.client.get(reverse('practice_result', args=[attempt.pk]))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('测试用例批阅明细', body)
        self.assertIn('代码质量分析', body)
        self.assertIn('重新练习', body)
        self.assertIn('知识点覆盖', body)
        self.assertIn('补全函数体', body)
        # 样例用例展示输入/期望/实际
        self.assertIn('[1,2,3]', body)


class QuestionBankTests(TestCase):
    """分层题库文档（Python题库.md，函数式批阅包）解析与选题测试。"""

    def test_load_bank_parses_all_questions(self):
        bank = question_bank.load_bank()
        self.assertEqual(len(bank), 44)
        for question in bank:
            self.assertTrue(question['code'])
            self.assertTrue(question['title'])
            self.assertTrue(question['statement'])
            self.assertTrue(question['tags'])
            self.assertTrue(question['function_name'])
            self.assertGreaterEqual(question['function_argc'], 1)
            # 函数框架与标准答案都是合法 Python 函数定义
            ast.parse(question['template_code'])
            ast.parse(question['reference_code'])
            self.assertGreaterEqual(len(question['cases']), 3)
            for case in question['cases']:
                self.assertTrue(case['input'])
                packed = json.loads(case['output'])
                self.assertIn('type', packed)

    def test_parse_sample_question_details(self):
        bank = {q['code']: q for q in question_bank.load_bank()}
        question = bank['Q4-02']
        self.assertEqual(question['title'], 'Q4-02 列表切片四连击')
        self.assertEqual(question['difficulty'], '进阶')
        self.assertEqual(question['function_name'], 'func0402')
        self.assertEqual(question['function_argc'], 1)
        self.assertIn('def func0402(nums):', question['template_code'])
        self.assertIn('TODO', question['template_code'])
        self.assertIn('nums[::-1]', question['reference_code'])
        self.assertIn('列表/切片', question['tags'])
        self.assertEqual(len(question['cases']), 10)
        self.assertTrue(question['cases'][0]['is_sample'])
        self.assertFalse(question['cases'][1]['is_sample'])
        self.assertEqual(question['cases'][0]['input'], '[1,2,3,4,5]')
        expected = json.loads(question['cases'][0]['output'])
        self.assertEqual(expected['type'], 'list')
        # 期望值 [整体反转, 偶数下标, 前三个, 最后两个] 的第一项首元素是 5
        first_reversed = expected['items'][0]['items']
        self.assertEqual(first_reversed[0]['value'], 5)

    def test_parse_multi_argument_function(self):
        bank = {q['code']: q for q in question_bank.load_bank()}
        question = bank['Q1-04']
        self.assertEqual(question['function_argc'], 2)

    def test_pack_value_matches_judge_convention(self):
        self.assertEqual(question_bank.pack_value(None), {'type': 'none'})
        self.assertEqual(question_bank.pack_value(True), {'type': 'bool', 'value': True})
        self.assertEqual(question_bank.pack_value((1, 2.5)), {
            'type': 'tuple',
            'items': [{'type': 'int', 'value': 1}, {'type': 'float', 'value': 2.5}],
        })
        packed_set = question_bank.pack_value({3, 1})
        self.assertEqual(packed_set['type'], 'set')
        self.assertEqual(
            [item['value'] for item in packed_set['items']], [1, 3]
        )

    def test_find_questions_prefers_specific_tags(self):
        matched = [q['code'] for q in question_bank.find_questions('列表切片')]
        self.assertEqual(matched[0], 'Q4-02')
        # 同一弱项每次选题不超过 2 题，且不重复
        self.assertEqual(len(matched), 2)

    def test_find_questions_exclude(self):
        first = question_bank.find_questions('列表切片')
        second = question_bank.find_questions(
            '列表切片', exclude={q['code'] for q in first}
        )
        self.assertTrue(second)
        self.assertFalse({q['code'] for q in second} & {q['code'] for q in first})

    def test_has_matches(self):
        self.assertTrue(question_bank.has_matches([{'name': '列表切片'}]))
        self.assertFalse(question_bank.has_matches([{'name': '量子纠缠纠错'}]))
