"""judge.py 与 tasks.py 的单元测试（不启动 Docker）。

run_case 的真实容器行为由 RUN_DOCKER_TESTS=1 门控的 test_docker.py 覆盖；
这里只测纯函数、verify_reference / evaluate 的状态机与任务派发逻辑。
"""

import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import TestCase as DjangoTestCase
from django.test import override_settings
from django.utils import timezone

from school import tasks
from school.judge import (
    CaseOutcome,
    InfrastructureError,
    compare_output,
    evaluate,
    verify_reference,
)
from school.models import (
    Assignment,
    AssignmentQuestion,
    AssignmentVersion,
    Classroom,
    JudgeRun,
    Problem,
    ProblemVersion,
    SubmissionRuleVersion,
    TestCase as TestCaseModel,
    User,
    UserRole,
)
from school.services import accept_submission, publish_assignment, set_membership, set_staff
from school.storage import save_private


def make_version(**kwargs):
    """构造一个最小可用的题目版本（不带班级依赖的轻量路径在测试内补齐）。"""
    return ProblemVersion.objects.create(**kwargs)


class CompareOutputTests(DjangoTestCase):
    def test_exact_mode_requires_identical(self):
        self.assertTrue(compare_output('a\nb\n', 'a\nb\n', 'exact'))
        self.assertFalse(compare_output('a \nb\n', 'a\nb\n', 'exact'))

    def test_trim_mode_ignores_trailing_whitespace(self):
        # trim 只去掉行尾空白与末尾换行，不处理行中间空格
        self.assertTrue(compare_output('a\t \r\nb\n\n', 'a\nb', 'trim'))
        self.assertFalse(compare_output('a\nb\nc\n', 'a\nb', 'trim'))

    def test_unknown_mode_falls_back_to_trim(self):
        self.assertTrue(compare_output('x\n', 'x', 'anything-else'))


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class VerifyReferenceTests(DjangoTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(temp.name))
        storage.enable()
        self.addCleanup(storage.disable)

        teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='t', must_change_password=False
        )
        UserRole.objects.create(user=teacher, role='teacher')
        classroom = Classroom.objects.create(code='T', name='t', term='2026')
        problem = Problem.objects.create(code='P1', classroom=classroom, created_by=teacher)
        self.version = ProblemVersion.objects.create(
            problem=problem,
            title='加法',
            statement='求和',
            reference_path=save_private('print(1)'),
        )
        TestCaseModel.objects.create(
            version=self.version,
            order=1,
            input_path=save_private('1'),
            output_path=save_private('1'),
            is_sample=False,
        )

    def test_not_configured_returns_false(self):
        self.version.reference_path = ''
        self.version.save()
        self.assertFalse(verify_reference(self.version.pk))

    def test_already_verified_short_circuits(self):
        self.version.reference_verified = True
        self.version.save()
        with mock.patch('school.judge.subprocess.run') as run:
            self.assertTrue(verify_reference(self.version.pk))
        run.assert_not_called()

    def test_docker_unavailable_records_error(self):
        with mock.patch('school.judge.subprocess.run', side_effect=OSError('no docker')):
            self.assertFalse(verify_reference(self.version.pk))
        self.version.refresh_from_db()
        self.assertIn('运行环境异常', self.version.verification_error)

    def test_image_without_sha256_rejected(self):
        fake = SimpleNamespace(returncode=0, stdout='not-a-sha')
        with mock.patch('school.judge.subprocess.run', return_value=fake):
            self.assertFalse(verify_reference(self.version.pk))
        self.version.refresh_from_db()
        self.assertIn('运行环境异常', self.version.verification_error)

    def test_no_hidden_cases_rejected(self):
        # 正常路径下 evaluation_configured 会先挡住全样例的情况；
        # 用 PropertyMock 模拟并发竞态（用例刚被删光）触达 NO_JUDGE_CASES 分支
        self.version.cases.update(is_sample=True)
        fake = SimpleNamespace(returncode=0, stdout='sha256:abc\n', text=True)
        with mock.patch(
            'school.models.ProblemVersion.evaluation_configured', new_callable=mock.PropertyMock
        ) as configured, mock.patch('school.judge.subprocess.run', return_value=fake):
            configured.return_value = True
            self.assertFalse(verify_reference(self.version.pk))
        self.version.refresh_from_db()
        self.assertIn('运行环境异常', self.version.verification_error)

    def test_failing_case_records_case_number(self):
        fake = SimpleNamespace(returncode=0, stdout='sha256:abc\n', text=True)
        with mock.patch('school.judge.subprocess.run', return_value=fake), mock.patch(
            'school.judge.run_case', return_value=CaseOutcome('WA', 1, '')
        ):
            self.assertFalse(verify_reference(self.version.pk))
        self.version.refresh_from_db()
        self.assertIn('第 1 个用例：WA', self.version.verification_error)

    def test_all_cases_pass_marks_verified(self):
        fake = SimpleNamespace(returncode=0, stdout='sha256:abc\n', text=True)
        with mock.patch('school.judge.subprocess.run', return_value=fake), mock.patch(
            'school.judge.run_case', return_value=CaseOutcome('AC', 1, '')
        ):
            self.assertTrue(verify_reference(self.version.pk))
        self.version.refresh_from_db()
        self.assertTrue(self.version.reference_verified)
        self.assertEqual(self.version.verification_error, '')
        self.assertEqual(self.version.runtime, 'sha256:abc')


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class EvaluateTests(DjangoTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(temp.name))
        storage.enable()
        self.addCleanup(storage.disable)

        admin = User.objects.create_user(
            username='a', password='SafePassword_2026', full_name='a', must_change_password=False
        )
        UserRole.objects.create(user=admin, role='admin')
        self.teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='t', must_change_password=False
        )
        UserRole.objects.create(user=self.teacher, role='teacher')
        student = User.objects.create_user(
            username='s', password='SafePassword_2026', full_name='s', must_change_password=False
        )
        UserRole.objects.create(user=student, role='student')
        classroom = Classroom.objects.create(code='T', name='t', term='2026')
        set_membership(admin, classroom, student)
        set_staff(admin, classroom, self.teacher, 'teacher', can_edit=True)
        problem = Problem.objects.create(code='P1', classroom=classroom, created_by=self.teacher)
        version = ProblemVersion.objects.create(
            problem=problem,
            title='加法',
            statement='求和',
            reference_path=save_private('print(1)'),
            reference_verified=True,
        )
        for order, (stdin, expected, sample) in enumerate(
            [('1 2', '3', True), ('2 3', '5', False)], 1
        ):
            TestCaseModel.objects.create(
                version=version,
                order=order,
                input_path=save_private(stdin),
                output_path=save_private(expected),
                is_sample=sample,
                hidden=not sample,
            )
        now = timezone.now() - timedelta(minutes=1)
        assignment = Assignment.objects.create(classroom=classroom, created_by=self.teacher)
        rule = SubmissionRuleVersion.objects.create(
            assignment=assignment,
            number=1,
            opens_at=now - timedelta(days=1),
            deadline=now + timedelta(days=1),
            late_deadline=now + timedelta(days=2),
            late_penalty=Decimal('.100'),
        )
        aversion = AssignmentVersion.objects.create(
            assignment=assignment, number=1, title='作业', rule=rule
        )
        question = AssignmentQuestion.objects.create(
            version=aversion, question_key='P1', problem_version=version, max_score=100
        )
        publish_assignment(self.teacher, aversion)
        self.submission = accept_submission(
            student, question.pk, 'print(5)', uuid.uuid4(), now
        )

    def run_for(self):
        return self.submission.runs.first()

    def test_unclaimable_run_returns_early(self):
        run = self.run_for()
        JudgeRun.objects.filter(pk=run.pk).update(status='done')
        with mock.patch('school.judge.run_case') as run_case:
            evaluate(run.pk)
        run_case.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, 'done')

    def test_no_hidden_cases_marks_error(self):
        run = self.run_for()
        run.question.problem_version.cases.update(is_sample=True)
        evaluate(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, 'error')
        self.assertEqual(run.error_code, 'NO_JUDGE_CASES')

    def test_all_pass_scores_full(self):
        run = self.run_for()
        with mock.patch(
            'school.judge.run_case', return_value=CaseOutcome('AC', 5, 'out')
        ):
            evaluate(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, 'done')
        self.assertEqual(run.verdict, 'AC')
        self.assertEqual(run.base_score, 100)
        self.assertEqual(run.results.count(), 2)

    def test_hidden_case_failure_takes_its_verdict(self):
        run = self.run_for()
        outcomes = [CaseOutcome('AC', 1), CaseOutcome('RE', 1)]
        with mock.patch('school.judge.run_case', side_effect=outcomes):
            evaluate(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, 'done')
        self.assertEqual(run.verdict, 'RE')
        self.assertEqual(run.base_score, 0)

    def test_infrastructure_error_marks_run(self):
        run = self.run_for()
        with mock.patch(
            'school.judge.run_case',
            side_effect=InfrastructureError('DOCKER_UNAVAILABLE'),
        ):
            evaluate(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, 'error')
        self.assertEqual(run.error_code, 'DOCKER_UNAVAILABLE')
        self.assertIsNone(run.base_score)

    def test_unexpected_error_marks_run_and_reraises(self):
        from school import judge as judge_module

        run = self.run_for()
        with mock.patch('school.judge.run_case', side_effect=KeyError('boom')), mock.patch.object(
            judge_module.logger, 'exception'
        ) as log_exception:
            with self.assertRaises(KeyError):
                evaluate(run.pk)
        log_exception.assert_called_once()
        run.refresh_from_db()
        self.assertEqual(run.status, 'error')
        self.assertEqual(run.error_code, 'WORKER_ERROR')


