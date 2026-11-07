"""批量函数判题（grading.py）的单元测试：run_case 全部 mock，不启动 Docker。"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from school.course_models import (
    Coursework,
    CourseworkCaseResult,
    CourseworkPackageUpdate,
    CourseworkQuestionResult,
    CourseworkSubmission,
    EvaluationPackage,
)
from school.judge import CaseOutcome, InfrastructureError
from school.models import Classroom, User, UserRole
from school.portal import grading
from school.storage import save_private


def packed(value_type, **kwargs):
    return json.dumps({'type': value_type, **kwargs}, ensure_ascii=False)


class PythonValuesEqualTests(TestCase):
    def test_type_mismatch(self):
        self.assertFalse(grading._python_values_equal(1, '1'))

    def test_float_epsilon(self):
        self.assertTrue(grading._python_values_equal(1.0, 1.0 + 1e-9))
        self.assertFalse(grading._python_values_equal(1.0, 1.1))

    def test_complex_epsilon(self):
        self.assertTrue(grading._python_values_equal(1 + 2j, 1 + 2j + 1e-9))
        self.assertFalse(grading._python_values_equal(1 + 2j, 1 + 3j))

    def test_containers_elementwise(self):
        # 类型严格：容器类型不同即不相等
        self.assertFalse(grading._python_values_equal([1.0, (2,)], (1.0, [2])))
        self.assertFalse(grading._python_values_equal([1, 2], (1, 2)))
        self.assertFalse(grading._python_values_equal([1, 2], [1, 2, 3]))
        self.assertTrue(grading._python_values_equal([1.0 + 1e-9, 2], [1.0, 2]))

    def test_exact_equality(self):
        self.assertTrue(grading._python_values_equal({'a': 1}, {'a': 1}))
        self.assertFalse(grading._python_values_equal({'a': 1}, {'a': 2}))


class TypedValuesEqualTests(TestCase):
    def test_non_dict_rejected(self):
        self.assertFalse(grading._typed_values_equal([1], [1]))

    def test_type_mismatch(self):
        self.assertFalse(
            grading._typed_values_equal({'type': 'int'}, {'type': 'float', 'value': 1})
        )

    def test_float_epsilon(self):
        left = {'type': 'float', 'value': 1.0}
        right = {'type': 'float', 'value': 1.0 + 1e-9}
        self.assertTrue(grading._typed_values_equal(left, right))

    def test_complex_epsilon(self):
        left = {'type': 'complex', 'real': 1, 'imag': 2}
        right = {'type': 'complex', 'real': 1 + 1e-9, 'imag': 2}
        self.assertTrue(grading._typed_values_equal(left, right))

    def test_list_length_mismatch(self):
        left = {'type': 'list', 'items': [{'type': 'int', 'value': 1}]}
        right = {'type': 'list', 'items': []}
        self.assertFalse(grading._typed_values_equal(left, right))

    def test_exact_strings_sets_dicts(self):
        self.assertTrue(grading._typed_values_equal({'type': 'str'}, {'type': 'str'}))
        self.assertFalse(
            grading._typed_values_equal(
                {'type': 'str', 'value': 'a'}, {'type': 'str', 'value': 'b'}
            )
        )


class ValuesEqualTests(TestCase):
    def test_packed_json_strings(self):
        self.assertTrue(grading.values_equal(packed('int', value=3), packed('int', value=3)))
        self.assertFalse(grading.values_equal(packed('int', value=3), packed('int', value=4)))

    def test_literal_fallback(self):
        # 字面量回退比较沿用原打分器语义：元素类型严格、元组与列表不同
        self.assertTrue(grading.values_equal('[1, 2]', '[1, 2]'))
        self.assertFalse(grading.values_equal('(1, 2)', '[1, 2]'))

    def test_garbage_falls_back_false(self):
        self.assertFalse(grading.values_equal('not-a-value', 'also-not'))

    def test_direct_dicts(self):
        self.assertTrue(grading.values_equal({'type': 'none'}, {'type': 'none'}))


class GradeCaseTests(TestCase):
    def test_ac_when_matches_expected(self):
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 5, packed('int', value=3))
        ):
            outcome = grading.grade_case(
                'source', {'function': 'f', 'argc': 1, 'expected': packed('int', value=3)}, '[1]'
            )
        self.assertEqual(outcome.verdict, 'AC')

    def test_wa_when_mismatch(self):
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 5, packed('int', value=4))
        ):
            outcome = grading.grade_case(
                'source', {'function': 'f', 'argc': 1, 'expected': packed('int', value=3)}, '[1]'
            )
        self.assertEqual(outcome.verdict, 'WA')

    def test_other_verdict_passthrough(self):
        with mock.patch.object(grading, 'run_case', return_value=CaseOutcome('TLE', 5, '')):
            outcome = grading.grade_case('source', {'function': 'f', 'argc': 1}, '[1]')
        self.assertEqual(outcome.verdict, 'TLE')


def items_for_grade():
    return [
        {
            'function': 'func301',
            'argc': 2,
            'inputs': ['[1, 2]'],
            'expected': [packed('int', value=3)],
            'points': 10,
        },
        {
            'function': 'func302',
            'argc': 1,
            'inputs': ['[1]', '[2]'],
            'expected': [packed('int', value=1), packed('int', value=2)],
            'points': 10,
        },
    ]


class GradeSubmissionTests(TestCase):
    def test_non_ac_verdict_uniform(self):
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('CE', 1, '')
        ):
            results = grading.grade_submission('src', items_for_grade())
        self.assertEqual(results[0][0].verdict, 'CE')
        self.assertEqual(len(results[1]), 2)

    def test_invalid_batch_output(self):
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, 'not json')
        ):
            with self.assertRaisesMessage(InfrastructureError, 'BATCH_OUTPUT_INVALID'):
                grading.grade_submission('src', items_for_grade())

    def test_load_verdict_uniform(self):
        stdout = json.dumps({'load_verdict': 'TLE'})
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            results = grading.grade_submission('src', items_for_grade())
        self.assertEqual(results[0][0].verdict, 'TLE')

    def test_invalid_load_verdict(self):
        stdout = json.dumps({'load_verdict': 'XX'})
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            with self.assertRaisesMessage(InfrastructureError, 'BATCH_LOAD_VERDICT_INVALID'):
                grading.grade_submission('src', items_for_grade())

    def test_result_count_mismatch(self):
        stdout = json.dumps({'results': []})
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            with self.assertRaisesMessage(InfrastructureError, 'BATCH_RESULT_COUNT_MISMATCH'):
                grading.grade_submission('src', items_for_grade())

    def test_expected_unavailable(self):
        items = items_for_grade()
        items[0].pop('expected')
        stdout = json.dumps(
            {
                'results': [
                    [{'verdict': 'OK', 'value': {'type': 'int', 'value': 3}}],
                    [{'verdict': 'OK'}, {'verdict': 'OK'}],
                ]
            }
        )
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            with self.assertRaisesMessage(InfrastructureError, 'EXPECTED_RESULTS_UNAVAILABLE'):
                grading.grade_submission('src', items)

    def test_case_count_mismatch(self):
        stdout = json.dumps(
            {'results': [[{'verdict': 'OK'}], [{'verdict': 'OK'}]]}
        )
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            with self.assertRaisesMessage(InfrastructureError, 'BATCH_CASE_COUNT_MISMATCH'):
                grading.grade_submission('src', items_for_grade())

    def test_invalid_row_rejected(self):
        stdout = json.dumps(
            {'results': [['row'], [{'verdict': 'OK'}, {'verdict': 'OK'}]]}
        )
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            with self.assertRaisesMessage(InfrastructureError, 'BATCH_CASE_INVALID'):
                grading.grade_submission('src', items_for_grade())

    def test_unknown_case_verdict_rejected(self):
        rows = [[{'verdict': 'XX'}], [{'verdict': 'OK'}, {'verdict': 'OK'}]]
        stdout = json.dumps({'results': rows})
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            with self.assertRaisesMessage(InfrastructureError, 'BATCH_CASE_VERDICT_INVALID'):
                grading.grade_submission('src', items_for_grade())

    def test_success_mixed_verdicts(self):
        rows = [
            [{'verdict': 'OK', 'value': {'type': 'int', 'value': 3}, 'elapsed_ms': 4}],
            [
                {'verdict': 'OK', 'value': {'type': 'int', 'value': 1}},
                {'verdict': 'RE'},
            ],
        ]
        stdout = json.dumps({'results': rows})
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, stdout)
        ):
            results = grading.grade_submission('src', items_for_grade())
        self.assertEqual(results[0][0].verdict, 'AC')
        self.assertEqual(results[0][0].elapsed_ms, 4)
        self.assertEqual(results[1][0].verdict, 'AC')
        self.assertEqual(results[1][1].verdict, 'RE')


@override_settings(PRIVATE_STORAGE=None)
class ValidatePackageTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)
        self.teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='教师', must_change_password=False
        )
        UserRole.objects.create(user=self.teacher, role='teacher')
        self.package = EvaluationPackage.objects.create(
            code='chapter-01',
            name='第一章',
            reference_path=save_private('def f():\n    pass\n'),
            spec=[{'function': 'func301', 'argc': 2, 'inputs': ['[1, 2]']}],
            digest='d' * 64,
            status='pending',
        )

    def set_stdout(self, value):
        return mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('AC', 1, value)
        )

    def test_non_pending_package_skipped(self):
        EvaluationPackage.objects.filter(pk=self.package.pk).update(status='ready')
        self.assertFalse(grading.validate_package(self.package.pk))

    def test_success_publishes_expected(self):
        stdout = json.dumps({'results': [[{'type': 'int', 'value': 3}]]})
        with self.set_stdout(stdout):
            self.assertTrue(grading.validate_package(self.package.pk))
        self.package.refresh_from_db()
        self.assertEqual(self.package.status, 'ready')
        self.assertEqual(
            self.package.spec[0]['expected'][0], {'type': 'int', 'value': 3}
        )

    def test_reference_runtime_error_marks_package(self):
        with mock.patch.object(
            grading, 'run_case', return_value=CaseOutcome('TLE', 1, '')
        ):
            self.assertFalse(grading.validate_package(self.package.pk))
        self.package.refresh_from_db()
        self.assertEqual(self.package.status, 'error')
        self.assertIn('REFERENCE_TLE', self.package.validation_error)

    def test_invalid_reference_output(self):
        with self.set_stdout('not json'):
            self.assertFalse(grading.validate_package(self.package.pk))
        self.package.refresh_from_db()
        self.assertIn('REFERENCE_OUTPUT_INVALID', self.package.validation_error)

    def test_reference_case_error_recorded(self):
        stdout = json.dumps(
            {'error': {'function': 'func301', 'order': 1, 'kind': 'ZeroDivisionError'}}
        )
        with self.set_stdout(stdout):
            self.assertFalse(grading.validate_package(self.package.pk))
        self.package.refresh_from_db()
        self.assertIn('func301 第 1 条用例', self.package.validation_error)

    def test_result_count_mismatch(self):
        stdout = json.dumps({'results': []})
        with self.set_stdout(stdout):
            self.assertFalse(grading.validate_package(self.package.pk))
        self.package.refresh_from_db()
        self.assertIn('REFERENCE_RESULT_COUNT_MISMATCH', self.package.validation_error)

    def test_case_count_mismatch(self):
        stdout = json.dumps({'results': [[]]})
        with self.set_stdout(stdout):
            self.assertFalse(grading.validate_package(self.package.pk))
        self.package.refresh_from_db()
        self.assertIn('REFERENCE_CASE_COUNT_MISMATCH', self.package.validation_error)

    def test_locked_race_returns_false(self):
        stdout = json.dumps({'results': [[packed('int', value=3)]]})
        with self.set_stdout(stdout), mock.patch.object(
            EvaluationPackage.objects, 'select_for_update'
        ) as select_for_update:
            select_for_update.return_value.get.return_value = SimpleNamespace(
                status='ready'
            )
            self.assertFalse(grading.validate_package(self.package.pk))


class EvaluateEntryTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)
        self.student = User.objects.create_user(
            username='s', password='SafePassword_2026', full_name='学生', must_change_password=False
        )
        UserRole.objects.create(user=self.student, role='student')
        self.teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='教师', must_change_password=False
        )
        UserRole.objects.create(user=self.teacher, role='teacher')
        classroom = Classroom.objects.create(code='G1', name='批阅班', course_name='Python', term='2026')
        self.work = Coursework.objects.create(
            classroom=classroom,
            owner=self.teacher,
            title='批量作业',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        self.entry = CourseworkSubmission.objects.create(
            coursework=self.work,
            student=self.student,
            sequence=1,
            source_path=save_private('def func301(a, b):\n    return a + b\n'),
            source_hash='h' * 64,
            snapshot={
                'ready': True,
                'items': [
                    {
                        'function': 'func301',
                        'argc': 2,
                        'inputs': ['[1, 2]'],
                        'expected': [packed('int', value=3)],
                        'points': 10,
                    }
                ],
            },
            status='pending',
        )
        self.question = CourseworkQuestionResult.objects.create(
            submission=self.entry,
            function_name='func301',
            title='合并两个列表',
            order=1,
            points=10,
        )

    def batch_stdout(self, value=packed('int', value=3), verdict='OK'):
        rows = [[{'verdict': verdict, 'value': json.loads(value), 'elapsed_ms': 3}]]
        return json.dumps({'results': rows})

    def test_non_pending_entry_skipped(self):
        CourseworkSubmission.objects.filter(pk=self.entry.pk).update(status='done')
        grading.evaluate(self.entry.pk)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'done')

    def test_not_ready_waits(self):
        CourseworkSubmission.objects.filter(pk=self.entry.pk).update(
            status='pending', snapshot={'ready': False}
        )
        grading.evaluate(self.entry.pk)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'waiting')

    def test_question_count_mismatch_marks_error(self):
        CourseworkQuestionResult.objects.all().delete()
        grading.evaluate(self.entry.pk)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'error')
        self.assertEqual(self.entry.error, 'QUESTION_COUNT_MISMATCH')

    def test_expected_unavailable_marks_error(self):
        CourseworkSubmission.objects.filter(pk=self.entry.pk).update(
            snapshot={
                'ready': True,
                'items': [{'function': 'func301', 'argc': 2, 'inputs': ['[1, 2]']}],
            }
        )
        grading.evaluate(self.entry.pk)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'error')
        self.assertEqual(self.entry.error, 'EXPECTED_RESULTS_UNAVAILABLE')

    def test_success_scores_and_persists_cases(self):
        with mock.patch.object(
            grading, 'grade_submission', return_value=[[CaseOutcome('AC', 3, packed('int', value=3))]]
        ) as grade_mock:
            grading.evaluate(self.entry.pk)
        grade_mock.assert_called_once()
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'done')
        self.assertEqual(self.entry.total, Decimal('10.0000'))
        self.question.refresh_from_db()
        self.assertEqual(self.question.verdict, 'AC')
        self.assertEqual(self.question.score, Decimal('10.0000'))
        self.assertEqual(self.question.passed_cases, 1)
        self.assertEqual(self.question.cases.count(), 1)
        case = self.question.cases.first()
        self.assertEqual(case.verdict, 'AC')
        self.assertEqual(case.elapsed_ms, 3)

    def test_partial_pass_scores_by_ratio(self):
        self.question.total_cases = 0
        with mock.patch.object(
            grading, 'grade_submission', return_value=[[CaseOutcome('WA', 3, '')]]
        ):
            grading.evaluate(self.entry.pk)
        self.question.refresh_from_db()
        self.assertEqual(self.question.verdict, 'WA')
        self.assertEqual(self.question.score, Decimal('0.0000'))

    def test_infrastructure_error_marks_entry(self):
        with mock.patch.object(
            grading, 'grade_submission', side_effect=InfrastructureError('DOCKER_UNAVAILABLE')
        ):
            grading.evaluate(self.entry.pk)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'error')
        self.assertEqual(self.entry.error, 'DOCKER_UNAVAILABLE')
        self.question.refresh_from_db()
        self.assertEqual(self.question.verdict, 'ERROR')

    def test_unexpected_error_uses_generic_code(self):
        with mock.patch.object(grading, 'grade_submission', side_effect=KeyError('x')):
            grading.evaluate(self.entry.pk)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'error')
        self.assertEqual(self.entry.error, 'GRADING_FAILED')


class RecoverStaleTests(TestCase):
    def test_requeues_stale_states(self):
        teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='教师', must_change_password=False
        )
        UserRole.objects.create(user=teacher, role='teacher')
        classroom = Classroom.objects.create(code='R2', name='恢复班', course_name='Python', term='2026')
        work = Coursework.objects.create(
            classroom=classroom,
            owner=teacher,
            title='恢复作业',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        old = timezone.now() - timezone.timedelta(minutes=30)
        queued = CourseworkSubmission.objects.create(
            coursework=work,
            student=teacher,
            sequence=1,
            source_path='x',
            source_hash='h',
            status='queued',
            heartbeat=old,
        )
        running = CourseworkSubmission.objects.create(
            coursework=work,
            student=teacher,
            sequence=2,
            source_path='x',
            source_hash='h',
            status='running',
            heartbeat=old,
        )
        package = EvaluationPackage.objects.create(
            code='chapter-09',
            name='第九章',
            digest='e' * 64,
            status='validating',
            validated_at=old,
        )
        CourseworkPackageUpdate.objects.create(
            coursework=work, package=package, status='validating'
        )
        grading.recover_stale()
        queued.refresh_from_db()
        running.refresh_from_db()
        package.refresh_from_db()
        self.assertEqual(queued.status, 'pending')
        self.assertEqual(running.status, 'error')
        self.assertEqual(running.error, 'WORKER_LOST')
        self.assertEqual(package.status, 'pending')
