"""名单导入（imports.py）与管理命令的单元测试。"""

import tempfile
from io import BytesIO
from pathlib import Path
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from school.course_models import CourseworkRubric
from school.imports import commit_import, preview_import
from school.models import Classroom, Coursework, User, UserRole
from school.portal import rubric_agent
from school.portal.parsers import document_text
from school.tests.tests_helpers_docx import build_docx_bytes


def csv_file(body: str, name='roster.csv'):
    return SimpleUploadedFile(name, body.encode('utf-8-sig'), content_type='text/csv')


class PreviewImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='SafePassword_2026', full_name='管理员', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')
        Classroom.objects.create(code='C1', name='班一', course_name='Python', term='2026')

    def test_valid_csv_returns_rows(self):
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,用户一,9001,C1\r\n'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['error'], '')
        self.assertEqual(rows[0]['line'], 2)

    def test_bad_header_rejected(self):
        with self.assertRaisesMessage(ValidationError, '表头必须为'):
            preview_import(csv_file('name,full,sid,code\r\nu1,用户一,9001,C1\r\n'))

    def test_wrong_extension_rejected(self):
        with self.assertRaisesMessage(ValidationError, '.csv 或 .xlsx'):
            preview_import(csv_file('x', name='roster.pdf'))

    def test_oversized_file_rejected(self):
        big = SimpleUploadedFile('roster.csv', b'a' * (2 * 1024 * 1024 + 1))
        with self.assertRaisesMessage(ValidationError, '2 MB'):
            preview_import(big)

    def test_empty_rows_rejected(self):
        with self.assertRaisesMessage(ValidationError, '1～500'):
            preview_import(csv_file('username,full_name,student_no,class_code\r\n'))

    def test_more_than_500_rows_rejected(self):
        body = 'username,full_name,student_no,class_code\r\n' + ''.join(
            f'u{i},用户{i},{i},C1\r\n' for i in range(501)
        )
        with self.assertRaisesMessage(ValidationError, '1～500'):
            preview_import(csv_file(body))

    def test_missing_column_value_flagged(self):
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,,9001,C1\r\n'))
        self.assertEqual(rows[0]['error'], '所有列均需填写')

    def test_duplicate_in_file_flagged(self):
        rows = preview_import(
            csv_file(
                'username,full_name,student_no,class_code\r\n'
                'u1,用户一,9001,C1\r\nu1,用户一,9002,C1\r\n'
            )
        )
        self.assertIn('重复账号', rows[1]['error'])

    def test_unknown_class_flagged(self):
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,用户一,9001,XX\r\n'))
        self.assertEqual(rows[0]['error'], '教学班不存在或已归档')

    def test_existing_account_mismatch_flagged(self):
        User.objects.create_user(
            username='u1', password='x-SafePass', full_name='另一个', student_no='9001',
            must_change_password=False,
        )
        UserRole.objects.create(user=User.objects.get(username='u1'), role='teacher')
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,用户一,9001,C1\r\n'))
        self.assertIn('信息不一致', rows[0]['error'])

    def test_student_no_taken_flagged(self):
        other = User.objects.create_user(
            username='u2', password='x-SafePass', full_name='占用', student_no='9002',
            must_change_password=False,
        )
        UserRole.objects.create(user=other, role='student')
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,用户一,9002,C1\r\n'))
        self.assertEqual(rows[0]['error'], '学号已被其他账号使用')

    def test_xlsx_supported(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['username', 'full_name', 'student_no', 'class_code'])
        sheet.append(['xl1', '表格用户', '9101', 'C1'])
        buffer = BytesIO()
        workbook.save(buffer)
        upload = SimpleUploadedFile('roster.xlsx', buffer.getvalue())
        rows = preview_import(upload)
        self.assertEqual(rows[0]['error'], '')
        self.assertEqual(rows[0]['username'], 'xl1')

    def test_invalid_xlsx_rejected(self):
        upload = SimpleUploadedFile('roster.xlsx', b'not a zip')
        with self.assertRaisesMessage(ValidationError, '无法读取 Excel'):
            preview_import(upload)


class CommitImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='SafePassword_2026', full_name='管理员', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')
        Classroom.objects.create(code='C1', name='班一', course_name='Python', term='2026')

    def test_commit_creates_users_and_membership(self):
        rows = preview_import(
            csv_file(
                'username,full_name,student_no,class_code\r\n'
                'u1,用户一,9001,C1\r\nu2,用户二,9002,C1\r\n'
            )
        )
        created = commit_import(self.admin, rows, 'Import_2026pw')
        self.assertEqual(created, 2)
        user = User.objects.get(username='u1')
        self.assertTrue(user.has_role('student'))
        self.assertTrue(user.memberships.filter(classroom__code='C1').exists())

    def test_commit_rejects_rows_with_errors(self):
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,,9001,C1\r\n'))
        with self.assertRaisesMessage(ValidationError, '请修正所有错误'):
            commit_import(self.admin, rows, 'Import_2026pw')

    def test_commit_rejects_non_admin(self):
        student = User.objects.create_user(
            username='s', password='SafePassword_2026', full_name='学生', must_change_password=False
        )
        UserRole.objects.create(user=student, role='student')
        with self.assertRaises(PermissionDenied):
            commit_import(student, [], 'Import_2026pw')

    def test_commit_rejects_default_password_unless_allowed(self):
        # 项目默认关闭密码验证器，临时启用 CommonPasswordValidator 使 123456 不合格
        validators = [
            {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
        ]
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,用户一,9001,C1\r\n'))
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            with self.assertRaises(ValidationError):
                commit_import(self.admin, rows, '123456')
            created = commit_import(self.admin, rows, '123456', allow_default_password=True)
        self.assertEqual(created, 1)

    def test_commit_detects_state_change_after_preview(self):
        rows = preview_import(csv_file('username,full_name,student_no,class_code\r\nu1,用户一,9001,C1\r\n'))
        teacher = User.objects.create_user(
            username='u1', password='x-SafePass', full_name='另一个', student_no='9001',
            must_change_password=False,
        )
        UserRole.objects.create(user=teacher, role='teacher')
        with self.assertRaisesMessage(ValidationError, '状态已变化'):
            commit_import(self.admin, rows, 'Import_2026pw')


class BootstrapAdminTests(TestCase):
    def _run(self, password='Admin-2026#pw', username='newadmin'):
        with mock.patch('getpass.getpass', side_effect=[password, password]):
            call_command('bootstrap_admin', '--username', username, '--name', '新管理员')

    def test_creates_admin_with_must_change_password(self):
        self._run()
        user = User.objects.get(username='newadmin')
        self.assertTrue(user.has_role('admin'))
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password('Admin-2026#pw'))

    def test_existing_username_rejected(self):
        self._run()
        with self.assertRaisesMessage(CommandError, '账号已存在'):
            self._run()

    def test_mismatched_passwords_rejected(self):
        with mock.patch('getpass.getpass', side_effect=['abc12345', 'different']):
            with self.assertRaisesMessage(CommandError, '两次密码不一致'):
                call_command('bootstrap_admin', '--username', 'other')

    def test_weak_password_rejected(self):
        validators = [
            {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
        ]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            with mock.patch('getpass.getpass', side_effect=['123', '123']):
                with self.assertRaises(CommandError):
                    call_command('bootstrap_admin', '--username', 'weak')


class RefreshAbilitiesTests(TestCase):
    def _work(self, with_rubric=True):
        teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='教师', must_change_password=False
        )
        UserRole.objects.create(user=teacher, role='teacher')
        classroom = Classroom.objects.create(code='RA', name='能力班', course_name='Python', term='2026')
        work = Coursework.objects.create(
            classroom=classroom,
            owner=teacher,
            title='作业A',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        if with_rubric:
            CourseworkRubric.objects.create(coursework=work, markdown='# 评分标准')
        return work

    def test_skips_work_without_rubric(self):
        work = self._work(with_rubric=False)
        out = mock.Mock()
        with mock.patch(
            'school.models.Coursework.objects.select_related'
        ) as select:
            select.return_value.order_by.return_value = [work]
            call_command('refresh_abilities', stdout=out)
        out.write.assert_called_once()
        self.assertIn('跳过', out.write.call_args.args[0])

    def test_reports_generated_abilities(self):
        work = self._work()
        out = mock.Mock()
        abilities = [{'label': '基础语法'}, {'label': '控制结构'}]
        with mock.patch(
            'school.models.Coursework.objects.select_related'
        ) as select, mock.patch.object(
            rubric_agent, 'generate_abilities', return_value=abilities
        ) as generate:
            select.return_value.order_by.return_value = [work]
            call_command('refresh_abilities', stdout=out)
        generate.assert_called_once_with(work, offline=False)
        self.assertIn('基础语法、控制结构', out.write.call_args_list[-1].args[0])

    def test_reports_error_and_continues(self):
        work = self._work()
        err = mock.Mock()
        out = mock.Mock()
        with mock.patch(
            'school.models.Coursework.objects.select_related'
        ) as select, mock.patch.object(
            rubric_agent,
            'generate_abilities',
            side_effect=RuntimeError('端点不可用'),
        ):
            select.return_value.order_by.return_value = [work]
            call_command('refresh_abilities', stdout=out, stderr=err)
        err.write.assert_called_once()
        self.assertIn('端点不可用', err.write.call_args.args[0])

    def test_coursework_filter_option(self):
        out = mock.Mock()
        with mock.patch(
            'school.models.Coursework.objects.select_related'
        ) as select:
            call_command('refresh_abilities', '--coursework', '5', stdout=out)
        select.return_value.order_by.return_value.filter.assert_called_once_with(pk=5)


class AnalyzeRubricTests(TestCase):
    def _work(self):
        teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='教师', must_change_password=False
        )
        UserRole.objects.create(user=teacher, role='teacher')
        classroom = Classroom.objects.create(code='AR', name='评标班', course_name='Python', term='2026')
        return Coursework.objects.create(
            classroom=classroom,
            owner=teacher,
            title='列表作业',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )

    def test_missing_coursework_raises(self):
        with self.assertRaisesMessage(CommandError, '作业不存在'):
            call_command('analyze_rubric', '999')

    def test_generates_and_prints_summary(self):
        work = self._work()
        rubric = mock.Mock()
        rubric.model = ''
        rubric.get_source_display.return_value = '规则生成'
        rubric.dimensions = [{'label': '正确性', 'weight': 60.0}]
        rubric.knowledge_points = [{'name': '切片', 'detail': '掌握 1 起始计数'}]
        out = mock.Mock()
        with mock.patch(
            'school.portal.rubric_agent.generate_for', return_value=rubric
        ) as generate:
            call_command('analyze_rubric', str(work.pk), '--offline', stdout=out)
        generate.assert_called_once_with(work, offline=True, force=True)
        written = ' '.join(str(call.args[0]) for call in out.write.call_args_list)
        self.assertIn('列表作业', written)
        self.assertIn('规则生成', written)
        self.assertIn('正确性(60%)', written)
        self.assertIn('切片', written)

    def test_keep_option_reuses_existing(self):
        work = self._work()
        rubric = mock.Mock()
        rubric.model = 'gpt-x'
        rubric.get_source_display.return_value = '大模型'
        rubric.dimensions = []
        rubric.knowledge_points = []
        out = mock.Mock()
        with mock.patch(
            'school.portal.rubric_agent.generate_for', return_value=rubric
        ) as generate:
            call_command('analyze_rubric', str(work.pk), '--keep', stdout=out)
        generate.assert_called_once_with(work, offline=False, force=False)
        self.assertIn('gpt-x', ' '.join(str(c.args[0]) for c in out.write.call_args_list))

    def test_llm_errors_become_command_error(self):
        from school.portal import rubric_agent

        work = self._work()
        with mock.patch.object(
            rubric_agent, 'generate_for', side_effect=rubric_agent.LLMNotConfigured('未配置')
        ):
            with self.assertRaisesMessage(CommandError, '未配置'):
                call_command('analyze_rubric', str(work.pk))


