import json
from unittest import mock

from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.course_models import CourseworkRubric
from school.models import (
    Classroom,
    ClassStaff,
    ClassStudent,
    Coursework,
    CourseworkItem,
    User,
    UserRole,
)
from school.portal import rubric_agent, teaching_views


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    LLM_BASE_URL='',
    LLM_API_KEY='',
    LLM_MODEL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class RubricAgentTests(TestCase):
    def setUp(self):
        self.teacher = self._user('teacher', 'teacher')
        self.student = self._user('student', 'student')
        self.classroom = Classroom.objects.create(code='R1', name='题目分析班', term='2026 秋季')
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
            description='实现三个列表相关的函数',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        CourseworkItem.objects.create(
            coursework=self.work,
            function_name='func301',
            title='合并并截取',
            points=10,
            order=1,
        )
        CourseworkItem.objects.create(
            coursework=self.work,
            function_name='func303',
            title='回文判断',
            points=10,
            order=2,
        )

    def _user(self, username, role):
        user = User.objects.create_user(
            username=username,
            full_name=username,
            student_no=username,
            password='Password-2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def test_missing_llm_does_not_fake_result(self):
        with self.assertRaises(rubric_agent.LLMNotConfigured):
            rubric_agent.generate_for(self.work)
        self.assertFalse(CourseworkRubric.objects.filter(coursework=self.work).exists())

    def test_offline_generates_six_dimension_rubric(self):
        rubric = rubric_agent.generate_for(self.work, offline=True)
        self.assertEqual(rubric.source, 'rule')
        self.assertEqual(len(rubric.dimensions), 6)
        total = sum(item['weight'] for item in rubric.dimensions)
        self.assertAlmostEqual(total, 100, places=1)
        self.assertIn('## 一、作业考察的知识点', rubric.markdown)
        self.assertIn('## 二、5 分制量表', rubric.markdown)
        self.assertTrue(rubric.knowledge_points)
        self.assertEqual(CourseworkRubric.objects.filter(coursework=self.work).count(), 1)
        # 雷达图的 6 根轴：规则兜底也必须是 6 个主能力，且各绑定一个不同维度
        self.assertEqual(len(rubric.abilities), 6)
        self.assertEqual(len({item['dimension'] for item in rubric.abilities}), 6)
        self.assertIn('## 三、主能力（雷达图维度）', rubric.markdown)

    # ---- 规则兜底：课程表未收录的题目从参考答案推断知识点 ----

    REFERENCE_CODE = (
        'def func501(n):\n'
        '    total = 0\n'
        '    i = 1\n'
        '    while i <= n:\n'
        '        total = total + i\n'
        '        i = i + 1\n'
        '    return total\n'
    )

    def test_rule_based_infers_points_from_reference_code(self):
        """课程规格表没有的函数，依据参考答案 AST 检测出具体知识点。"""
        context = {
            'title': '循环练习',
            'grading_mode': '机器批阅',
            'items': [{'function': 'func501', 'title': '1~n 累加', 'points': 10}],
        }
        result = rubric_agent.rule_based(context, reference_code=self.REFERENCE_CODE)
        names = {point['name'] for point in result['points']}
        self.assertIn('while 循环', names)
        self.assertIn('函数定义与返回值', names)
        self.assertNotIn('通用程序设计', names)
        point = next(p for p in result['points'] if p['name'] == 'while 循环')
        self.assertEqual(point['tasks'], ['func501'])
        self.assertIn('依据参考答案自动识别', point['detail'])
        self.assertEqual(len(result['abilities']), 6)

    def test_rule_based_falls_back_without_reference(self):
        """没有参考答案可分析时（如非机器批阅），退回通用描述。"""
        context = {
            'title': '循环练习',
            'grading_mode': '机器批阅',
            'items': [{'function': 'func501', 'title': '1~n 累加', 'points': 10}],
        }
        result = rubric_agent.rule_based(context)
        self.assertEqual(
            [point['name'] for point in result['points']], ['通用程序设计']
        )

    def test_parse_filters_unknown_dimensions_and_normalizes_weight(self):
        context = rubric_agent.coursework_context(self.work)
        payload = {
            'knowledge_points': [{'name': '切片', 'detail': '1 起始换算', 'tasks': ['func301']}],
            'dimensions': [
                {'key': 'knowledge', 'weight': 50, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
                {'key': 'syntax', 'weight': 50, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
                {'key': 'boundary', 'weight': 50, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
                {'key': 'logic', 'weight': 50, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
                {'key': 'structure', 'weight': 50, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
                {'key': 'unknown-key', 'weight': 999, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
            ],
        }
        parsed = rubric_agent.parse_response(json.dumps(payload), context)
        keys = [item['key'] for item in parsed['dimensions']]
        self.assertNotIn('unknown-key', keys)
        self.assertEqual(len(keys), 5)
        self.assertAlmostEqual(sum(item['weight'] for item in parsed['dimensions']), 100, places=1)

    def test_teacher_page_and_permission(self):
        rubric_agent.generate_for(self.work, offline=True)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '5 分制量表')
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse('work_rubric', args=[self.work.pk])).status_code, 403
        )

    def test_regenerate_keeps_single_row(self):
        rubric_agent.generate_for(self.work, offline=True)
        rubric_agent.generate_for(self.work, offline=True)
        self.assertEqual(CourseworkRubric.objects.filter(coursework=self.work).count(), 1)

    # ---- 作业保存后自动生成评分标准（teaching_views._auto_generate_rubric）----

    def _request_with_messages(self):
        request = RequestFactory().get('/')
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))
        return request

    _LLM_PAYLOAD = {
        'knowledge_points': [{'name': '切片', 'detail': '1 起始换算', 'tasks': ['func301']}],
        'dimensions': [
            {'key': 'knowledge', 'weight': 30, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
            {'key': 'syntax', 'weight': 20, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
            {'key': 'boundary', 'weight': 15, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
            {'key': 'logic', 'weight': 15, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
            {'key': 'structure', 'weight': 10, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
            {'key': 'readability', 'weight': 10, 'five': 'A', 'four': 'B', 'three': 'C', 'two': 'D', 'one': 'E'},
        ],
    }

    def test_auto_generate_skipped_without_llm_config(self):
        request = self._request_with_messages()
        teaching_views._auto_generate_rubric(request, self.work)
        self.assertFalse(CourseworkRubric.objects.filter(coursework=self.work).exists())
        notes = [m.message for m in get_messages(request)]
        self.assertTrue(any('未配置大模型' in n for n in notes))

    def test_auto_generate_calls_llm_and_saves(self):
        request = self._request_with_messages()
        with mock.patch.object(rubric_agent, 'llm_configured', return_value=True), \
                mock.patch.object(
                    rubric_agent, 'chat', return_value=json.dumps(self._LLM_PAYLOAD)
                ):
            teaching_views._auto_generate_rubric(request, self.work)
        rubric = CourseworkRubric.objects.get(coursework=self.work)
        self.assertEqual(rubric.source, 'llm')
        notes = [m.message for m in get_messages(request)]
        self.assertTrue(any('已自动调用大模型生成评分标准' in n for n in notes))

    def test_auto_generate_keeps_existing_rubric(self):
        rubric_agent.generate_for(self.work, offline=True)
        request = self._request_with_messages()
        with mock.patch.object(rubric_agent, 'llm_configured', return_value=True), \
                mock.patch.object(rubric_agent, 'chat') as chat:
            teaching_views._auto_generate_rubric(request, self.work)
        chat.assert_not_called()
        self.assertEqual(CourseworkRubric.objects.filter(coursework=self.work).count(), 1)

    def test_auto_generate_failure_does_not_raise(self):
        request = self._request_with_messages()
        with mock.patch.object(rubric_agent, 'llm_configured', return_value=True), \
                mock.patch.object(rubric_agent, 'chat', side_effect=rubric_agent.LLMError('超时')):
            teaching_views._auto_generate_rubric(request, self.work)
        self.assertFalse(CourseworkRubric.objects.filter(coursework=self.work).exists())
        notes = [m.message for m in get_messages(request)]
        self.assertTrue(any('自动生成评分标准失败' in n for n in notes))

    # ---- 批阅包更新后后台重建评分标准（rubric_agent.schedule_regeneration）----

    def test_regenerate_job_rule_fallback_without_llm(self):
        rubric_agent._regenerate_coursework_job(self.work.pk)
        rubric = CourseworkRubric.objects.get(coursework=self.work)
        self.assertEqual(rubric.source, 'rule')

    def test_regenerate_job_force_overwrites_existing(self):
        rubric_agent.generate_for(self.work, offline=True)
        with mock.patch.object(rubric_agent, 'llm_configured', return_value=True), \
                mock.patch.object(
                    rubric_agent, 'chat', return_value=json.dumps(self._LLM_PAYLOAD)
                ):
            rubric_agent._regenerate_coursework_job(self.work.pk)
        rubric = CourseworkRubric.objects.get(coursework=self.work)
        self.assertEqual(rubric.source, 'llm')
        self.assertEqual(CourseworkRubric.objects.filter(coursework=self.work).count(), 1)

    def test_regenerate_job_failure_keeps_old_rubric(self):
        rubric_agent.generate_for(self.work, offline=True)
        old_markdown = CourseworkRubric.objects.get(coursework=self.work).markdown
        with mock.patch.object(rubric_agent, 'llm_configured', return_value=True), \
                mock.patch.object(rubric_agent, 'chat', side_effect=rubric_agent.LLMError('超时')):
            rubric_agent._regenerate_coursework_job(self.work.pk)
        rubric = CourseworkRubric.objects.get(coursework=self.work)
        self.assertEqual(rubric.source, 'rule')
        self.assertEqual(rubric.markdown, old_markdown)
