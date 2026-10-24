import io
import json
from unittest.mock import patch
from zipfile import ZipFile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from school.judge import CaseOutcome
from school.models import (
    ClassStudent,
    CourseworkGradeHistory,
    CourseworkPackageUpdate,
    CourseworkSubmission,
    EvaluationPackage,
    User,
    UserRole,
)
from school.portal.grading import validate_package
from school.portal.package_update_services import create_package_update, retry_package_update
from school.portal.parsers import parse_package_archive
from school.storage import save_private

from . import test_review_changes


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class PackageRegressionTests(TestCase):
    setUp = test_review_changes.ReviewChangesTests.setUp
    create_work = test_review_changes.ReviewChangesTests.create_work
    entry = test_review_changes.ReviewChangesTests.entry
    document_bytes = test_review_changes.ReviewChangesTests.document_bytes
    attach_package_archive = test_review_changes.ReviewChangesTests.attach_package_archive

    def test_document_update_cannot_bypass_pending_reference_validation(self):
        self.attach_package_archive()
        self.package.status = 'pending'
        self.package.spec[0].pop('expected')
        self.package.save(update_fields=['status', 'spec'])
        entry = self.entry()
        self.assertEqual(entry.status, 'waiting')
        update = create_package_update(
            self.teacher,
            self.work,
            'chapter/题目.docx',
            SimpleUploadedFile('题目.docx', self.document_bytes('new document')),
        )
        self.assertEqual(update.status, 'pending')
        self.assertEqual(update.package.status, 'pending')
        payload = {'results': [[{'type': 'int', 'value': 2}, {'type': 'int', 'value': 3}]]}
        with patch(
            'school.portal.grading.run_case', return_value=CaseOutcome('WA', 1, json.dumps(payload))
        ):
            self.assertTrue(validate_package(update.package_id))
        entry.refresh_from_db()
        self.work.refresh_from_db()
        self.assertEqual(entry.status, 'pending')
        self.assertTrue(entry.snapshot['ready'])
        self.assertEqual(entry.snapshot['package_id'], self.work.package_id)

    def test_download_avoids_colliding_sanitized_student_folders(self):
        self.student.student_no = 'A/1'
        self.student.full_name = 'Same'
        self.student.save(update_fields=['student_no', 'full_name'])
        self.entry()
        other = User.objects.create_user(username='other', student_no='A?1', full_name='Same')
        UserRole.objects.create(user=other, role='student')
        ClassStudent.objects.create(classroom=self.classroom, student=other)
        CourseworkSubmission.objects.create(
            coursework=self.work,
            student=other,
            sequence=1,
            source_path=save_private('different', '.py'),
            source_hash='different',
            snapshot={},
            status='waiting',
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('work_submissions_download', args=[self.work.pk]))
        with ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            sources = [i for i in archive.infolist() if i.filename.endswith('.py')]
            self.assertEqual(len(sources), 2)
            self.assertEqual(len({i.filename for i in sources}), 2)
            self.assertEqual(
                {archive.read(i) for i in sources}, {b'def func1(x): return x+1', b'different'}
            )

    def test_corrupt_member_is_a_validation_error(self):
        raw = bytearray(self.attach_package_archive())
        offset = raw.index(b'def func1(x): return x + 1')
        raw[offset] = ord('X')  # Preserve ZIP headers but break the member CRC.
        with self.assertRaises(ValidationError):
            parse_package_archive(bytes(raw), 'corrupt.zip')

    def test_cannot_retry_an_old_update_while_a_new_update_is_pending(self):
        self.attach_package_archive()
        first = create_package_update(
            self.teacher,
            self.work,
            'chapter/gold.py',
            SimpleUploadedFile('gold.py', b'def func1(x): return x+2'),
        )
        first.status = 'error'
        first.save(update_fields=['status'])
        second = create_package_update(
            self.teacher,
            self.work,
            'chapter/gold.py',
            SimpleUploadedFile('gold.py', b'def func1(x): return x+3'),
        )
        with self.assertRaises(ValidationError):
            retry_package_update(self.teacher, first)
        self.assertEqual(CourseworkPackageUpdate.objects.get(pk=first.pk).status, 'error')
        self.assertEqual(CourseworkPackageUpdate.objects.get(pk=second.pk).status, 'pending')

    def test_delete_work_after_updates_removes_history_and_all_private_files(self):
        self.attach_package_archive()
        self.entry()
        create_package_update(
            self.teacher,
            self.work,
            'chapter/题目.docx',
            SimpleUploadedFile('题目.docx', self.document_bytes('updated')),
        )
        self.work.refresh_from_db()
        update = create_package_update(
            self.teacher,
            self.work,
            'chapter/gold.py',
            SimpleUploadedFile('gold.py', b'def func1(x): return x+2'),
        )
        payload = {'results': [[{'type': 'int', 'value': 3}, {'type': 'int', 'value': 4}]]}
        with patch(
            'school.portal.grading.run_case',
            return_value=CaseOutcome('WA', 1, json.dumps(payload)),
        ):
            self.assertTrue(validate_package(update.package_id))
        self.assertEqual(CourseworkGradeHistory.objects.count(), 1)
        self.client.force_login(self.teacher)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('work_delete', args=[self.work.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CourseworkPackageUpdate.objects.exists())
        self.assertFalse(CourseworkGradeHistory.objects.exists())
        self.assertFalse(CourseworkSubmission.objects.exists())
        self.assertFalse(EvaluationPackage.objects.exists())
        self.assertEqual([p for p in settings.PRIVATE_STORAGE.rglob('*') if p.is_file()], [])

    def test_archive_blocks_new_package_and_bulk_download_routes(self):
        self.attach_package_archive()
        self.classroom.archived = True
        self.classroom.save(update_fields=['archived'])
        for user in [self.teacher, self.student, self.admin]:
            self.client.force_login(user)
            for route in ['work_package_file', 'work_submissions_download']:
                response = self.client.get(reverse(route, args=[self.work.pk]))
                self.assertIn(response.status_code, [403, 404])