class TasksTests(DjangoTestCase):
    def test_evaluate_run_delegates(self):
        with mock.patch('school.judge.evaluate') as evaluate_mock:
            tasks.evaluate_run(7)
        evaluate_mock.assert_called_once_with(7)

    def test_verify_problem_deletes_dispatch_lock(self):
        cache.set('verify-dispatch:3', True, 60)
        with mock.patch('school.judge.verify_reference', return_value=True):
            self.assertTrue(tasks.verify_problem(3))
        self.assertIsNone(cache.get('verify-dispatch:3'))

    def test_recover_stale_requeues_and_errors(self):
        stale_queued = {'filter': mock.call()}
        with mock.patch('school.tasks.JudgeRun') as judge_run:
            judge_run.objects.filter.side_effect = [stale_queued, stale_queued]
            tasks.recover_stale()
        self.assertEqual(judge_run.objects.filter.call_count, 2)

    def test_dispatch_pending_drains_and_dispatches(self):
        with mock.patch('school.cleanup.drain_file_cleanup') as drain, mock.patch(
            'school.tasks.recover_stale'
        ) as recover, mock.patch('school.tasks.ProblemVersion') as version_mock, mock.patch(
            'school.tasks.JudgeRun'
        ) as run_mock, mock.patch(
            'school.services.dispatch_reference'
        ) as dispatch_reference, mock.patch(
            'school.services.dispatch'
        ) as dispatch, mock.patch(
            'school.tasks.dispatch_coursework'
        ) as dispatch_coursework:
            version_mock.objects.filter.return_value.exclude.return_value.distinct.return_value.values_list.return_value = [
                11,
                12,
            ]
            run_mock.objects.filter.return_value.values_list.return_value = [21]
            tasks.dispatch_pending()
        drain.assert_called_once()
        recover.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in dispatch_reference.call_args_list], [11, 12]
        )
        dispatch.assert_called_once_with(21)
        dispatch_coursework.assert_called_once()

    def test_dispatch_coursework_success(self):
        with mock.patch(
            'school.portal.grading.recover_stale'
        ) as recover, mock.patch(
            'school.models.EvaluationPackage'
        ) as package_mock, mock.patch(
            'school.models.CourseworkSubmission'
        ) as submission_mock, mock.patch(
            'school.tasks.validate_course_package.delay'
        ) as validate_delay, mock.patch(
            'school.tasks.evaluate_coursework.delay'
        ) as evaluate_delay:
            package_mock.objects.filter.return_value.exclude.return_value.values_list.return_value = [
                1
            ]
            submission_mock.objects.filter.return_value.values_list.return_value = [2]
            submission_mock.objects.filter.return_value.update.return_value = 1
            tasks.dispatch_coursework()
        recover.assert_called_once()
        validate_delay.assert_called_once_with(1)
        evaluate_delay.assert_called_once_with(2)
        # 成功路径：pending → queued 的条件更新确实发生
        submission_mock.objects.filter.assert_any_call(pk=2, status='pending')
        self.assertEqual(submission_mock.objects.filter.return_value.update.call_args.kwargs['status'], 'queued')

    def test_dispatch_coursework_delay_failure_resets_status(self):
        with mock.patch('school.portal.grading.recover_stale'), mock.patch(
            'school.models.EvaluationPackage'
        ) as package_mock, mock.patch(
            'school.models.CourseworkSubmission'
        ) as submission_mock, mock.patch(
            'school.tasks.validate_course_package.delay',
            side_effect=RuntimeError('broker down'),
        ), mock.patch(
            'school.tasks.evaluate_coursework.delay',
            side_effect=RuntimeError('broker down'),
        ):
            package_mock.objects.filter.return_value.exclude.return_value.values_list.return_value = [
                1
            ]
            package_mock.objects.filter.return_value.update.return_value = 1
            submission_mock.objects.filter.return_value.values_list.return_value = [2]
            submission_mock.objects.filter.return_value.update.return_value = 1
            tasks.dispatch_coursework()
        package_mock.objects.filter.assert_any_call(pk=1, status='validating')
        submission_mock.objects.filter.assert_any_call(pk=2, status='pending')

    def test_validate_course_package_delegates(self):
        with mock.patch('school.portal.grading.validate_package') as validate_mock:
            tasks.validate_course_package(9)
        validate_mock.assert_called_once_with(9)

    def test_evaluate_coursework_delegates(self):
        with mock.patch('school.portal.grading.evaluate') as evaluate_mock:
            tasks.evaluate_coursework(4)
        evaluate_mock.assert_called_once_with(4)
