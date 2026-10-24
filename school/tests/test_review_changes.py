import io
import json
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.cleanup import drain_file_cleanup, queue_file_cleanup
from school.judge import CaseOutcome
from school.models import (
    Classroom,
    ClassStudent,
    Coursework,
    CourseworkCaseResult,
    CourseworkGradeHistory,
    CourseworkPackageUpdate,
    CourseworkSubmission,
    EvaluationPackage,
    PrivateFileCleanup,
    User,
    UserRole,
)
from school.portal.account_services import save_person
from school.portal.admin_forms import GrantForm, PersonForm
from school.portal.grading import evaluate, recover_stale, validate_package
from school.portal.reporting_services import roster_rows
from school.portal.rosters import students_in, with_student_counts
from school.storage import read_private_bytes, save_private

from . import test_portal


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    STORE_RECOVERY_PASSWORDS=True,
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ReviewChangesTests(TestCase):
    setUp = test_portal.PortalTests.setUp
    entry = test_portal.PortalTests.entry
    create_work = test_portal.PortalTests.create_work
    get_as = test_portal.PortalTests.get_as

    def document_bytes(self, text='单文件更新测试'):
        document = io.BytesIO()
        with ZipFile(document, 'w') as archive:
            archive.writestr(
                'word/document.xml',
                f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
            )
        return document.getvalue()

    def attach_package_archive(self):
        package = io.BytesIO()
        with ZipFile(package, 'w') as archive:
            root = 'chapter/'
            archive.writestr(root + '题目.docx', self.document_bytes())
            archive.writestr(root + 'sample.py', 'def func1(x):\n    pass\n')
            archive.writestr(root + 'gold.py', 'def func1(x): return x + 1')
            archive.writestr(root + 'func_info_list.txt', 'func1 10 data/func1.txt\n')
            archive.writestr(root + 'data/func1.txt', '1\n2\n')
        self.package.archive_path = save_private(package.getvalue(), '.zip')
        self.package.save(update_fields=['archive_path'])
        return package.getvalue()

    def test_delete_work_removes_graph_and_files_but_preserves_shared_package(self):
        other = self.create_work()
        entry = self.entry()
        CourseworkCaseResult.objects.create(question=entry.questions.get(), order=1, verdict='AC')
        paths = [self.work.document_path, entry.source_path]
        reference = self.package.reference_path
        self.client.force_login(self.teacher)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('work_delete', args=[self.work.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CourseworkSubmission.objects.filter(pk=entry.pk).exists())
        self.assertFalse(CourseworkCaseResult.objects.exists())
        for path in paths:
            self.assertFalse((settings.PRIVATE_STORAGE / path).exists())
        self.assertTrue(EvaluationPackage.objects.filter(pk=self.package.pk).exists())
        self.assertTrue((settings.PRIVATE_STORAGE / reference).exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('work_delete', args=[other.pk]))
        self.assertFalse(EvaluationPackage.objects.filter(pk=self.package.pk).exists())
        self.assertFalse((settings.PRIVATE_STORAGE / reference).exists())

    def test_delete_class_removes_content_but_keeps_accounts_and_other_classes(self):
        self.entry()
        other = Classroom.objects.create(code='C2', name='另一个班', term='2026')
        ClassStudent.objects.create(classroom=other, student=self.student)
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('class_delete', args=[self.classroom.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Classroom.objects.filter(pk=self.classroom.pk).exists())
        self.assertFalse(Coursework.objects.exists())
        self.assertFalse(CourseworkSubmission.objects.exists())
        self.assertTrue(self.student.memberships.filter(classroom=other).exists())
        self.assertEqual(User.objects.count(), 3)

    def test_delete_student_removes_submission_file_not_teacher_work(self):
        entry = self.entry()
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('person_delete', args=['student', self.student.pk]))
        self.assertFalse(CourseworkSubmission.objects.exists())
        self.assertFalse((settings.PRIVATE_STORAGE / entry.source_path).exists())
        self.assertTrue(Coursework.objects.filter(pk=self.work.pk).exists())

    def test_rollback_keeps_database_and_files(self):
        entry = self.entry()
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    Coursework.objects.filter(pk=self.work.pk).delete()
                    raise ValueError('rollback')
            except ValueError:
                pass
        self.assertTrue(CourseworkSubmission.objects.filter(pk=entry.pk).exists())
        self.assertTrue((settings.PRIVATE_STORAGE / entry.source_path).exists())
        self.assertFalse(PrivateFileCleanup.objects.exists())

    def test_file_cleanup_failure_retries_and_never_removes_shared_file(self):
        key = save_private('orphan')
        with (
            patch.object(Path, 'unlink', side_effect=OSError('busy')),
            self.captureOnCommitCallbacks(execute=True),
        ):
            queue_file_cleanup([key, self.work.document_path])
        self.assertTrue(PrivateFileCleanup.objects.filter(path=key).exists())
        self.assertTrue((settings.PRIVATE_STORAGE / self.work.document_path).exists())
        drain_file_cleanup()
        self.assertFalse((settings.PRIVATE_STORAGE / key).exists())
        self.assertFalse(PrivateFileCleanup.objects.exists())

    def test_archive_hides_all_role_routes_and_restore_returns_same_records(self):
        entry = self.entry()
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(
                reverse('archives'), {'classroom': self.classroom.pk, 'archived': 'on'}
            ).status_code,
            302,
        )
        for user in (self.admin, self.teacher, self.student):
            for route in (
                reverse('work', args=[self.work.pk]),
                reverse('entry', args=[entry.pk]),
                reverse('entry_source', args=[entry.pk]),
                reverse('work_file', args=[self.work.pk, 'document']),
            ):
                self.assertEqual(self.get_as(user, route).status_code, 404)
            self.assertNotContains(self.get_as(user, reverse('classes')), self.classroom.name)
        self.assertEqual(self.get_as(self.teacher, reverse('archives')).status_code, 403)
        self.assertEqual(self.get_as(self.student, reverse('archives')).status_code, 403)
        self.assertNotContains(
            self.get_as(self.admin, reverse('students')), '<td>student</td>', html=True
        )
        self.assertEqual(
            self.client.get(reverse('class_edit', args=[self.classroom.pk])).status_code, 404
        )
        self.assertContains(self.client.get(reverse('archives')), self.classroom.code)
        self.client.post(reverse('archives'), {'classroom': self.classroom.pk})
        self.assertEqual(
            self.get_as(self.student, reverse('entry', args=[entry.pk])).status_code, 200
        )
        self.assertTrue(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=self.student, active=True
            ).exists()
        )

    def test_edit_student_does_not_remove_archived_membership(self):
        archived = Classroom.objects.create(code='OLD', name='旧班', term='2025', archived=True)
        ClassStudent.objects.create(classroom=archived, student=self.student)
        form = PersonForm(
            {
                'username': 'student',
                'full_name': '改名',
                'student_no': 'student',
                'is_active': True,
                'classrooms': [self.classroom.pk],
            },
            instance=self.student,
            kind='student',
        )
        self.assertTrue(form.is_valid(), form.errors)
        save_person(self.admin, form, 'student')
        self.assertTrue(ClassStudent.objects.get(classroom=archived, student=self.student).active)

    def test_ninety_two_members_match_list_report_and_class_count(self):
        for i in range(91):
            user = User.objects.create_user(
                username=f'n{i:03}',
                student_no=f'n{i:03}',
                full_name=f'学生{i}',
                must_change_password=False,
            )
            UserRole.objects.create(user=user, role='student')
            ClassStudent.objects.create(classroom=self.classroom, student=user)
        # A legacy invalid teacher membership must not add a 93rd student.
        ClassStudent.objects.create(classroom=self.classroom, student=self.teacher)
        self.assertEqual(students_in(self.classroom).count(), 92)
        self.assertEqual(with_student_counts(Classroom.objects.all()).get().student_count, 92)
        rows, stats = roster_rows(self.work)
        self.assertEqual(len(rows), 92)
        self.assertEqual(stats[0][1], 92)
        response = self.get_as(
            self.admin, reverse('students') + f'?classroom={self.classroom.pk}&page=4&per_page=30'
        )
        self.assertEqual(response.context['page'].paginator.count, 92)
        self.assertEqual(len(response.context['page']), 2)
        self.assertContains(response, '<td>92</td>', html=True)
        self.assertContains(response, '跳至')
        self.assertContains(response, '每页 30 人')
        self.assertContains(self.client.get(reverse('classes')), '<td>92</td>', html=True)

    def test_import_success_redirects_to_class_and_repeat_does_not_inflate(self):
        self.client.force_login(self.admin)
        raw = b'username,full_name,student_no,class_code\nnew,New,N1,C1\n'
        for count in (1, 0):
            self.client.post(
                reverse('students_import'), {'file': SimpleUploadedFile('roster.csv', raw)}
            )
            response = self.client.post(reverse('students_import'), {'confirm': 'yes'}, follow=True)
            self.assertContains(response, f'新增账号 {count} 个')
            self.assertEqual(
                response.redirect_chain[0][0],
                reverse('students') + f'?classroom={self.classroom.pk}',
            )
            self.assertEqual(students_in(self.classroom).count(), 2)

    def test_grant_labels_and_admin_roster_actions(self):
        labels = str(GrantForm()['classroom'])
        for part in ('C1', '一班', '2026 秋季'):
            self.assertIn(part, labels)
        response = self.get_as(self.admin, reverse('class_detail', args=[self.classroom.pk]))
        self.assertNotContains(response, '本班作业')
        self.assertNotContains(response, '查看学生结果')
        for name, args in [
            ('works', []),
            ('work_new', []),
            ('work_edit', [self.work.pk]),
            ('work_delete', [self.work.pk]),
        ]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        response = self.get_as(self.teacher, reverse('class_detail', args=[self.classroom.pk]))
        self.assertContains(response, '本班作业')

    def test_teacher_sees_expected_actual_student_html_does_not(self):
        entry = self.entry()
        entry.snapshot['items'][0]['expected'] = [
            {'type': 'str', 'value': 'EXPECTED_SECRET'},
            {'type': 'str', 'value': 'SECOND_SECRET'},
        ]
        entry.save(update_fields=['snapshot'])
        payload = {
            'results': [
                [
                    {
                        'verdict': 'OK',
                        'elapsed_ms': 1,
                        'value': {'type': 'str', 'value': '<script>ACTUAL_SECRET</script>'},
                    },
                    {'verdict': 'RE', 'elapsed_ms': 2},
                ]
            ]
        }
        with patch(
            'school.portal.grading.run_case', return_value=CaseOutcome('WA', 3, json.dumps(payload))
        ):
            evaluate(entry.pk)
        teacher = self.get_as(self.teacher, reverse('entry', args=[entry.pk]))
        self.assertContains(teacher, 'EXPECTED_SECRET')
        self.assertContains(teacher, 'ACTUAL_SECRET')
        self.assertNotContains(teacher, '<script>ACTUAL_SECRET</script>')
        student = self.get_as(self.student, reverse('entry', args=[entry.pk]))
        for text in ('EXPECTED_SECRET', 'ACTUAL_SECRET', '期望结果', '实际结果'):
            self.assertNotContains(student, text)

    def test_manual_download_latest_and_permissions(self):
        self.work.grading_mode = 'manual'
        self.work.save(update_fields=['grading_mode'])
        for seq in (1, 2):
            buffer = io.BytesIO()
            with ZipFile(buffer, 'w') as archive:
                for number in range(1001, 1006):
                    archive.writestr(f'10答案/{number}.py', f'print({seq}, {number})')
            raw = buffer.getvalue()
            CourseworkSubmission.objects.create(
                coursework=self.work,
                student=self.student,
                sequence=seq,
                source_path=save_private(raw, '.zip'),
                source_hash=str(seq),
                snapshot={'required_files': [f'{number}.py' for number in range(1001, 1006)]},
                status='review',
            )
        url = reverse('work_submissions_download', args=[self.work.pk])
        response = self.get_as(self.teacher, url)
        with ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            names = archive.namelist()
            self.assertFalse(any('第1次' in name for name in names))
            self.assertFalse(any(name.endswith('.zip') for name in names))
            directory = f'{self.student.student_no}_{self.student.full_name}_第2次/'
            self.assertEqual(
                [name for name in names if name.startswith(directory)],
                [f'{directory}{number}.py' for number in range(1001, 1006)],
            )
            self.assertEqual(archive.read(f'{directory}1001.py'), b'print(2, 1001)')
            self.assertFalse(any('10答案' in name for name in names))
            self.assertIn('打包结果.csv', names)
        self.assertEqual(self.get_as(self.student, url).status_code, 403)
        self.grant.can_export = False
        self.grant.save()
        self.assertEqual(self.get_as(self.teacher, url).status_code, 403)

    def test_automatic_download_includes_latest_python_source(self):
        first = self.entry()
        first.status = 'done'
        first.save(update_fields=['status'])
        second = self.entry()
        url = reverse('work_submissions_download', args=[self.work.pk])

        response = self.get_as(self.teacher, url)

        with ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            names = archive.namelist()
            directory = f'{self.student.student_no}_{self.student.full_name}_第2次/'
            member = f'{directory}{self.student.student_no}.py'
            self.assertIn(member, names)
            self.assertEqual(archive.read(member), b'def func1(x): return x+1')
            self.assertNotIn(first.source_path, names)
            self.assertNotIn(second.source_path, names)
            self.assertIn('打包结果.csv', names)

    def test_manual_download_reports_invalid_student_zip(self):
        self.work.grading_mode = 'manual'
        self.work.save(update_fields=['grading_mode'])
        CourseworkSubmission.objects.create(
            coursework=self.work,
            student=self.student,
            sequence=1,
            source_path=save_private(b'not a zip', '.zip'),
            source_hash='broken',
            snapshot={'required_files': [f'{number}.py' for number in range(1001, 1006)]},
            status='review',
        )

        response = self.get_as(
            self.teacher, reverse('work_submissions_download', args=[self.work.pk])
        )

        with ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            names = archive.namelist()
            self.assertEqual(names, ['打包结果.csv', '下载说明.txt'])
            report = archive.read('打包结果.csv').decode('utf-8-sig')
            self.assertIn('答案ZIP损坏或结构无效', report)

    def test_document_update_activates_without_regrading_and_button_is_on_edit_page(self):
        self.assertNotContains(
            self.get_as(self.teacher, reverse('work', args=[self.work.pk])), '更新单个文件'
        )
        self.attach_package_archive()
        old_package_id = self.work.package_id
        detail = self.get_as(self.teacher, reverse('work', args=[self.work.pk]))
        self.assertNotContains(detail, '更新单个文件')
        self.assertContains(
            self.get_as(self.teacher, reverse('work_edit', args=[self.work.pk])),
            '更新单个文件',
        )
        self.assertEqual(
            self.get_as(self.student, reverse('work_package_file', args=[self.work.pk])).status_code,
            403,
        )
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse('work_package_file', args=[self.work.pk]),
            {
                'package_member': 'chapter/题目.docx',
                'replacement_file': SimpleUploadedFile(
                    '题目.docx', self.document_bytes('更新后的题目说明')
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.work.refresh_from_db()
        update = CourseworkPackageUpdate.objects.get(coursework=self.work)
        self.assertEqual(update.status, 'activated')
        self.assertFalse(update.grading_changed)
        self.assertNotEqual(self.work.package_id, old_package_id)
        self.assertFalse(CourseworkGradeHistory.objects.exists())

    def test_sample_update_requires_validation_and_regrades_existing_submission(self):
        self.attach_package_archive()
        entry = self.entry()
        entry.status = 'done'
        entry.total = 10
        entry.save(update_fields=['status', 'total'])
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('work_package_file', args=[self.work.pk]),
            {
                'package_member': 'chapter/sample.py',
                'replacement_file': SimpleUploadedFile(
                    'sample.py', b'def func1(x):\n    return 0\n'
                ),
            },
        )
        update = CourseworkPackageUpdate.objects.get(coursework=self.work)
        self.assertEqual(update.status, 'pending')
        self.assertTrue(update.grading_changed)
        payload = (
            '{"results":[['
            '{"type":"int","value":2},{"type":"int","value":3}'
            ']]}'
        )
        with patch(
            'school.portal.grading.run_case', return_value=CaseOutcome('WA', 1, payload)
        ):
            self.assertTrue(validate_package(update.package_id))
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'pending')
        self.assertTrue(CourseworkGradeHistory.objects.filter(submission=entry).exists())

    def test_manual_material_single_file_update_skips_docker_and_preserves_grades(self):
        materials = io.BytesIO()
        with ZipFile(materials, 'w') as archive:
            archive.writestr('chapter10/题目.docx', self.document_bytes('人工批阅题目'))
            archive.writestr('chapter10/data.txt', '旧数据')
        old_materials = save_private(materials.getvalue(), '.zip')
        self.work.grading_mode = 'manual'
        self.work.package = None
        self.work.materials_path = old_materials
        self.work.materials_name = 'chapter10.zip'
        self.work.save(update_fields=['grading_mode', 'package', 'materials_path', 'materials_name'])
        entry = CourseworkSubmission.objects.create(
            coursework=self.work,
            student=self.student,
            sequence=1,
            source_path=save_private(b'answer', '.zip'),
            source_hash='manual',
            snapshot={},
            status='done',
            total=50,
        )
        self.assertNotContains(
            self.get_as(self.teacher, reverse('work', args=[self.work.pk])), '更新单个文件'
        )
        self.assertContains(
            self.get_as(self.teacher, reverse('work_edit', args=[self.work.pk])),
            '更新单个文件',
        )
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse('work_package_file', args=[self.work.pk]),
            {
                'package_member': 'chapter10/data.txt',
                'replacement_file': SimpleUploadedFile('data.txt', '新数据'.encode()),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.work.refresh_from_db()
        entry.refresh_from_db()
        update = CourseworkPackageUpdate.objects.get(coursework=self.work)
        self.assertEqual(update.status, 'activated')
        self.assertFalse(update.grading_changed)
        self.assertIsNone(update.package_id)
        self.assertEqual(update.previous_materials_path, old_materials)
        self.assertEqual(entry.status, 'done')
        self.assertEqual(entry.total, 50)
        self.assertFalse(CourseworkGradeHistory.objects.exists())
        with ZipFile(io.BytesIO(read_private_bytes(self.work.materials_path))) as archive:
            self.assertEqual(archive.read('chapter10/data.txt'), '新数据'.encode())

    def test_scoring_file_update_keeps_old_grade_until_validation_then_requeues(self):
        self.attach_package_archive()
        entry = self.entry()
        entry.status = 'done'
        entry.total = 10
        entry.save(update_fields=['status', 'total'])
        question = entry.questions.get()
        question.score = 10
        question.verdict = 'AC'
        question.save(update_fields=['score', 'verdict'])
        old_package_id = self.work.package_id
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse('work_package_file', args=[self.work.pk]),
            {
                'package_member': 'chapter/data/func1.txt',
                'replacement_file': SimpleUploadedFile('func1.txt', b'2\n'),
            },
        )

        self.assertEqual(response.status_code, 302)
        update = CourseworkPackageUpdate.objects.get(coursework=self.work)
        self.assertEqual(update.status, 'pending')
        self.assertTrue(update.grading_changed)
        self.work.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(self.work.package_id, old_package_id)
        self.assertEqual(entry.status, 'done')
        self.assertEqual(entry.total, 10)

        payload = '{"results":[[{"type":"int","value":3}]]}'
        with patch(
            'school.portal.grading.run_case', return_value=CaseOutcome('WA', 1, payload)
        ):
            self.assertTrue(validate_package(update.package_id))

        self.work.refresh_from_db()
        entry.refresh_from_db()
        update.refresh_from_db()
        self.assertEqual(update.status, 'activated')
        self.assertNotEqual(self.work.package_id, old_package_id)
        self.assertEqual(entry.status, 'pending')
        self.assertIsNone(entry.total)
        history = CourseworkGradeHistory.objects.get(submission=entry)
        self.assertEqual(history.total, 10)
        self.assertEqual(history.results[0]['score'], '10.0000')
        self.assertEqual(entry.snapshot['items'][0]['inputs'], ['2'])
        work_page = self.get_as(self.teacher, reverse('work', args=[self.work.pk]))
        self.assertContains(work_page, '重评进度')
        self.assertContains(work_page, '成功 0 / 1，剩余 1，失败 0')
        self.assertContains(
            self.get_as(self.teacher, reverse('work_results', args=[self.work.pk])),
            '重评进度',
        )
        self.assertContains(self.get_as(self.teacher, reverse('entry', args=[entry.pk])), '重评前的历史成绩')
        self.assertNotContains(
            self.get_as(self.student, reverse('entry', args=[entry.pk])), '重评前的历史成绩'
        )

        grade_payload = {
            'results': [
                [
                    {
                        'verdict': 'OK',
                        'elapsed_ms': 1,
                        'value': {'type': 'int', 'value': 3},
                    }
                ]
            ]
        }
        with patch(
            'school.portal.grading.run_case',
            return_value=CaseOutcome('WA', 1, json.dumps(grade_payload)),
        ):
            evaluate(entry.pk)
        completed_page = self.get_as(self.teacher, reverse('work', args=[self.work.pk]))
        self.assertNotContains(completed_page, '重评进度')
        self.assertContains(completed_page, '版本更新记录')
        self.assertContains(completed_page, '重评完成：1/1')
        self.assertNotContains(
            self.get_as(self.teacher, reverse('work_results', args=[self.work.pk])),
            '重评进度',
        )

    def test_failed_package_update_keeps_current_package_and_can_retry(self):
        self.attach_package_archive()
        old_package_id = self.work.package_id
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('work_package_file', args=[self.work.pk]),
            {
                'package_member': 'chapter/gold.py',
                'replacement_file': SimpleUploadedFile(
                    'gold.py', b'def func1(x):\n    raise ValueError()\n'
                ),
            },
        )
        update = CourseworkPackageUpdate.objects.get(coursework=self.work)
        payload = '{"results":[],"error":{"function":"func1","order":1,"kind":"ValueError"}}'
        with patch(
            'school.portal.grading.run_case', return_value=CaseOutcome('WA', 1, payload)
        ):
            self.assertFalse(validate_package(update.package_id))

        self.work.refresh_from_db()
        update.refresh_from_db()
        self.assertEqual(self.work.package_id, old_package_id)
        self.assertEqual(update.status, 'error')
        self.assertIn('ValueError', update.error)
        response = self.client.post(reverse('work_package_retry', args=[self.work.pk]))
        self.assertEqual(response.status_code, 302)
        update.refresh_from_db()
        self.assertEqual(update.status, 'pending')

    def test_worker_recovers_ready_package_update_after_interruption(self):
        self.attach_package_archive()
        old_package_id = self.work.package_id
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('work_package_file', args=[self.work.pk]),
            {
                'package_member': 'chapter/data/func1.txt',
                'replacement_file': SimpleUploadedFile('func1.txt', b'3\n'),
            },
        )
        update = CourseworkPackageUpdate.objects.get(coursework=self.work)
        spec = update.package.spec
        spec[0]['expected'] = [{'type': 'int', 'value': 4}]
        update.package.spec = spec
        update.package.status = 'ready'
        update.package.save(update_fields=['spec', 'status'])

        recover_stale()

        self.work.refresh_from_db()
        update.refresh_from_db()
        self.assertEqual(update.status, 'activated')
        self.assertNotEqual(self.work.package_id, old_package_id)

    def test_purge_legacy_deleted_rows_but_preserves_archived_and_shared(self):
        self.work.deleted_at = timezone.now()
        self.work.save()
        archived = Classroom.objects.create(code='ARCH', name='归档班', term='2025', archived=True)
        orphan = save_private('old-file')
        with self.captureOnCommitCallbacks(execute=True):
            call_command('purge_deleted_data', '--apply', '--offline', stdout=io.StringIO())
        self.assertFalse(Coursework.objects.filter(pk=self.work.pk).exists())
        self.assertTrue(Classroom.objects.filter(pk=archived.pk).exists())
        self.assertFalse((settings.PRIVATE_STORAGE / orphan).exists())
