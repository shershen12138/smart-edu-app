import hashlib
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.course_models import CourseworkSubmission, QualityReport
from school.models import (
    Classroom,
    ClassStaff,
    ClassStudent,
    Coursework,
    CourseworkItem,
    User,
    UserRole,
)
from school.storage import save_private

SOURCE = (
    "def func301(A, B):\n"
    "    C = A + B\n"
    "    return C[7:15]\n"
)

MANUAL_ARCHIVE = b'PK\x03\x04fake'


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class QualityReportTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

        self.teacher = self._user('teacher', 'teacher')
        self.student = self._user('student', 'student')
        self.other = self._user('other', 'student')
        self.classroom = Classroom.objects.create(code='Q1', name='评测班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
            can_export=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        ClassStudent.objects.create(classroom=self.classroom, student=self.other)

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
        CourseworkItem.objects.create(
            coursework=self.work,
            function_name='func301',
            title='合并两列表并取第 8~15 个',
            points=10,
            order=1,
        )
        self.entry = CourseworkSubmission.objects.create(
            coursework=self.work,
            student=self.student,
            sequence=1,
            source_path=save_private(SOURCE, '.py'),
            source_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
            snapshot={'items': [], 'max_score': 10, 'grading_mode': 'automatic'},
            status='done',
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

    def test_student_sees_own_report(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'func301')
        self.assertContains(response, '代码评测报告')
        report = QualityReport.objects.get(submission=self.entry)
        self.assertEqual(report.source_sha256, self.entry.source_hash)
        self.assertTrue(report.payload['tasks'])
        self.assertTrue(report.markdown_key)

    def test_report_is_reused_for_same_source(self):
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        first = QualityReport.objects.get(submission=self.entry)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        second = QualityReport.objects.get(submission=self.entry)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.markdown_key, second.markdown_key)

    def test_other_student_is_forbidden(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_teacher_can_view(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)

    def test_radar_and_markdown_download(self):
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        report = QualityReport.objects.get(submission=self.entry)
        if report.radar_key:
            radar = self.client.get(reverse('quality_radar', args=[self.entry.pk]))
            self.assertEqual(radar.status_code, 200)
            self.assertEqual(radar['Content-Type'], 'image/png')
        download = self.client.get(reverse('quality_markdown', args=[self.entry.pk]))
        self.assertEqual(download.status_code, 200)
        # 读完流并关闭，避免 Windows 上临时文件句柄未释放导致清理失败
        b''.join(download.streaming_content)
        download.close()

    def test_manual_work_has_no_report(self):
        manual = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='人工批阅作业',
            grading_mode='manual',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        entry = CourseworkSubmission.objects.create(
            coursework=manual,
            student=self.student,
            sequence=1,
            source_path=save_private(MANUAL_ARCHIVE, '.zip'),
            source_hash=hashlib.sha256(MANUAL_ARCHIVE).hexdigest(),
            snapshot={'items': [], 'max_score': 10, 'grading_mode': 'manual'},
            status='review',
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[entry.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(QualityReport.objects.filter(submission=entry).exists())
