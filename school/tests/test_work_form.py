"""教师上传题目页：分组表单结构、上传区与编辑态提示。"""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.models import ClassStaff, Classroom, User, UserRole
from school.course_models import Coursework


def _user(username, role):
    user = User.objects.create_user(
        username=username,
        full_name=username,
        student_no=username,
        password='Password-2026!',
        must_change_password=False,
    )
    UserRole.objects.create(user=user, role=role)
    return user


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
)
class WorkFormRenderTests(TestCase):
    def setUp(self):
        self.teacher = _user('teacher', 'teacher')
        self.classroom = Classroom.objects.create(code='C1', name='一班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
        )
        self.client.force_login(self.teacher)

    def test_new_work_page_is_grouped(self):
        response = self.client.get(reverse('work_new'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        for text in (
            '选择批阅方式',
            '时间与教学班',
            '上传题目文件',
            '点击选择 ZIP 文件',
            '上传前检查',
            'ZIP 结构示例',
            '自动调用大模型生成评分标准',
        ):
            self.assertIn(text, body)
        self.assertIn('class="work-form"', body)
        self.assertIn('name="grading_mode"', body)
        self.assertIn('id_package_file', body)
        self.assertIn('id_auto_rubric', body)
        self.assertIn('id_classroom', body)
        self.assertIn('id_deadline', body)

    def test_edit_page_keeps_same_layout(self):
        work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='列表作业',
            description='说明',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=7),
            status='open',
        )
        response = self.client.get(reverse('work_edit', args=[work.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '修改作业')
        self.assertContains(response, 'class="work-form"')