class ImportCoursePackagesTests(TestCase):
    def test_missing_directory_raises(self):
        with self.assertRaisesMessage(CommandError, '目录不存在'):
            call_command('import_course_packages', 'Z:/definitely/not/here')

    def _prepare_chapter(self, root):
        folder = root / '01基础'
        folder.mkdir(parents=True)
        (folder / '题.docx').write_bytes(build_docx_bytes(['题目一']))
        (folder / 'sample.py').write_text('def func301(a, b):\n    pass\n', encoding='utf-8')
        (folder / 'gold.py').write_text('def func301(a, b):\n    return a + b\n', encoding='utf-8')
        (folder / 'func_info_list.txt').write_text('func301 100 data/func301.txt\n', encoding='utf-8')
        (folder / 'data').mkdir()
        (folder / 'data' / 'func301.txt').write_text('[1, 2]\n[3, 4]\n', encoding='utf-8')

    def test_imports_and_dedupes_reimport(self):
        from school.models import EvaluationPackage

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self._prepare_chapter(root)
            out = mock.Mock()
            call_command('import_course_packages', name, stdout=out)
            self.assertEqual(EvaluationPackage.objects.filter(active=True).count(), 1)
            package = EvaluationPackage.objects.get(active=True)
            self.assertEqual(package.code, 'chapter-01')
            self.assertTrue(package.template_path)
            # 再次导入同样内容：命中同一 digest，不新增
            call_command('import_course_packages', name, stdout=out)
            self.assertEqual(EvaluationPackage.objects.count(), 1)
            # 停用后重新导入：恢复 active 并清除错误状态
            EvaluationPackage.objects.update(active=False, status='error', validation_error='旧错误')
            call_command('import_course_packages', name, stdout=out)
            package.refresh_from_db()
            self.assertTrue(package.active)
            self.assertEqual(package.status, 'pending')
            self.assertEqual(package.validation_error, '')

    def test_skips_non_chapter_folders(self):
        from school.models import EvaluationPackage

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'notes').mkdir()
            (root / '99尾部').mkdir()
            out = mock.Mock()
            call_command('import_course_packages', name, stdout=out)
            self.assertEqual(EvaluationPackage.objects.count(), 0)
            self.assertIn('导入完成：0', out.write.call_args_list[-1].args[0])


class DocumentTextHelperTests(TestCase):
    def test_build_docx_helper_matches_parser(self):
        self.assertEqual(document_text(build_docx_bytes(['段落']), 'a.docx'), '段落')
