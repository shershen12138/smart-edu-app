"""教师端评分标准视图（rubric_views）的单元测试。"""

import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.course_models import CourseworkRubric
from school.models import Classroom, ClassStaff, Coursework, User, UserRole


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class RubricViewTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

        self.teacher = self._user('teacher', 'teacher')
        self.other = self._user('other', 'teacher')
        self.classroom = Classroom.objects.create(code='R1', name='评分班', term='2026')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
        )
        self.work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='列表作业',
            description='实现 func301',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
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

    def test_get_renders_status_and_llm_state(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('评分标准', response.content.decode('utf-8'))

    def test_get_forbidden_without_edit(self):
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.other,
            role='teacher',
            can_edit=False,
            can_view_grades=True,
        )
        self.client.force_login(self.other)
        response = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertEqual(response.status_code, 403)

    def test_post_llm_success(self):
        self.client.force_login(self.teacher)
        with mock_generate('ok') as generate:
            response = self.client.post(
                reverse('work_rubric', args=[self.work.pk]), {}
            )
        generate.assert_called_once()
        self.assertRedirects(response, reverse('work_rubric', args=[self.work.pk]))
        # 评分标准已落库
        self.assertTrue(CourseworkRubric.objects.filter(coursework=self.work).exists())
        follow = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertContains(follow, 'ok')

    def test_post_offline_warns(self):
        self.client.force_login(self.teacher)
        with mock_generate('ok') as generate:
            self.client.post(reverse('work_rubric', args=[self.work.pk]), {'mode': 'offline'})
        generate.assert_called_once()
        follow = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertContains(follow, '规则兜底')

    def test_post_llm_not_configured_shows_error(self):
        from school.portal import rubric_agent

        self.client.force_login(self.teacher)
        with mock.patch.object(
            rubric_agent,
            'generate_for',
            side_effect=rubric_agent.LLMNotConfigured('未配置大模型端点'),
        ):
            response = self.client.post(reverse('work_rubric', args=[self.work.pk]), {})
        self.assertRedirects(response, reverse('work_rubric', args=[self.work.pk]))
        follow = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertContains(follow, '未配置大模型端点')

    def test_post_parse_error_shows_error(self):
        from school.portal import rubric_agent

        self.client.force_login(self.teacher)
        with mock.patch.object(
            rubric_agent,
            'generate_for',
            side_effect=rubric_agent.RubricParseError('解析失败'),
        ):
            self.client.post(reverse('work_rubric', args=[self.work.pk]), {})
        follow = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertContains(follow, '生成失败：解析失败')

    def test_download_returns_markdown_attachment(self):
        CourseworkRubric.objects.create(
            coursework=self.work, markdown='# 评分标准\n| 维度 | 权重 |\n'
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('work_rubric_download', args=[self.work.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/markdown; charset=utf-8')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_download_without_rubric_forbidden(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('work_rubric_download', args=[self.work.pk]))
        self.assertEqual(response.status_code, 403)


def mock_generate(markdown):
    """把 rubric_agent.generate_for mock 成生成指定 markdown 的评分标准。"""
    from school.course_models import CourseworkRubric
    from school.portal import rubric_agent

    def fake_generate(work, offline=False):
        CourseworkRubric.objects.update_or_create(
            coursework=work, defaults={'markdown': markdown}
        )
        return CourseworkRubric.objects.get(coursework=work)

    class _Ctx:
        def __init__(self):
            self.patcher = mock.patch.object(rubric_agent, 'generate_for', side_effect=fake_generate)

        def __enter__(self):
            self.mock = self.patcher.start()
            return self.mock

        def __exit__(self, *args):
            self.patcher.stop()
            return False

    return _Ctx()
