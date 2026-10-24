import tempfile
import uuid
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase as DjangoTestCase, override_settings, Client
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from school.models import *
from school.services import *
from school.permissions import permitted
from school.storage import save_private, read_private
from school.judge import evaluate, CaseOutcome, InfrastructureError, compare_output
from school.imports import preview_import, commit_import


@override_settings(
    ROOT_URLCONF='config.legacy_urls',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class WorkflowTests(DjangoTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = override_settings(PRIVATE_STORAGE=Path(self.temp.name))
        self.storage.enable()
        self.addCleanup(self.storage.disable)
        self.addCleanup(self.temp.cleanup)
        self.now = timezone.now() - timedelta(minutes=1)
        self.people = {}
        for role in ('admin', 'teacher', 'assistant', 'student'):
            user = User.objects.create_user(
                username=role,
                password='SafePassword_2026',
                full_name=role,
                student_no=role,
                must_change_password=False,
            )
            UserRole.objects.create(user=user, role=role)
            self.people[role] = user
        self.admin, self.teacher, self.assistant, self.student = [
            self.people[k] for k in ('admin', 'teacher', 'assistant', 'student')
        ]
        self.c = Classroom.objects.create(code='TEST', name='测试班', term='2026')
        set_membership(self.admin, self.c, self.student)
        set_staff(
            self.admin,
            self.c,
            self.teacher,
            'teacher',
            can_edit=True,
            can_view_grades=True,
            can_export=True,
        )
        set_staff(
            self.admin,
            self.c,
            self.assistant,
            'assistant',
            can_edit=True,
            can_view_grades=True,
            can_export=False,
        )
        problem = Problem.objects.create(code='P1', classroom=self.c, created_by=self.teacher)
        self.p = ProblemVersion.objects.create(
            problem=problem,
            title='加法',
            statement='输入两个整数求和',
            input_format='a b',
            output_format='和',
            data_range='整数',
            reference_path=save_private('print(sum(map(int,input().split())))'),
            reference_verified=True,
        )
        for index, (stdin, expected, sample) in enumerate(
            [('1 2', '3', True), ('2 3', '5', False), ('-5 2', '-3', False)], 1
        ):
            TestCase.objects.create(
                version=self.p,
                order=index,
                input_path=save_private(stdin),
                output_path=save_private(expected),
                is_sample=sample,
                hidden=not sample,
            )
        self.a = Assignment.objects.create(classroom=self.c, created_by=self.teacher)
        self.rule = SubmissionRuleVersion.objects.create(
            assignment=self.a,
            number=1,
            opens_at=self.now - timedelta(days=1),
            deadline=self.now + timedelta(days=1),
            late_deadline=self.now + timedelta(days=2),
            late_penalty=Decimal('.100'),
        )
        self.v = AssignmentVersion.objects.create(
            assignment=self.a, number=1, title='测试作业', rule=self.rule
        )
        self.q = AssignmentQuestion.objects.create(
            version=self.v, question_key='P1', problem_version=self.p, max_score=100
        )
        publish_assignment(self.teacher, self.v)
        self.a.refresh_from_db()

    def submit(self, now=None, code='print(5)', key=None):
        return accept_submission(
            self.student, self.q.pk, code, key or uuid.uuid4(), now or self.now
        )

    def finish(self, sub, score=100):
        run = sub.runs.first()
        run.status = 'done'
        run.verdict = 'AC' if score else 'WA'
        run.base_score = score
        run.save()
        return run

    def test_only_admin_manages_roster(self):
        for actor in (self.teacher, self.assistant, self.student):
            with self.assertRaises(PermissionDenied):
                set_membership(actor, self.c, self.student, False)

    def test_same_class_student_staff_conflict(self):
        UserRole.objects.create(user=self.student, role='assistant')
        with self.assertRaises(ValidationError):
            set_staff(self.admin, self.c, self.student, 'assistant')

    def test_ta_cannot_publish_or_export(self):
        self.assertTrue(permitted(self.assistant, self.c, 'edit'))
        self.assertFalse(permitted(self.assistant, self.c, 'publish'))
        self.assertFalse(permitted(self.assistant, self.c, 'export'))
        with self.assertRaises(PermissionDenied):
            make_revision(self.assistant, self.a)

    def test_authorization_expiration_and_revocation(self):
        staff = ClassStaff.objects.get(user=self.assistant)
        staff.expires_at = self.now - timedelta(seconds=1)
        staff.save()
        self.assertFalse(permitted(self.assistant, self.c, 'edit'))
        staff.expires_at = None
        staff.active = False
        staff.save()
        self.assertFalse(permitted(self.assistant, self.c, 'grades'))

    def test_submission_idempotency_and_payload_binding(self):
        key = uuid.uuid4()
        sub = self.submit(key=key)
        self.assertEqual(self.submit(key=key).pk, sub.pk)
        self.assertEqual(Submission.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.submit(key=key, code='print(9)')

    def test_exact_deadline_accepted_as_normal(self):
        sub = self.submit(now=self.rule.deadline)
        self.assertEqual(sub.kind, 'normal')

    def test_late_penalty_snapshot(self):
        sub = self.submit(now=self.rule.deadline + timedelta(seconds=1))
        run = self.finish(sub)
        self.assertEqual(sub.kind, 'late')
        self.assertEqual(final_score(run), Decimal('90.00'))

    def test_outside_window_rejected(self):
        with self.assertRaises(ValidationError):
            self.submit(now=self.rule.late_deadline + timedelta(seconds=1))
        self.assertEqual(Submission.objects.count(), 0)

    def test_rate_pending_attempt_limits(self):
        first = self.submit()
        with self.assertRaises(ValidationError):
            self.submit(now=self.now + timedelta(seconds=1))
        self.submit(now=self.now + timedelta(seconds=10))
        with self.assertRaises(ValidationError):
            self.submit(now=self.now + timedelta(seconds=20))
        JudgeRun.objects.update(status='done', base_score=0)
        self.rule.max_attempts = 2
        self.rule.save()
        with self.assertRaises(ValidationError):
            self.submit(now=self.now + timedelta(seconds=30))

    def test_removed_student_cannot_submit_can_read_own_history(self):
        sub = self.submit()
        set_membership(self.admin, self.c, self.student, False)
        with self.assertRaises(PermissionDenied):
            self.submit(now=self.now + timedelta(seconds=11))
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(f'/submissions/{sub.pk}/').status_code, 200)

    def test_other_student_cannot_read_code_or_results(self):
        sub = self.submit(code='print("private code")')
        other = User.objects.create_user(
            username='other', password='a', full_name='另一人', must_change_password=False
        )
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/submissions/{sub.pk}/').status_code, 403)
        self.assertEqual(self.client.get(f'/submissions/{sub.pk}/status/').status_code, 403)

    def test_hidden_case_not_in_student_page(self):
        self.client.force_login(self.student)
        response = self.client.get(f'/questions/{self.q.pk}/')
        self.assertContains(response, '1 2')
        self.assertNotContains(response, '-5 2')
        self.assertNotContains(response, self.p.reference_path)

    def test_all_cases_pass_or_zero_no_partial_credit(self):
        sub = self.submit()
        with patch(
            'school.judge.run_case',
            side_effect=[CaseOutcome('AC', 5), CaseOutcome('AC', 5), CaseOutcome('WA', 5)],
        ):
            evaluate(sub.runs.first().pk)
        run = sub.runs.first()
        self.assertEqual(run.base_score, 0)
        self.assertEqual(run.results.count(), 3)
        with patch('school.judge.run_case') as runner:
            evaluate(run.pk)
        runner.assert_not_called()

    def test_passed_all_cases_full_score(self):
        sub = self.submit()
        with patch('school.judge.run_case', return_value=CaseOutcome('AC', 5)):
            evaluate(sub.runs.first().pk)
        self.assertEqual(sub.runs.first().base_score, 100)

    def test_sample_feedback_does_not_change_formal_score(self):
        sub = self.submit()
        with patch(
            'school.judge.run_case',
            side_effect=[CaseOutcome('WA', 5), CaseOutcome('AC', 5), CaseOutcome('AC', 5)],
        ):
            evaluate(sub.runs.first().pk)
        run = sub.runs.first()
        self.assertEqual(run.base_score, 100)
        self.assertEqual(run.results.filter(case__is_sample=True).get().verdict, 'WA')

    def test_testcase_form_preserves_exact_whitespace(self):
        from school.forms import CaseForm

        form = CaseForm({'input': '  5\n', 'output': '  6 \n', 'enabled': 'on'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['input'], '  5\n')
        self.assertEqual(form.cleaned_data['output'], '  6 \n')

    def test_multirole_cannot_see_student_class_drafts(self):
        UserRole.objects.create(user=self.assistant, role='student')
        other = Classroom.objects.create(code='OTHER', name='另一教学班', term='2026')
        set_membership(self.admin, other, self.assistant)
        assignment = Assignment.objects.create(classroom=other, created_by=self.teacher)
        rule = SubmissionRuleVersion.objects.create(
            assignment=assignment,
            number=1,
            opens_at=self.now,
            deadline=self.now + timedelta(days=1),
        )
        AssignmentVersion.objects.create(
            assignment=assignment, number=1, title='不应透露的未发布草稿', rule=rule
        )
        self.client.force_login(self.assistant)
        self.assertNotContains(self.client.get('/'), '不应透露的未发布草稿')

    def test_system_error_not_zero(self):
        sub = self.submit()
        with patch('school.judge.run_case', side_effect=InfrastructureError('DOCKER_UNAVAILABLE')):
            evaluate(sub.runs.first().pk)
        run = sub.runs.first()
        self.assertEqual(run.status, 'error')
        self.assertIsNone(run.base_score)
        with self.assertRaises(ValidationError):
            make_revision(self.teacher, self.a)
        self.assertFalse(GradeRevision.objects.exists())

    def test_grades_best_and_immutable_published_snapshot(self):
        first = self.submit()
        self.finish(first, 100)
        second = self.submit(now=self.now + timedelta(seconds=11))
        self.finish(second, 0)
        revision = make_revision(self.teacher, self.a)
        self.assertEqual(revision.students.get().total, 100)
        publish_grades(self.teacher, revision)
        self.student.full_name = '改名'
        self.student.save()
        set_membership(self.admin, self.c, self.student, False)
        self.assertEqual(revision.students.get().name_snapshot, 'student')
        self.client.force_login(self.student)
        self.assertContains(self.client.get('/my-grades/'), '100.00')

    def test_latest_selection(self):
        self.rule.selection = 'latest'
        self.rule.save()
        first = self.submit()
        self.finish(first, 100)
        second = self.submit(now=self.now + timedelta(seconds=11))
        self.finish(second, 0)
        revision = make_revision(self.teacher, self.a)
        self.assertEqual(revision.students.get().total, 0)

    def test_changed_problem_requires_rejudge(self):
        sub = self.submit()
        self.finish(sub)
        new = ProblemVersion.objects.create(
            problem=self.p.problem,
            number=2,
            title='新版本',
            statement='x',
            input_format='x',
            output_format='x',
            data_range='x',
            reference_path=self.p.reference_path,
            reference_verified=True,
        )
        TestCase.objects.create(
            version=new, order=1, input_path=save_private('2 3'), output_path=save_private('5')
        )
        rule = SubmissionRuleVersion.objects.create(
            assignment=self.a, number=2, opens_at=self.rule.opens_at, deadline=self.rule.deadline
        )
        version = AssignmentVersion.objects.create(
            assignment=self.a, number=2, title='新作业版本', rule=rule
        )
        AssignmentQuestion.objects.create(
            version=version, question_key='P1', problem_version=new, max_score=100
        )
        publish_assignment(self.teacher, version)
        with self.assertRaises(ValidationError):
            make_revision(self.teacher, self.a)

    def test_rejudge_roster_frozen_before_publish(self):
        sub = self.submit()
        self.finish(sub)
        revision = make_revision(self.teacher, self.a, rejudge=True)
        self.student.full_name = '新姓名'
        self.student.save()
        set_membership(self.admin, self.c, self.student, False)
        with patch('school.judge.run_case', return_value=CaseOutcome('AC', 2)):
            evaluate(revision.runs.first().pk)
        publish_grades(self.teacher, revision)
        self.assertEqual(revision.students.get().name_snapshot, 'student')

    def test_extensions_teacher_only_and_independent_limit(self):
        ext = ExtensionRequest.objects.create(
            student=self.student, assignment=self.a, reason='生病未完成'
        )
        start = self.rule.late_deadline + timedelta(days=1)
        with self.assertRaises(PermissionDenied):
            decide_extension(self.assistant, ext, True, start, start + timedelta(days=1))
        decide_extension(
            self.teacher,
            ext,
            True,
            start,
            start + timedelta(days=1),
            attempts=1,
            penalty=Decimal('.2'),
        )
        sub = self.submit(now=start)
        self.assertEqual(sub.kind, 'extension')
        self.assertEqual(final_score(self.finish(sub)), Decimal('80.00'))
        with self.assertRaises(ValidationError):
            self.submit(now=start + timedelta(seconds=11))

    def test_overlapping_extension_rejected(self):
        one = ExtensionRequest.objects.create(student=self.student, assignment=self.a, reason='one')
        two = ExtensionRequest.objects.create(student=self.student, assignment=self.a, reason='two')
        decide_extension(self.teacher, one, True, self.now, self.now + timedelta(days=3))
        with self.assertRaises(ValidationError):
            decide_extension(self.teacher, two, True, self.now, self.now + timedelta(days=2))

    def test_import_preview_commit_idempotent_and_duplicates(self):
        data = b'username,full_name,student_no,class_code\nnew,New Student,N001,TEST\n'
        rows = preview_import(SimpleUploadedFile('students.csv', data))
        self.assertFalse(rows[0]['error'])
        self.assertEqual(commit_import(self.admin, rows, 'StrongInitial_2026'), 1)
        self.assertEqual(commit_import(self.admin, rows, 'StrongInitial_2026'), 0)
        duplicate = preview_import(
            SimpleUploadedFile('students.csv', data + b'new,New Student,N001,TEST\n')
        )
        self.assertTrue(duplicate[-1]['error'])
        self.assertTrue(User.objects.get(username='new').must_change_password)

    def test_first_login_force_password_change(self):
        self.student.must_change_password = True
        self.student.save()
        self.client.force_login(self.student)
        self.assertRedirects(self.client.get('/'), '/password/')

    def test_profile_cannot_grant_identity(self):
        self.client.force_login(self.student)
        response = self.client.post(
            '/profile/', {'email': 'student@example.com', 'active_role': 'admin'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.student.roles.filter(role='admin').exists())
        self.assertEqual(self.client.get('/users/').status_code, 403)

    def test_identity_switch_limits_active_operations(self):
        UserRole.objects.create(user=self.admin, role='student')
        self.client.force_login(self.admin)
        self.client.post('/profile/', {'email': '', 'active_role': 'student'})
        self.assertEqual(self.client.get('/users/').status_code, 403)
        self.client.post('/profile/', {'email': '', 'active_role': 'admin'})
        self.assertEqual(self.client.get('/users/').status_code, 200)

    def test_extension_scope_is_validated_and_frozen(self):
        ext = ExtensionRequest.objects.create(
            student=self.student, assignment=self.a, reason='补交一题'
        )
        with self.assertRaises(ValidationError):
            decide_extension(
                self.teacher,
                ext,
                True,
                self.now,
                self.now + timedelta(days=1),
                question_keys=['FOREIGN'],
            )
        decide_extension(
            self.teacher, ext, True, self.now, self.now + timedelta(days=1), question_keys=['P1']
        )
        ext.refresh_from_db()
        self.assertEqual(ext.question_keys, ['P1'])
        with self.assertRaises(ValidationError):
            decide_extension(
                self.teacher, ext, True, self.now, self.now + timedelta(days=1), question_keys=[]
            )

    def test_refund_once_and_no_revived_execution(self):
        sub = self.submit()
        run = sub.runs.first()
        run.status = 'error'
        run.error_code = 'DOCKER_UNAVAILABLE'
        run.save()
        self.client.force_login(self.admin)
        for _ in range(2):
            self.client.post('/operations/', {'action': 'refund', 'run': run.pk})
        sub.refresh_from_db()
        run.refresh_from_db()
        self.assertFalse(sub.counted)
        self.assertEqual(run.status, 'superseded')
        with patch('school.judge.run_case') as runner:
            evaluate(run.pk)
        runner.assert_not_called()
        self.assertEqual(AuditLog.objects.filter(action='judge.refund').count(), 1)

    def test_stale_running_task_becomes_system_error(self):
        from school.tasks import recover_stale

        sub = self.submit()
        JudgeRun.objects.filter(submission=sub).update(
            status='running', heartbeat=timezone.now() - timedelta(minutes=21)
        )
        recover_stale()
        self.assertEqual(sub.runs.get().status, 'error')
        self.assertIsNone(sub.runs.get().base_score)

    def test_student_cannot_admin_endpoints(self):
        self.client.force_login(self.student)
        for path in ['/users/', '/users/new/', '/users/import/', '/operations/', '/classes/new/']:
            self.assertEqual(self.client.get(path).status_code, 403, path)

    def test_all_authorized_pages_render(self):
        paths = {
            self.admin: [
                '/',
                '/classes/',
                '/users/',
                '/users/new/',
                '/users/import/',
                f'/users/{self.admin.pk}/',
                '/operations/',
                '/classes/new/',
                f'/classes/{self.c.pk}/',
                '/announcements/new/',
            ],
            self.teacher: [
                '/',
                f'/classes/{self.c.pk}/',
                f'/classes/{self.c.pk}/problems/',
                f'/classes/{self.c.pk}/problems/new/',
                f'/classes/{self.c.pk}/problems/{self.p.pk}/edit/',
                f'/classes/{self.c.pk}/assignments/new/',
                f'/assignments/{self.a.pk}/',
                f'/assignments/{self.a.pk}/grades/',
                f'/assignments/{self.a.pk}/extensions/',
            ],
            self.student: [
                '/',
                '/classes/',
                f'/assignments/{self.a.pk}/',
                f'/questions/{self.q.pk}/',
                '/my-grades/',
                '/notifications/',
                '/submissions/',
                '/password/',
            ],
        }
        for user, urls in paths.items():
            self.client.force_login(user)
            for path in urls:
                response = self.client.get(path)
                self.assertEqual(
                    response.status_code, 200, (user.username, path, response.content[:200])
                )

    def test_csrf_required_for_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post('/users/new/', {}).status_code, 403)

    def test_delete_class_cleans_legacy_graph_and_notifications(self):
        submission = self.submit()
        run = self.finish(submission)
        JudgeCaseResult.objects.create(run=run, case=self.p.cases.first(), verdict='AC')
        revision = make_revision(self.teacher, self.a)
        publish_grades(self.teacher, revision)
        self.assertTrue(Notification.objects.filter(event='grade', object_id=self.a.pk).exists())
        paths = [self.p.reference_path, submission.code_path]
        for case in self.p.cases.all():
            paths += [case.input_path, case.output_path]
        with self.captureOnCommitCallbacks(execute=True):
            self.c.delete()
        for model in (
            Problem, ProblemVersion, TestCase, Assignment, AssignmentVersion,
            SubmissionRuleVersion, AssignmentQuestion, Submission, JudgeRun,
            JudgeCaseResult, GradeRevision, StudentGrade, StudentQuestionGrade, Notification,
        ):
            self.assertFalse(model.objects.exists(), model.__name__)
        self.assertEqual(User.objects.count(), 4)
        for path in paths:
            self.assertFalse((Path(self.temp.name) / path).exists())

    def test_csv_formula_sanitization(self):
        from school.views import safe_csv

        self.assertEqual(safe_csv('=1+1'), "'=1+1")

    def test_private_storage_path_traversal_rejected(self):
        with self.assertRaises(ValidationError):
            read_private('../secrets.txt')

    def test_comparison_preserves_internal_whitespace(self):
        self.assertEqual(read_private(save_private('a\r\nb\n')), 'a\r\nb\n')
        self.assertTrue(compare_output('1 2  \r\n', '1 2\n', 'trim'))
        self.assertFalse(compare_output('1  2', '1 2', 'trim'))
        self.assertFalse(compare_output('5', '5\n', 'exact'))

    def test_login_throttle(self):
        from django.core.cache import cache

        cache.clear()
        for _ in range(10):
            self.client.post('/login/', {'username': 'missing', 'password': 'bad'})
        self.assertContains(
            self.client.post('/login/', {'username': 'missing', 'password': 'bad'}), '失败次数过多'
        )
