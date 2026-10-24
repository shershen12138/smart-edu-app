import json

from django.test import TestCase, override_settings
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
from school.portal import rubric_agent


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
