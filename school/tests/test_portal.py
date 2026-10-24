import hashlib
import io
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.judge import CaseOutcome, InfrastructureError
from school.models import (
    Classroom,
    ClassStaff,
    ClassStudent,
    Coursework,
    CourseworkItem,
    CourseworkSubmission,
    DataDictionary,
    DictionaryItem,
    EvaluationPackage,
    User,
    UserRole,
)
from school.portal.forms import SubmitForm, WorkForm
from school.portal.grading import (
    batch_harness,
    evaluate,
    grade_submission,
    harness,
    validate_package,
    values_equal,
)
from school.portal.parsers import document_text, parse_package_archive
from school.portal.services import roster_rows, save_work, submit
from school.storage import read_private, save_private


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    STORE_RECOVERY_PASSWORDS=True,
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class PortalTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)
        self.users = {}
        for role in ('admin', 'teacher', 'student'):
            u = User.objects.create_user(
                username=role,
                full_name=role,
                student_no=role,
                password='Password-2026!',
                must_change_password=False,
            )
            UserRole.objects.create(user=u, role=role)
            self.users[role] = u
        self.admin, self.teacher, self.student = [
            self.users[r] for r in ('admin', 'teacher', 'student')
        ]
        self.classroom = Classroom.objects.create(code='C1', name='一班', term='2026 秋季')
        self.grant = ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
            can_export=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.text = b'Write function func1(x), return x + 1.'
        self.package = EvaluationPackage.objects.create(
            code='test-package',
            name='函数作业',
            document_digest=hashlib.sha256(self.text).hexdigest(),
            digest='test',
            description=self.text.decode(),
            reference_path=save_private('def func1(x): return x + 1', '.py'),
            status='ready',
            spec=[
                {
                    'function': 'func1',
                    'points': 10,
                    'argc': 1,
                    'inputs': ['1', '2'],
                    'expected': [
                        {'type': 'int', 'value': 2},
                        {'type': 'int', 'value': 3},
                    ],
                }
            ],
        )
        self.work = self.create_work()

    def create_work(self, text=None):
        content = text or self.text
        package = self.package if content == self.text else None
        work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='第一次作业',
            description=content.decode(),
            document_path=save_private(content, '.txt'),
            document_name='第一次作业.txt',
            grading_mode='automatic',
            package=package,
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        if package:
            CourseworkItem.objects.create(
                coursework=work, function_name='func1', title='func1', points=10, order=1
            )
        return work

    def entry(self, user=None, work=None, request_id=None):
        return submit(
            user or self.student,
            (work or self.work).pk,
            {'source': 'def func1(x): return x+1', 'request_id': request_id or uuid.uuid4()},
        )

    def get_as(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_role_navigation_and_no_legacy_workflow(self):
        for user, expected, absent in [
            (self.admin, '教师用户与授权', '我的作业看板'),
            (self.teacher, '教学仪表盘', '教学班名单管理'),
            (self.student, '我的作业看板', '教师用户与授权'),
        ]:
            response = self.get_as(user, '/')
            self.assertContains(response, expected)
            self.assertNotContains(response, absent)
            self.assertNotContains(response, '助教')
            self.assertNotContains(response, '成绩发布')
        self.assertEqual(self.client.get('/extensions/').status_code, 404)

    def test_work_management_shows_grading_mode(self):
        response = self.get_as(self.teacher, reverse('works'))
        self.assertContains(response, '批阅方式')
        self.assertContains(response, '机器批阅')

        self.work.grading_mode = 'manual'
        self.work.save(update_fields=['grading_mode'])
        response = self.get_as(self.teacher, reverse('works'))
        self.assertContains(response, '非机器批阅')

    def test_student_dashboard_stat_cards_filter_assignments(self):
        self.work.title = '已提交作业'
        self.work.save(update_fields=['title'])
        self.entry()
        pending = self.create_work(text=b'Pending exercise')
        pending.title = '待完成作业'
        pending.grading_mode = 'manual'
        pending.save(update_fields=['title', 'grading_mode'])

        response = self.get_as(self.student, f"{reverse('dashboard')}?filter=submitted")
        self.assertContains(response, '已提交作业')
        self.assertNotContains(response, '待完成作业')
        self.assertContains(response, '机器批阅')
        self.assertContains(response, 'aria-current="true"', html=False)

        response = self.get_as(self.student, f"{reverse('dashboard')}?filter=pending")
        self.assertContains(response, '待完成作业')
        self.assertNotContains(response, '已提交作业')
        self.assertContains(response, '非机器批阅')
        self.assertContains(response, '未截止且未提交的作业')

        response = self.get_as(self.student, f"{reverse('dashboard')}?filter=classrooms")
        self.assertContains(response, '一班')
        self.assertContains(response, '班级编号 C1')
        self.assertContains(response, 'Python 程序设计')
        self.assertNotContains(response, '已提交作业')
        self.assertNotContains(response, '待完成作业')

    def test_student_dashboard_paginates_six_cards_per_page(self):
        for number in range(7):
            work = self.create_work(text=f'Exercise {number}'.encode())
            work.title = f'分页作业 {number}'
            work.save(update_fields=['title'])

        response = self.get_as(self.student, f"{reverse('dashboard')}?filter=all")
        self.assertEqual(len(response.context['card_page']), 6)
        self.assertEqual(response.context['card_page'].paginator.num_pages, 2)
        self.assertContains(response, '下一页')

        response = self.get_as(self.student, f"{reverse('dashboard')}?filter=all&page=2")
        self.assertEqual(len(response.context['card_page']), 2)
        self.assertContains(response, '上一页')

    def test_teacher_dashboard_filters_cards_and_paginates(self):
        self.work.title = '待批阅作业'
        self.work.save(update_fields=['title'])
        self.entry()

        error_work = self.create_work(text=b'Error exercise')
        error_work.title = '异常作业'
        error_work.save(update_fields=['title'])
        error_entry = self.entry(work=error_work)
        CourseworkSubmission.objects.filter(pk=error_entry.pk).update(status='error')

        response = self.get_as(self.teacher, f"{reverse('dashboard')}?filter=pending")
        self.assertContains(response, '待批阅作业')
        self.assertNotContains(response, '异常作业')
        self.assertContains(response, '机器批阅')

        response = self.get_as(self.teacher, f"{reverse('dashboard')}?filter=errors")
        self.assertContains(response, '异常作业')
        self.assertNotContains(response, '待批阅作业')

        response = self.get_as(self.teacher, f"{reverse('dashboard')}?filter=classrooms")
        self.assertContains(response, '一班')
        self.assertContains(response, '班级编号 C1')
        self.assertNotContains(response, '异常作业')

        manual_work = self.create_work(text=b'Manual exercise')
        manual_work.grading_mode = 'manual'
        manual_work.title = '非机器批阅作业'
        manual_work.save(update_fields=['grading_mode', 'title'])
        for number in range(5):
            self.create_work(text=f'Teacher page {number}'.encode())
        response = self.get_as(self.teacher, f"{reverse('dashboard')}?filter=all")
        self.assertEqual(len(response.context['card_page']), 6)
        self.assertEqual(response.context['card_page'].paginator.num_pages, 2)
        self.assertContains(response, '非机器批阅')
        self.assertContains(response, '下一页')

    def test_forced_password_change_blocks_business_pages_and_records_new_password(self):
        self.student.set_password('123456')
        self.student.must_change_password = True
        self.student.save()
        self.assertTrue(self.client.login(username='student', password='123456'))
        self.assertRedirects(self.client.get('/'), '/password/', fetch_redirect_response=False)
        self.assertRedirects(
            self.client.post(reverse('work', args=[self.work.pk])),
            '/password/',
            fetch_redirect_response=False,
        )
        response = self.client.post(
            '/password/',
            {
                'old_password': '123456',
                'new_password1': 'New-Secure-2026!',
                'new_password2': 'New-Secure-2026!',
            },
        )
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertFalse(self.student.must_change_password)
        self.assertTrue(self.student.check_password('New-Secure-2026!'))
        self.assertEqual(self.student.recovery_password, 'New-Secure-2026!')

    def test_default_accounts_reset_disables_old_accounts_and_forces_all_three(self):
        call_command('reset_local_accounts', confirm_reset=True, stdout=io.StringIO())
        users = User.objects.filter(deleted_at__isnull=True)
        self.assertEqual(
            set(users.values_list('username', flat=True)), {'admin', 'teacher', 'student'}
        )
        for user in users:
            self.assertTrue(user.check_password('123456'))
            self.assertTrue(user.must_change_password)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_active)

    def test_recovery_password_admin_only_and_not_in_lists(self):
        url = reverse('person_edit', args=['student', self.student.pk])
        self.assertEqual(self.get_as(self.teacher, url).status_code, 403)
        self.assertEqual(self.get_as(self.student, url).status_code, 403)
        response = self.get_as(self.admin, url)
        self.assertContains(response, 'Password-2026!')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertNotContains(self.client.get('/students/'), 'Password-2026!')
        with override_settings(STORE_RECOVERY_PASSWORDS=False):
            self.assertNotContains(self.client.get(url), 'Password-2026!')

    def test_admin_creates_default_student_and_can_edit_and_delete(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('person_new', args=['student']),
            {
                'username': 's2',
                'full_name': '学生二',
                'student_no': '002',
                'is_active': 'on',
                'classrooms': [self.classroom.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='s2')
        self.assertTrue(user.check_password('123456'))
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.memberships.filter(active=True).exists())
        response = self.client.post(
            reverse('person_edit', args=['student', user.pk]),
            {
                'username': 's2',
                'full_name': '学生改名',
                'student_no': '002',
                'is_active': 'on',
                'classrooms': [self.classroom.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.full_name, '学生改名')
        self.client.post(reverse('person_delete', args=['student', user.pk]))
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_teacher_cannot_manage_roster_or_dictionary(self):
        for url in (
            '/students/',
            '/students/import/',
            '/dictionaries/',
            '/teachers/',
            '/classes/new/',
        ):
            self.assertEqual(self.get_as(self.teacher, url).status_code, 403)

    def test_authorization_revocation_enforced_for_edit_view_export(self):
        self.grant.can_export = False
        self.grant.save()
        self.assertEqual(
            self.get_as(self.teacher, reverse('work_export', args=[self.work.pk])).status_code, 403
        )
        self.grant.can_view_grades = False
        self.grant.can_edit = False
        self.grant.save()
        for route in ('work_edit', 'work_results', 'work'):
            self.assertEqual(
                self.get_as(self.teacher, reverse(route, args=[self.work.pk])).status_code, 403
            )

    def test_batch_roster_and_import_with_default_password(self):
        self.client.force_login(self.admin)
        csv = 'username,full_name,student_no,class_code\nnewstudent,新学生,003,C1\n'
        response = self.client.post(
            '/students/import/', {'file': SimpleUploadedFile('students.csv', csv.encode())}
        )
        self.assertContains(response, '可以导入')
        self.assertEqual(self.client.post('/students/import/', {'confirm': 'yes'}).status_code, 302)
        user = User.objects.get(username='newstudent')
        self.assertTrue(user.check_password('123456'))
        self.assertTrue(user.must_change_password)
        self.client.post(
            '/students/batch/',
            {'selected': [user.pk], 'action': 'remove_class', 'classroom': self.classroom.pk},
        )
        self.assertFalse(user.memberships.filter(active=True).exists())

    def test_dictionary_crud_duplicate_and_in_use_protection(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            '/dictionaries/new/', {'code': 'level', 'name': '等级', 'active': 'on'}
        )
        self.assertEqual(response.status_code, 302)
        dictionary = DataDictionary.objects.get(code='level')
        url = reverse('dictionary_item_new', args=[dictionary.pk])
        data = {'value': 'basic', 'label': '基础', 'order': 1, 'active': 'on'}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertContains(self.client.post(url, data), '不能重复')
        item = dictionary.items.get()
        self.client.post(reverse('dictionary_item_delete', args=[dictionary.pk, item.pk]))
        self.assertFalse(dictionary.items.exists())
        self.client.post(reverse('dictionary_delete', args=[dictionary.pk]))
        self.assertFalse(DataDictionary.objects.filter(pk=dictionary.pk).exists())
        course = DataDictionary.objects.get(code='course')
        item = course.items.get(value='Python 程序设计')
        self.client.post(reverse('dictionary_item_delete', args=[course.pk, item.pk]))
        self.assertTrue(DictionaryItem.objects.filter(pk=item.pk).exists())

    def test_work_keeps_private_document_and_package(self):
        self.assertEqual(self.work.package, self.package)
        self.assertEqual(self.work.items.count(), 1)
        self.assertEqual(read_private(self.work.document_path), self.text.decode())
        response = self.get_as(self.student, reverse('work_file', args=[self.work.pk, 'document']))
        self.assertEqual(b''.join(response.streaming_content), self.text)
        self.assertEqual(self.work.title, '第一次作业')

    def test_teacher_form_contains_package_or_document_class_deadline_and_revision(self):
        form = WorkForm(user=self.teacher)
        self.assertEqual(
            set(form.fields),
            {
                'grading_mode',
                'classroom',
                'package_file',
                'deadline',
                'revision',
            },
        )
        self.assertEqual(form.fields['package_file'].label, '机器批阅包')

    def test_updated_package_keeps_used_assets_and_selects_new_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chapter = root / '02-test'
            (chapter / 'data').mkdir(parents=True)
            (chapter / 'gold.py').write_text('def func1(x): return x + 1', encoding='utf-8')
            (chapter / 'func_info_list.txt').write_text('func1 10 data/func1.txt', encoding='utf-8')
            (chapter / 'data/func1.txt').write_text('1\n2', encoding='utf-8')
            call_command('import_course_packages', str(root), stdout=io.StringIO())
            original = EvaluationPackage.objects.get(code='chapter-02')
            self.work.package = original
            self.work.save()
            path = original.reference_path
            (chapter / 'gold.py').write_text('def func1(x): return x + 2', encoding='utf-8')
            call_command('import_course_packages', str(root), stdout=io.StringIO())
            original.refresh_from_db()
            self.assertFalse(original.active)
            self.assertEqual(original.reference_path, path)
            self.assertEqual(read_private(path), 'def func1(x): return x + 1')
            self.assertEqual(
                EvaluationPackage.objects.filter(
                    code__startswith='chapter-02', active=True
                ).count(),
                1,
            )

    def test_full_http_upload_submission_and_download(self):
        document = io.BytesIO()
        with ZipFile(document, 'w') as archive:
            archive.writestr(
                'word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>HTTP作业</w:t></w:r></w:p></w:body></w:document>',
            )
        package = io.BytesIO()
        with ZipFile(package, 'w') as archive:
            root = 'HTTP作业/'
            archive.writestr(root + 'HTTP作业.docx', document.getvalue())
            archive.writestr(root + 'sample.py', 'def func1(x):\n    pass\n')
            archive.writestr(root + 'gold.py', 'def func1(x):\n    return x + 1\n')
            archive.writestr(root + 'func_info_list.txt', 'func1 10 data/func1.txt\n')
            archive.writestr(root + 'data/func1.txt', '1\n')
        self.client.force_login(self.teacher)
        response = self.client.post(
            '/work/new/',
            {
                'grading_mode': 'automatic',
                'classroom': self.classroom.pk,
                'package_file': SimpleUploadedFile('HTTP作业.zip', package.getvalue()),
                'revision': 0,
                'deadline': timezone.now() + timezone.timedelta(days=3),
            },
        )
        self.assertEqual(response.status_code, 302)
        work = Coursework.objects.get(title='HTTP作业')
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('work', args=[work.pk]),
            {
                'request_id': uuid.uuid4(),
                'source': SimpleUploadedFile('student.py', b'def func1(x): return x+1'),
            },
        )
        self.assertEqual(response.status_code, 302)
        entry = work.entries.get()
        response = self.client.get(reverse('entry_source', args=[entry.pk]))
        self.assertEqual(b''.join(response.streaming_content), b'def func1(x): return x+1')

    def test_teacher_creation_grants_and_revoke(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('person_new', args=['teacher']),
            {'username': 't2', 'full_name': '教师二', 'student_no': 'T2', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 302)
        teacher = User.objects.get(username='t2')
        self.assertTrue(teacher.check_password('123456'))
        url = reverse('teacher_grants', args=[teacher.pk])
        self.assertEqual(
            self.client.post(
                url,
                {
                    'classroom': self.classroom.pk,
                    'can_edit': 'on',
                    'can_view_grades': 'on',
                    'can_export': 'on',
                    'active': 'on',
                },
            ).status_code,
            302,
        )
        self.assertTrue(teacher.teaching.get().can_export)
        self.client.post(url, {'classroom': self.classroom.pk})
        self.assertFalse(teacher.teaching.get().active)

    def test_bulk_delete_excludes_teacher_and_requires_selection(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            '/students/batch/', {'selected': [self.student.pk], 'action': 'remove_class'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.student.memberships.get().active)
        self.client.post(
            '/students/batch/', {'selected': [self.student.pk, self.teacher.pk], 'action': 'delete'}
        )
        self.teacher.refresh_from_db()
        self.assertFalse(User.objects.filter(pk=self.student.pk).exists())
        self.assertTrue(self.teacher.is_active)

    def test_class_crud(self):
        self.client.force_login(self.admin)
        data = {'code': 'C2', 'name': '二班', 'course_name': 'Python 程序设计', 'term': '2026 秋季'}
        self.assertEqual(self.client.post('/classes/new/', data).status_code, 302)
        classroom = Classroom.objects.get(code='C2')
        data['name'] = '二班改名'
        self.assertEqual(
            self.client.post(reverse('class_edit', args=[classroom.pk]), data).status_code, 302
        )
        classroom.refresh_from_db()
        self.assertEqual(classroom.name, '二班改名')
        self.client.post(reverse('class_delete', args=[classroom.pk]))
        self.assertFalse(Classroom.objects.filter(pk=classroom.pk).exists())

    def test_modify_in_place_and_reject_stale_form(self):
        self.assertFalse(WorkForm(instance=self.work, user=self.teacher).fields['grading_mode'].disabled)
        data = {
            'grading_mode': 'automatic',
            'classroom': self.classroom.pk,
            'deadline': timezone.now() + timezone.timedelta(days=2),
            'revision': self.work.revision,
        }
        form = WorkForm(data, instance=self.work, user=self.teacher)
        self.assertTrue(form.is_valid(), form.errors)
        updated = save_work(self.teacher, form)
        self.assertEqual(updated.pk, self.work.pk)
        self.assertEqual(Coursework.objects.count(), 1)
        stale = WorkForm(data, instance=updated, user=self.teacher)
        self.assertTrue(stale.is_valid(), stale.errors)
        with self.assertRaises(ValidationError):
            save_work(self.teacher, stale)

        self.entry()
        locked = WorkForm(instance=self.work, user=self.teacher)
        self.assertTrue(locked.fields['grading_mode'].disabled)
        self.assertIn('已有学生提交', locked.fields['grading_mode'].help_text)

    def test_unconfigured_work_collects_file_without_fake_score_then_bind(self):
        work = self.create_work(text=b'New exercise for future grading')
        entry = self.entry(work=work)
        self.assertEqual(entry.status, 'waiting')
        self.assertIsNone(entry.total)
        call_command('bind_course_package', work.pk, self.package.code, stdout=io.StringIO())
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'pending')
        self.assertEqual(entry.questions.count(), 1)

    def test_submission_scope_deadline_file_type_and_idempotency(self):
        with self.assertRaises(PermissionDenied):
            self.entry(user=self.teacher)
        entry = self.entry()
        self.assertEqual(self.entry(request_id=entry.request_id).pk, entry.pk)
        with self.assertRaises(ValidationError):
            self.entry()
        CourseworkSubmission.objects.filter(pk=entry.pk).update(status='done', total=10)
        self.work.deadline = timezone.now() - timezone.timedelta(seconds=1)
        self.work.save()
        with self.assertRaises(ValidationError):
            self.entry()
        for filename, body in [('a.txt', b'x'), ('a.py', b'x' * (128 * 1024 + 1)), ('a.py', b'')]:
            form = SubmitForm(
                {'request_id': uuid.uuid4()}, {'source': SimpleUploadedFile(filename, body)}
            )
            self.assertFalse(form.is_valid())

    def test_student_cannot_read_another_students_submission(self):
        entry = self.entry()
        other = User.objects.create_user(
            username='other', password='123456', must_change_password=False
        )
        UserRole.objects.create(user=other, role='student')
        ClassStudent.objects.create(classroom=self.classroom, student=other)
        for route in ('entry', 'entry_source'):
            self.assertEqual(self.get_as(other, reverse(route, args=[entry.pk])).status_code, 403)
        self.assertEqual(
            self.get_as(self.student, reverse('work_results', args=[self.work.pk])).status_code, 403
        )

    def test_partial_case_points_and_hierarchical_results(self):
        entry = self.entry()
        with patch(
            'school.portal.grading.grade_submission',
            return_value=[[CaseOutcome('AC', 3), CaseOutcome('WA', 4)]],
        ):
            evaluate(entry.pk)
        entry.refresh_from_db()
        self.assertEqual(entry.total, 5)
        self.assertEqual(entry.status, 'done')
        self.assertEqual(entry.questions.get().cases.count(), 2)
        response = self.get_as(self.student, reverse('entry', args=[entry.pk]))
        self.assertContains(response, '测试输入')
        self.assertContains(response, '<code>1</code>', html=True)
        self.assertContains(response, '<code>2</code>', html=True)
        self.assertContains(response, '结果不符')
        self.assertNotContains(response, self.package.reference_path)
        history = self.get_as(self.student, reverse('work', args=[self.work.pk]))
        self.assertContains(history, '得分 / 总分')
        self.assertContains(history, '5.0 / 10')
        self.assertContains(history, '机器批阅')
        second = self.entry()
        with patch(
            'school.portal.grading.grade_submission',
            return_value=[[CaseOutcome('AC', 2), CaseOutcome('AC', 2)]],
        ):
            evaluate(second.pk)
        second.refresh_from_db()
        self.assertEqual(second.total, 10)
        rows, stats = roster_rows(self.work)
        self.assertEqual(rows[0]['entry'], second)
        self.assertEqual(stats[3], ('均分/总分', '10.0 / 10'))
        self.assertEqual(stats[4][1], '10.0')
        self.assertEqual(stats[5][1], '10.0')

    def test_teacher_results_show_high_low_and_score_distribution(self):
        first = self.entry()
        CourseworkSubmission.objects.filter(pk=first.pk).update(status='done', total=10)
        for index, score in enumerate((8, 0), 2):
            student = User.objects.create_user(
                username=f'student{index}',
                full_name=f'学生{index}',
                student_no=f'20260{index}',
                password='123456',
                must_change_password=False,
            )
            UserRole.objects.create(user=student, role='student')
            ClassStudent.objects.create(classroom=self.classroom, student=student)
            entry = self.entry(user=student)
            CourseworkSubmission.objects.filter(pk=entry.pk).update(status='done', total=score)

        response = self.get_as(self.teacher, reverse('work_results', args=[self.work.pk]))
        self.assertContains(response, '均分/总分')
        self.assertContains(response, '6.0 / 10')
        self.assertContains(response, '最高分')
        self.assertContains(response, '最低分')
        self.assertContains(response, '全班成绩分布')
        self.assertContains(response, '全班成绩分布柱状图')
        self.assertContains(response, 'score-column-chart')
        self.assertContains(response, '90%～100%')
        self.assertContains(response, '80%～89%')
        self.assertEqual(response.context['distribution_graded_count'], 3)
        self.assertEqual(
            [bucket['count'] for bucket in response.context['score_distribution']],
            [1, 1, 0, 0, 1],
        )

        dashboard = self.get_as(self.teacher, reverse('dashboard'))
        self.assertContains(dashboard, '最高分')
        self.assertContains(dashboard, '最低分')

    def test_grader_failure_is_ungraded_not_zero_and_retry_possible(self):
        entry = self.entry()
        with patch(
            'school.portal.grading.grade_submission',
            side_effect=InfrastructureError('DOCKER_UNAVAILABLE'),
        ):
            evaluate(entry.pk)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'error')
        self.assertIsNone(entry.total)
        self.assertIsNone(entry.questions.get().score)
        self.client.force_login(self.teacher)
        self.client.post(reverse('entry_retry', args=[entry.pk]))
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'pending')

    def test_student_container_receives_no_reference_or_expected_answer(self):
        payload = json.dumps(
            {
                'load_verdict': '',
                'results': [
                    [
                        {
                            'verdict': 'OK',
                            'elapsed_ms': 1,
                            'value': {'type': 'str', 'value': 'REFERENCE_SECRET'},
                        }
                    ]
                ],
            }
        )
        item = {
            'function': 'func1',
            'argc': 1,
            'inputs': ['1'],
            'expected': [{'type': 'str', 'value': 'REFERENCE_SECRET'}],
        }
        with patch(
            'school.portal.grading.run_case',
            return_value=CaseOutcome('WA', 1, payload),
        ) as runner:
            result = grade_submission('STUDENT_MARKER', [item])
        self.assertEqual(result[0][0].verdict, 'AC')
        self.assertNotIn('REFERENCE_SECRET', runner.call_args.args[0])
        self.assertNotIn('REFERENCE_SECRET', runner.call_args.args[1])
        self.assertEqual(runner.call_count, 1)
        self.assertTrue(values_equal('{1, 2}', '{2, 1}'))
        self.assertFalse(values_equal("'a '", "'a'"))
        self.assertFalse(values_equal('True', '1'))
        compile(harness('def func1(x): return x', 'func1', 1), '<harness>', 'exec')
        compile(batch_harness('def func1(x): return x', 2000, 30000), '<batch>', 'exec')

    def test_zip_package_is_parsed_saved_and_queued_for_docker_validation(self):
        document = io.BytesIO()
        with ZipFile(document, 'w') as archive:
            archive.writestr(
                'word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第二章</w:t></w:r></w:p></w:body></w:document>',
            )
        package = io.BytesIO()
        with ZipFile(package, 'w') as archive:
            root = '02-python基础知识/'
            archive.writestr(root + '02-python基础知识习题说明.docx', document.getvalue())
            archive.writestr(root + 'sample02.py', 'def func201(a, b):\n    pass\n')
            archive.writestr(root + 'gold.py', 'def func201(a, b):\n    return a + b\n')
            archive.writestr(root + 'func_info_list.txt', 'func201 10 data/func201.txt\n')
            archive.writestr(root + 'data/func201.txt', '1, 2\n3, 4\n')
        parsed = parse_package_archive(package.getvalue(), 'chapter.zip')
        self.assertEqual(parsed['name'], '02-python基础知识')
        self.assertEqual(len(parsed['spec'][0]['inputs']), 2)
        form = WorkForm(
            {
                'grading_mode': 'automatic',
                'classroom': self.classroom.pk,
                'deadline': timezone.now() + timezone.timedelta(days=1),
                'revision': 0,
            },
            {'package_file': SimpleUploadedFile('chapter.zip', package.getvalue())},
            user=self.teacher,
        )
        self.assertTrue(form.is_valid(), form.errors)
        work = save_work(self.teacher, form)
        self.assertEqual(work.package.status, 'pending')
        self.assertEqual(work.items.count(), 1)
        self.assertEqual(work.description, '第二章')

    def test_manual_assignment_zip_submission_and_teacher_review(self):
        document = io.BytesIO()
        with ZipFile(document, 'w') as archive:
            archive.writestr(
                'word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第十章文件系统</w:t></w:r></w:p></w:body></w:document>',
            )
        materials = io.BytesIO()
        with ZipFile(materials, 'w') as archive:
            root = '10-文件系统/'
            archive.writestr(root + '10-文件系统习题说明.docx', document.getvalue())
            archive.writestr(root + '作业10数据文件/1001.txt', 'input')

        form = WorkForm(
            {
                'grading_mode': 'manual',
                'classroom': self.classroom.pk,
                'deadline': timezone.now() + timezone.timedelta(days=1),
                'revision': 0,
            },
            {'package_file': SimpleUploadedFile('chapter10.zip', materials.getvalue())},
            user=self.teacher,
        )
        self.assertTrue(form.is_valid(), form.errors)
        work = save_work(self.teacher, form)
        self.assertEqual(work.grading_mode, 'manual')
        self.assertIsNone(work.package)
        self.assertEqual(
            list(work.items.values_list('function_name', flat=True)),
            ['1001', '1002', '1003', '1004', '1005'],
        )
        self.assertTrue(work.materials_path)

        self.client.force_login(self.student)
        page = self.client.get(reverse('work', args=[work.pk]))
        self.assertContains(page, '请上传包含 `1001.py` 至 `1005.py` 的ZIP文件')
        self.assertContains(page, '下载题目数据文件')

        answer = io.BytesIO()
        with ZipFile(answer, 'w') as archive:
            for number in range(1001, 1006):
                archive.writestr(f'第十章答案/{number}.py', f'print({number})\n')
        response = self.client.post(
            reverse('work', args=[work.pk]),
            {
                'request_id': uuid.uuid4(),
                'source': SimpleUploadedFile('answers.zip', answer.getvalue()),
            },
        )
        self.assertEqual(response.status_code, 302)
        entry = work.entries.get()
        self.assertEqual(entry.status, 'review')
        self.assertEqual(entry.questions.count(), 5)

        self.client.force_login(self.teacher)
        review_page = self.client.get(reverse('entry', args=[entry.pk]))
        self.assertContains(review_page, 'print(1001)')
        review = {}
        for question in entry.questions.all():
            review[f'score_{question.pk}'] = 10
            review[f'feedback_{question.pk}'] = '完成正确'
        response = self.client.post(reverse('entry', args=[entry.pk]), review)
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'done')
        self.assertEqual(entry.total, 50)
        self.assertEqual(entry.graded_by, self.teacher)
        self.assertTrue(all(q.feedback == '完成正确' for q in entry.questions.all()))
        history = self.get_as(self.student, reverse('work', args=[work.pk]))
        self.assertContains(history, '50.0 / 50')
        self.assertContains(history, '非机器批阅')

    def test_package_reference_is_precomputed_once_and_releases_waiting_entries(self):
        package = EvaluationPackage.objects.create(
            code='pending-package',
            name='待验证',
            digest='pending-package',
            description='题目',
            reference_path=save_private('def func2(x): return x * 2', '.py'),
            spec=[{'function': 'func2', 'points': 10, 'argc': 1, 'inputs': ['2']}],
        )
        self.work.package = package
        self.work.save(update_fields=['package'])
        self.work.items.update(function_name='func2', title='func2')
        entry = self.entry()
        self.assertEqual(entry.status, 'waiting')
        payload = '{"results":[[{"type":"int","value":4}]]}'
        with patch(
            'school.portal.grading.run_case', return_value=CaseOutcome('WA', 4, payload)
        ) as runner:
            self.assertTrue(validate_package(package.pk))
        package.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(package.status, 'ready')
        self.assertEqual(entry.status, 'pending')
        self.assertEqual(runner.call_count, 1)

    def test_csv_export_scope_and_formula_escape(self):
        self.student.full_name = '=1+1'
        self.student.save()
        self.entry()
        response = self.get_as(self.teacher, reverse('work_export', args=[self.work.pk]))
        self.assertContains(response, "'=1+1")
        self.assertContains(response, '等待批阅')
        self.assertNotContains(response, 'Password-2026!')
        self.grant.active = False
        self.grant.save()
        self.assertEqual(
            self.client.get(reverse('work_export', args=[self.work.pk])).status_code, 403
        )

    def test_text_reading_docx_and_invalid_xml(self):
        output = io.BytesIO()
        with ZipFile(output, 'w') as archive:
            archive.writestr(
                'word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>题目说明</w:t></w:r></w:p></w:body></w:document>',
            )
        self.assertEqual(document_text(output.getvalue(), 'exercise.docx'), '题目说明')
        with self.assertRaises(ValidationError):
            document_text(b'broken zip', 'exercise.docx')

    def test_all_main_pages_render_and_delete_is_post_only_mutation(self):
        for user, routes in [
            (
                self.admin,
                [
                    '/teachers/',
                    '/students/',
                    '/classes/',
                    '/dictionaries/',
                    '/students/import/',
                    reverse('teacher_grants', args=[self.teacher.pk]),
                ],
            ),
            (
                self.teacher,
                [
                    '/work/',
                    '/work/new/',
                    '/results/',
                    reverse('work', args=[self.work.pk]),
                    reverse('work_results', args=[self.work.pk]),
                    reverse('class_detail', args=[self.classroom.pk]),
                    reverse('student_results', args=[self.classroom.pk, self.student.pk]),
                ],
            ),
            (self.student, ['/', reverse('work', args=[self.work.pk])]),
        ]:
            for url in routes:
                with self.subTest(url=url, user=user.username):
                    self.assertEqual(self.get_as(user, url).status_code, 200)
        self.get_as(self.teacher, reverse('work_delete', args=[self.work.pk]))
        self.work.refresh_from_db()
        self.assertIsNone(self.work.deleted_at)
        self.client.post(reverse('work_delete', args=[self.work.pk]))
        self.assertFalse(Coursework.objects.filter(pk=self.work.pk).exists())
