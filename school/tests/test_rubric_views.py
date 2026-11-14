"""教师端评分标准视图（rubric_views）的单元测试。"""

import io
import tempfile
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.course_models import CourseworkRubric
from school.models import Classroom, ClassStaff, Coursework, User, UserRole
from school.portal import rubric_agent as rubric_agent_module


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

    def test_get_auto_creates_rule_rubric_when_missing(self):
        """历史作业打开评分标准页时，自动用规则兜底补一份。"""
        from school.course_models import CourseworkItem

        CourseworkItem.objects.create(
            coursework=self.work, function_name='func301', title='合并两个列表', points=100
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertEqual(response.status_code, 200)
        rubric = CourseworkRubric.objects.get(coursework=self.work)
        self.assertEqual(rubric.source, 'rule')
        self.assertContains(response, '规则兜底')
        self.assertContains(response, '考察重点（雷达图维度）')

    def test_get_keeps_existing_rubric(self):
        CourseworkRubric.objects.create(
            coursework=self.work, markdown='# 已生成的标准', source='llm', model='m'
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('work_rubric', args=[self.work.pk]))
        self.assertContains(response, '已生成的标准')
        self.assertContains(response, '大模型生成')
        self.assertEqual(CourseworkRubric.objects.count(), 1)

    def test_page_has_no_generate_buttons(self):
        """生成方式由上传时的勾选决定，页面不再提供生成按钮。"""
        CourseworkRubric.objects.create(coursework=self.work, markdown='# 标准')
        self.client.force_login(self.teacher)
        body = self.client.get(reverse('work_rubric', args=[self.work.pk])).content.decode('utf-8')
        # 没有提交生成方式的表单，也没有生成按钮
        self.assertNotIn('name="mode"', body)
        self.assertNotIn('规则兜底生成（离线演示）</button>', body)
        self.assertNotIn('调用大模型生成</button>', body)

    def test_post_not_allowed(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('work_rubric', args=[self.work.pk]), {})
        self.assertEqual(response.status_code, 405)

    # ---- 上传题目文件时的勾选 ----

    def _package_bytes(self):
        document = io.BytesIO()
        with ZipFile(document, 'w') as archive:
            archive.writestr(
                'word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>第三章</w:t></w:r></w:p></w:body></w:document>',
            )
        package = io.BytesIO()
        with ZipFile(package, 'w') as archive:
            root = '03-列表/'
            archive.writestr(root + '03-列表习题说明.docx', document.getvalue())
            archive.writestr(root + 'sample03.py', 'def func301(a, b):\n    pass\n')
            archive.writestr(root + 'gold.py', 'def func301(a, b):\n    return a + b\n')
            archive.writestr(root + 'func_info_list.txt', 'func301 10 data/func301.txt\n')
            archive.writestr(root + 'data/func301.txt', '1, 2\n')
        return package.getvalue()

    def _upload(self, auto_rubric):
        data = {
            'grading_mode': 'automatic',
            'classroom': self.classroom.pk,
            'deadline': (timezone.now() + timezone.timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
            'revision': 0,
        }
        if auto_rubric:
            data['auto_rubric'] = 'on'
        return self.client.post(
            reverse('work_new'),
            {**data, 'package_file': SimpleUploadedFile('chapter.zip', self._package_bytes())},
        )

    def test_upload_with_checkbox_passes_auto_flag(self):
        self.client.force_login(self.teacher)
        with mock.patch.object(
            rubric_agent_module,
            'prepare_for_upload',
            return_value=('llm', '已调用大模型生成评分标准，可在“评分标准”页面查看。'),
        ) as prepare:
            response = self._upload(True)
        self.assertEqual(response.status_code, 302)
        prepare.assert_called_once()
        work, user, auto = prepare.call_args.args
        self.assertTrue(auto)
        self.assertEqual(work.grading_mode, 'automatic')

    def test_upload_without_checkbox_passes_rule_flag(self):
        self.client.force_login(self.teacher)
        with mock.patch.object(
            rubric_agent_module,
            'prepare_for_upload',
            return_value=('rule', '未勾选大模型生成，已按规则兜底生成评分标准（离线演示）。'),
        ) as prepare:
            self._upload(False)
        prepare.assert_called_once()
        self.assertFalse(prepare.call_args.args[2])

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



