"""旧路由（config.legacy_urls）下视图的回归测试。

现行业务在 school/portal，旧视图仅供回归保障；
这里覆盖班级与账号管理、导入、提交流程、成绩与补交处理的页面路径。
"""

import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.models import (
    Announcement,
    Assignment,
    AssignmentQuestion,
    AssignmentVersion,
    Classroom,
    ClassStaff,
    ExtensionRequest,
    GradeRevision,
    JudgeRun,
    Notification,
    Problem,
    ProblemVersion,
    Submission,
    SubmissionRuleVersion,
    TestCase as TestCaseModel,
    User,
    UserRole,
)
from school.services import (
    accept_submission,
    make_revision,
    publish_assignment,
    set_membership,
    set_staff,
)
from school.storage import save_private
from school.teaching import edit_token


@override_settings(
    ROOT_URLCONF='config.legacy_urls',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class LegacyViewTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

        self.admin = self._user('admin', 'admin')
        self.teacher = self._user('teacher', 'teacher')
        self.assistant = self._user('assistant', 'assistant')
        self.student = self._user('student', 'student')
        self.classroom = Classroom.objects.create(code='L1', name='旧路由班', term='2026')
        set_membership(self.admin, self.classroom, self.student)
        set_staff(
            self.admin,
            self.classroom,
            self.teacher,
            'teacher',
            can_edit=True,
            can_view_grades=True,
            can_export=True,
        )
        set_staff(
            self.admin,
            self.classroom,
            self.assistant,
            'assistant',
            can_edit=True,
            can_view_grades=True,
        )
        problem = Problem.objects.create(
            code='P1', classroom=self.classroom, created_by=self.teacher
        )
        self.version = ProblemVersion.objects.create(
            problem=problem,
            title='加法',
            statement='求和',
            reference_path=save_private('print(sum(map(int,input().split())))'),
            reference_verified=True,
        )
        for order, (stdin, expected, sample) in enumerate(
            [('1 2', '3', True), ('2 3', '5', False)], 1
        ):
            TestCaseModel.objects.create(
                version=self.version,
                order=order,
                input_path=save_private(stdin),
                output_path=save_private(expected),
                is_sample=sample,
                hidden=not sample,
            )
        self.assignment = Assignment.objects.create(
            classroom=self.classroom, created_by=self.teacher
        )
        now = timezone.now() - timedelta(minutes=1)
        self.rule = SubmissionRuleVersion.objects.create(
            assignment=self.assignment,
            number=1,
            opens_at=now - timedelta(days=1),
            deadline=now + timedelta(days=1),
            late_deadline=now + timedelta(days=2),
            late_penalty=Decimal('.100'),
        )
        self.aversion = AssignmentVersion.objects.create(
            assignment=self.assignment, number=1, title='测试作业', rule=self.rule
        )
        self.question = AssignmentQuestion.objects.create(
            version=self.aversion,
            question_key='P1',
            problem_version=self.version,
            max_score=100,
        )
        publish_assignment(self.teacher, self.aversion)

    def _user(self, username, role):
        user = User.objects.create_user(
            username=username,
            password='SafePassword_2026',
            full_name=username,
            student_no=username,
            must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def submit(self, code='print(5)'):
        return accept_submission(
            self.student, self.question.pk, code, uuid.uuid4(), timezone.now()
        )

    # ---- 班级管理 ----

    def test_class_create_redirects_to_detail(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('class_create'),
            {'code': 'NEW', 'name': '新班', 'course_name': 'Python 程序设计', 'term': '2026'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Classroom.objects.filter(code='NEW').exists())

    def test_class_detail_member_action(self):
        new_student = self._user('s2', 'student')
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('class_detail', args=[self.classroom.pk]),
            {'action': 'member', 'student': new_student.pk, 'active': '1'},
        )
        self.assertRedirects(response, reverse('class_detail', args=[self.classroom.pk]))

    def test_class_detail_staff_action(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('class_detail', args=[self.classroom.pk]),
            {
                'action': 'staff',
                'user': self.assistant.pk,
                'role': 'assistant',
                'can_view_grades': 'on',
            },
        )
        self.assertRedirects(response, reverse('class_detail', args=[self.classroom.pk]))

    def test_class_detail_revoke_action(self):
        staff = ClassStaff.objects.get(user=self.assistant, classroom=self.classroom)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('class_detail', args=[self.classroom.pk]),
            {'action': 'revoke', 'staff': staff.pk},
        )
        self.assertRedirects(response, reverse('class_detail', args=[self.classroom.pk]))
        staff.refresh_from_db()
        self.assertFalse(staff.active)

    def test_class_detail_archive_toggle(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('class_detail', args=[self.classroom.pk]), {'action': 'archive'}
        )
        self.classroom.refresh_from_db()
        self.assertTrue(self.classroom.archived)

    def test_class_detail_invalid_action_shows_error(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('class_detail', args=[self.classroom.pk]), {'action': 'bogus'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '请检查表单内容')

    def test_non_admin_cannot_post_class_actions(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('class_detail', args=[self.classroom.pk]), {'action': 'archive'}
        )
        self.assertEqual(response.status_code, 403)

    # ---- 账号管理 ----

    def test_users_view_search_filters(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users') + '?q=stu')
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['users']
        self.assertEqual(
            [user.username for user in page_obj.object_list], ['student']
        )

    def test_user_create_with_roles(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('user_create'),
            {
                'username': 'newbie',
                'full_name': '新同学',
                'student_no': '2026999',
                'roles': ['student'],
                'password': 'InitPass_2026x',
            },
        )
        self.assertRedirects(response, reverse('users'))
        self.assertTrue(User.objects.filter(username='newbie').exists())

    def test_user_detail_toggle_active(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('user_detail', args=[self.student.pk]), {'action': 'toggle'}
        )
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)

    def test_user_detail_reset_password(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('user_detail', args=[self.student.pk]),
            {'action': 'reset', 'password': 'ResetPass_2026'},
        )
        self.student.refresh_from_db()
        self.assertTrue(self.student.must_change_password)
        self.assertTrue(self.student.check_password('ResetPass_2026'))

    def test_user_detail_reset_weak_password_rejected(self):
        # 项目默认关闭密码验证器，这里临时启用以验证重置路径的校验分支
        validators = [
            {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
        ]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            self.client.force_login(self.admin)
            self.client.post(
                reverse('user_detail', args=[self.student.pk]),
                {'action': 'reset', 'password': '123'},
                follow=True,
            )
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password('SafePassword_2026'))

    def test_user_detail_roles_updates_membership(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('user_detail', args=[self.student.pk]),
            {'action': 'roles', 'roles': ['teacher']},
        )
        roles = set(self.student.roles.values_list('role', flat=True))
        self.assertEqual(roles, {'teacher'})

    def test_user_detail_self_management_blocked(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('user_detail', args=[self.admin.pk]), {'action': 'toggle'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '请通过其他管理员管理当前账号')

    def test_user_detail_unknown_action_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('user_detail', args=[self.student.pk]), {'action': 'bogus'}
        )
        self.assertContains(response, '未知操作')

    def test_user_detail_profile_update(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('user_detail', args=[self.student.pk]),
            {'action': 'profile', 'full_name': '新名字', 'student_no': '2026888'},
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, '新名字')

    # ---- 名单导入 ----

    def test_import_template_downloads(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('import_template'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])

    def test_users_import_preview_and_commit(self):
        self.client.force_login(self.admin)
        csv_body = 'username,full_name,student_no,class_code\r\nimp1,导入一,9001,L1\r\n'.encode(
            'utf-8-sig'
        )
        upload = SimpleUploadedFile('roster.csv', csv_body, content_type='text/csv')
        response = self.client.post(
            reverse('users_import'), {'action': 'preview', 'file': upload}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'imp1')
        response = self.client.post(
            reverse('users_import'), {'action': 'commit', 'password': 'Import_2026pw'}
        )
        self.assertRedirects(response, reverse('users'))
        self.assertTrue(User.objects.filter(username='imp1').exists())

    def test_users_import_commit_without_preview_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('users_import'), {'action': 'commit', 'password': 'Import_2026pw'}
        )
        self.assertContains(response, '请先预览导入文件')

    # ---- 提交与题目 ----

    def test_question_view_get_hides_hidden_cases(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('question', args=[self.question.pk]))
        self.assertContains(response, '1 2')
        self.assertNotContains(response, '2 3')

    def test_question_view_submit_code(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('question', args=[self.question.pk]),
            {'code': 'print(5)', 'request_key': uuid.uuid4()},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Submission.objects.filter(student=self.student).exists())

    def test_question_view_draft_hidden_from_student(self):
        draft = AssignmentVersion.objects.create(
            assignment=self.assignment, number=2, title='草稿作业', rule=self.rule
        )
        draft_question = AssignmentQuestion.objects.create(
            version=draft, question_key='P1', problem_version=self.version, max_score=50
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('question', args=[draft_question.pk]))
        self.assertEqual(response.status_code, 403)

    def test_submissions_view_redirects_non_student(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('submissions'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_submission_view_owner_and_status_json(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'done'
        run.verdict = 'AC'
        run.base_score = 100
        run.save()
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse('submission', args=[sub.pk])).status_code, 200
        )
        status = self.client.get(reverse('submission_status', args=[sub.pk]))
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertEqual(payload['status'], 'done')
        self.assertEqual(payload['score'], '100.00')

    def test_my_grades_renders_for_student(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('my_grades')).status_code, 200)

    # ---- 补交与公告与通知 ----

    def test_extensions_view_create_and_duplicate(self):
        self.client.force_login(self.student)
        self.client.post(
            reverse('extensions', args=[self.assignment.pk]), {'reason': '生病住院无法按时提交'}
        )
        self.assertEqual(ExtensionRequest.objects.filter(student=self.student).count(), 1)
        second = self.client.post(
            reverse('extensions', args=[self.assignment.pk]), {'reason': '再次提交补交申请'}
        )
        self.assertContains(second, '请勿重复提交')
        self.assertEqual(ExtensionRequest.objects.filter(student=self.student).count(), 1)

    def test_announcement_create_for_classroom_and_platform(self):
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('class_announcement', args=[self.classroom.pk]),
            {'title': '班内通知', 'content': '明天交作业'},
        )
        self.client.force_login(self.admin)
        self.client.post(
            reverse('announcement_create'),
            {'title': '平台公告', 'content': '系统维护'},
        )
        self.assertEqual(Announcement.objects.count(), 2)

    def test_notifications_mark_all_read(self):
        Notification.objects.create(
            recipient=self.student,
            event='test',
            message='通知内容',
            dedup_key='test-1',
        )
        self.client.force_login(self.student)
        response = self.client.post(reverse('notifications'))
        self.assertRedirects(response, reverse('notifications'))
        self.assertFalse(
            self.student.notifications.filter(read_at__isnull=True).exists()
        )

    # ---- 运维操作 ----

    def test_operations_retry_error_run(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'error'
        run.error_code = 'DOCKER_UNAVAILABLE'
        run.save()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('operations'), {'run': run.pk, 'action': 'retry'}
        )
        self.assertRedirects(response, reverse('operations'))
        run.refresh_from_db()
        self.assertEqual(run.status, 'superseded')
        # 重试会创建新的执行记录
        self.assertTrue(JudgeRun.objects.filter(submission=sub).exclude(pk=run.pk).exists())

    def test_operations_refund_error_run(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'error'
        run.save()
        self.client.force_login(self.admin)
        self.client.post(reverse('operations'), {'run': run.pk, 'action': 'refund'})
        sub.refresh_from_db()
        self.assertFalse(sub.counted)
        run.refresh_from_db()
        self.assertEqual(run.status, 'superseded')

    def test_operations_rejects_non_error_run(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'pending'
        run.save()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('operations'), {'run': run.pk, 'action': 'retry'}, follow=True
        )
        self.assertContains(response, '只能处理系统异常任务')

    def test_operations_rejects_unknown_action(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'error'
        run.save()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('operations'), {'run': run.pk, 'action': 'bogus'}, follow=True
        )
        self.assertContains(response, '无效操作')


class LegacyTeachingViewTests(LegacyViewTests):
    """旧教学模块（school/teaching_views.py）的回归测试，复用同一夹具。"""

    def make_draft(self):
        draft = AssignmentVersion.objects.create(
            assignment=self.assignment, number=2, title='草稿作业', rule=self.rule
        )
        question = AssignmentQuestion.objects.create(
            version=draft, question_key='P1', problem_version=self.version, max_score=100
        )
        return draft, question

    def test_problem_retry_dispatches_verification(self):
        fresh = ProblemVersion.objects.create(
            problem=self.version.problem,
            number=2,
            title='加法v2',
            statement='求和',
            reference_path=save_private('print(1)'),
        )
        TestCaseModel.objects.create(
            version=fresh,
            order=1,
            input_path=save_private('1'),
            output_path=save_private('1'),
            is_sample=False,
        )
        self.client.force_login(self.teacher)
        with mock.patch('school.teaching_views.dispatch_reference') as dispatch:
            response = self.client.post(reverse('problem_retry', args=[fresh.pk]))
        dispatch.assert_called_once_with(fresh.pk)
        self.assertRedirects(response, reverse('problems', args=[self.classroom.pk]))

    def test_problem_retry_skips_when_not_configured(self):
        fresh = ProblemVersion.objects.create(
            problem=self.version.problem,
            number=2,
            title='无评测题',
            statement='求和',
        )
        self.client.force_login(self.teacher)
        with mock.patch('school.teaching_views.dispatch_reference') as dispatch:
            self.client.post(reverse('problem_retry', args=[fresh.pk]))
        dispatch.assert_not_called()

    def test_assignment_action_publishes_draft_with_token(self):
        draft, _question = self.make_draft()
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('assignment_action', args=[draft.pk]),
            {'action': 'publish', 'edit_token': edit_token(draft)},
        )
        self.assertRedirects(response, reverse('assignment', args=[self.assignment.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'published')

    def test_assignment_action_publish_rejects_stale_token(self):
        draft, _question = self.make_draft()
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('assignment_action', args=[draft.pk]),
            {'action': 'publish', 'edit_token': 'stale'},
            follow=True,
        )
        self.assertContains(response, '请重新打开并检查当前内容')

    def test_assignment_action_updates_draft_points(self):
        draft, question = self.make_draft()
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('assignment_action', args=[draft.pk]),
            {
                'action': 'points',
                'edit_token': edit_token(draft),
                f'points_{question.pk}': '80.5',
            },
        )
        self.assertRedirects(response, reverse('assignment', args=[self.assignment.pk]))
        question.refresh_from_db()
        self.assertEqual(question.max_score, Decimal('80.5'))

    def test_assignment_action_points_rejects_invalid(self):
        draft, question = self.make_draft()
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('assignment_action', args=[draft.pk]),
            {
                'action': 'points',
                'edit_token': edit_token(draft),
                f'points_{question.pk}': 'abc',
            },
            follow=True,
        )
        self.assertContains(response, '分值格式不正确')

    def test_assignment_action_points_rejects_published(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('assignment_action', args=[self.aversion.pk]),
            {
                'action': 'points',
                'edit_token': edit_token(self.aversion),
                f'points_{self.question.pk}': '80',
            },
            follow=True,
        )
        self.assertContains(response, '只能调整草稿分值')

    def test_grades_flow_calculate_and_publish_then_export(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'done'
        run.verdict = 'AC'
        run.base_score = 100
        run.save()
        self.client.force_login(self.teacher)
        self.client.post(reverse('grades', args=[self.assignment.pk]), {'action': 'calculate'})
        revision = GradeRevision.objects.get(assignment=self.assignment)
        self.assertEqual(revision.status, 'ready')
        self.client.post(
            reverse('grades', args=[self.assignment.pk]),
            {'action': 'publish', 'revision': revision.pk},
        )
        revision.refresh_from_db()
        self.assertEqual(revision.status, 'published')
        # 学生端可查看已发布成绩
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('my_grades')).status_code, 200)
        # 教师导出 CSV
        self.client.force_login(self.teacher)
        export = self.client.get(reverse('grades_export', args=[revision.pk]))
        self.assertEqual(export.status_code, 200)
        self.assertIn(b'student', export.content)

    def test_grades_export_unpublished_forbidden(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'done'
        run.base_score = 100
        run.save()
        revision = make_revision(self.teacher, self.assignment, '测试批次')
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('grades_export', args=[revision.pk]))
        self.assertEqual(response.status_code, 403)

    def test_assignment_detail_and_version_access(self):
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse('assignment', args=[self.assignment.pk])).status_code, 200
        )
        outsider = self._user('outsider', 'student')
        self.client.force_login(outsider)
        self.assertEqual(
            self.client.get(reverse('assignment', args=[self.assignment.pk])).status_code, 403
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('assignment_version', args=[self.aversion.pk]))
        self.assertRedirects(response, reverse('assignment', args=[self.assignment.pk]))

    def test_extension_decide_note_revoke_and_approve(self):
        extension = ExtensionRequest.objects.create(
            student=self.student,
            assignment=self.assignment,
            reason='生病住院无法按时提交',
        )
        self.client.force_login(self.teacher)
        # 备注路径
        response = self.client.post(
            reverse('extension_decide', args=[extension.pk]),
            {'action': 'note', 'note': '情况属实'},
        )
        self.assertRedirects(response, reverse('extensions', args=[self.assignment.pk]))
        extension.refresh_from_db()
        self.assertEqual(extension.assistant_note, '情况属实')
        # 撤销路径（需先批准）
        ExtensionRequest.objects.filter(pk=extension.pk).update(status='approved')
        response = self.client.post(
            reverse('extension_decide', args=[extension.pk]), {'action': 'revoke'}
        )
        self.assertRedirects(response, reverse('extensions', args=[self.assignment.pk]))
        extension.refresh_from_db()
        self.assertEqual(extension.status, 'revoked')

    def test_extension_decide_approves_with_form(self):
        extension = ExtensionRequest.objects.create(
            student=self.student,
            assignment=self.assignment,
            reason='生病住院无法按时提交',
        )
        now = timezone.localtime()
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('extension_decide', args=[extension.pk]),
            {
                'approve': 'yes',
                'starts_at': now.strftime('%Y-%m-%dT%H:%M'),
                'ends_at': (now + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
                'attempts': '2',
                'penalty': '0.1',
            },
        )
        self.assertRedirects(response, reverse('extensions', args=[self.assignment.pk]))
        extension.refresh_from_db()
        self.assertEqual(extension.status, 'approved')

