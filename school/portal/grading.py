"""Function-package grader: uploaded code runs only in constrained Docker containers."""

import ast
import json
import logging
import uuid
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from school.judge import CaseOutcome, InfrastructureError, run_case
from school.models import (
    Coursework,
    CourseworkCaseResult,
    CourseworkSubmission,
    EvaluationPackage,
)
from school.storage import read_private

from .coursework_services import snapshot

logger = logging.getLogger(__name__)
EPSILON = 1e-6
SCORE_QUANTUM = Decimal('0.0001')


ARGUMENTS_SOURCE = r"""
def _case_args(text, argc):
    raw = ast.literal_eval(text)
    if argc == 1:
        # Legacy case files allow a trailing argument separator, e.g. 10, or [1,2],.
        # Explicit tuple literals such as (1,) remain a single tuple argument.
        if text.rstrip().endswith(',') and isinstance(raw, tuple) and len(raw) == 1:
            raw = raw[0]
        return (raw,)
    return tuple(raw)
"""


PACKER_SOURCE = r"""
def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def _pack(value):
    kind = type(value)
    if value is None:
        return {'type': 'none'}
    if kind is bool:
        return {'type': 'bool', 'value': value}
    if kind is int:
        return {'type': 'int', 'value': value}
    if kind is float:
        return {'type': 'float', 'value': value}
    if kind is complex:
        return {'type': 'complex', 'real': value.real, 'imag': value.imag}
    if kind is str:
        return {'type': 'str', 'value': value}
    if kind is list:
        return {'type': 'list', 'items': [_pack(item) for item in value]}
    if kind is tuple:
        return {'type': 'tuple', 'items': [_pack(item) for item in value]}
    if kind is set:
        items = [_pack(item) for item in value]
        return {'type': 'set', 'items': sorted(items, key=_canonical)}
    if kind is dict:
        items = [[_pack(key), _pack(item)] for key, item in value.items()]
        return {'type': 'dict', 'items': sorted(items, key=_canonical)}
    raise TypeError('unsupported return type: ' + kind.__name__)
"""


def harness(source, function, argc):
    return f"""import ast, contextlib, json, sys
{PACKER_SOURCE}
{ARGUMENTS_SOURCE}
_args = _case_args(sys.stdin.read(), {argc!r})
_namespace = {{"__name__": "course_submission"}}
with contextlib.redirect_stdout(sys.stderr):
    exec(compile({source!r}, "submission.py", "exec"), _namespace)
    _result = _namespace[{function!r}](*_args)
print(json.dumps(_pack(_result), ensure_ascii=False, sort_keys=True, separators=(',', ':')))
"""


def batch_harness(source, case_timeout_ms, submission_timeout_ms):
    """Load one student module once and evaluate every case in the same container."""
    return f"""import ast, contextlib, json, os, signal, sys, time
{PACKER_SOURCE}
{ARGUMENTS_SOURCE}

class _CaseTimeout(BaseException):
    pass

def _timeout(_signum, _frame):
    raise _CaseTimeout()

def _case(verdict, elapsed_ms, value=None):
    row = {{'verdict': verdict, 'elapsed_ms': elapsed_ms}}
    if verdict == 'OK':
        row['value'] = value
    return row

_requests = json.loads(sys.stdin.read())
_namespace = {{'__name__': 'course_submission'}}
_payload = {{'load_verdict': '', 'results': []}}
_sink = open(os.devnull, 'w')
_deadline = time.monotonic() + {submission_timeout_ms!r} / 1000
_case_timeout = {case_timeout_ms!r} / 1000
_load_started = time.perf_counter()
try:
    signal.signal(signal.SIGALRM, _timeout)
    signal.setitimer(signal.ITIMER_REAL, min(_case_timeout, max(0.001, _deadline - time.monotonic())))
    with contextlib.redirect_stdout(_sink):
        exec(compile({source!r}, 'submission.py', 'exec'), _namespace)
except _CaseTimeout:
    _payload['load_verdict'] = 'TLE'
except (SyntaxError, IndentationError):
    _payload['load_verdict'] = 'CE'
except BaseException:
    _payload['load_verdict'] = 'RE'
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)

if not _payload['load_verdict']:
    for _item in _requests:
        _rows = []
        _function = _namespace.get(_item['function'])
        for _text in _item['inputs']:
            _started = time.perf_counter()
            _remaining = _deadline - time.monotonic()
            if _remaining <= 0:
                _rows.append(_case('TLE', 0))
                continue
            if not callable(_function):
                _rows.append(_case('RE', 0))
                continue
            try:
                signal.signal(signal.SIGALRM, _timeout)
                signal.setitimer(signal.ITIMER_REAL, min(_case_timeout, _remaining))
                _args = _case_args(_text, _item['argc'])
                with contextlib.redirect_stdout(_sink):
                    _value = _pack(_function(*_args))
                _elapsed = max(0, int((time.perf_counter() - _started) * 1000))
                _rows.append(_case('OK', _elapsed, _value))
            except _CaseTimeout:
                _elapsed = max(0, int((time.perf_counter() - _started) * 1000))
                _rows.append(_case('TLE', _elapsed))
            except BaseException:
                _elapsed = max(0, int((time.perf_counter() - _started) * 1000))
                _rows.append(_case('RE', _elapsed))
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        _payload['results'].append(_rows)

_sink.close()
print(json.dumps(_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
"""


def reference_harness(source, spec):
    public_spec = [
        {'function': item['function'], 'argc': item['argc'], 'inputs': item['inputs']}
        for item in spec
    ]
    return f"""import ast, contextlib, json, sys
{PACKER_SOURCE}
{ARGUMENTS_SOURCE}
_spec = json.loads({json.dumps(public_spec, ensure_ascii=False)!r})
_namespace = {{"__name__": "course_reference"}}
_payload = {{"results": []}}
try:
    with contextlib.redirect_stdout(sys.stderr):
        exec(compile({source!r}, "gold.py", "exec"), _namespace)
        for _item in _spec:
            _answers = []
            for _order, _text in enumerate(_item["inputs"], 1):
                try:
                    _args = _case_args(_text, _item["argc"])
                    _answers.append(_pack(_namespace[_item["function"]](*_args)))
                except BaseException as _error:
                    _payload["error"] = {{
                        "function": _item["function"],
                        "order": _order,
                        "kind": type(_error).__name__,
                    }}
                    raise
            _payload["results"].append(_answers)
except BaseException as _error:
    if "error" not in _payload:
        _payload["error"] = {{"function": "gold.py", "order": 0, "kind": type(_error).__name__}}
print(json.dumps(_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
"""


def _python_values_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, float):
        return abs(actual - expected) <= EPSILON
    if isinstance(expected, complex):
        return max(abs(actual.real - expected.real), abs(actual.imag - expected.imag)) <= EPSILON
    if isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(
            _python_values_equal(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def _typed_values_equal(actual, expected):
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    kind = actual.get('type')
    if kind != expected.get('type'):
        return False
    if kind == 'float':
        return abs(actual.get('value') - expected.get('value')) <= EPSILON
    if kind == 'complex':
        return (
            max(
                abs(actual.get('real') - expected.get('real')),
                abs(actual.get('imag') - expected.get('imag')),
            )
            <= EPSILON
        )
    if kind in ('list', 'tuple'):
        left, right = actual.get('items', []), expected.get('items', [])
        return len(left) == len(right) and all(
            _typed_values_equal(a, b) for a, b in zip(left, right)
        )
    # The original scorer compares strings, sets and dictionaries exactly.
    return actual == expected


def values_equal(actual, expected):
    """Compare encoded container output; retain literal support for old stored packages."""
    try:
        left = json.loads(actual) if isinstance(actual, str) else actual
        right = json.loads(expected) if isinstance(expected, str) else expected
        if isinstance(left, dict) and 'type' in left and isinstance(right, dict):
            return _typed_values_equal(left, right)
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    try:
        left = ast.literal_eval(actual.strip()) if isinstance(actual, str) else actual
        right = ast.literal_eval(expected.strip()) if isinstance(expected, str) else expected
        return _python_values_equal(left, right)
    except (ValueError, SyntaxError, RecursionError, TypeError, MemoryError):
        return False


def grade_case(source, item, raw, expected=None):
    limits = SimpleNamespace(time_ms=2000, memory_mb=128, output_kb=64, comparison='exact')
    outcome = run_case(harness(source, item['function'], item['argc']), raw, '', limits)
    if outcome.verdict in ('AC', 'WA'):
        answer = expected if expected is not None else item.get('expected')
        outcome.verdict = (
            'AC' if answer is not None and values_equal(outcome.stdout, answer) else 'WA'
        )
    return outcome


def grade_submission(source, items):
    """Run a complete submission in one Docker container and compare results on the host."""
    case_timeout_ms = max(1, settings.COURSEWORK_CASE_TIME_MS)
    submission_timeout_ms = max(case_timeout_ms, settings.COURSEWORK_SUBMISSION_TIME_MS)
    public_spec = [
        {'function': item['function'], 'argc': item['argc'], 'inputs': item['inputs']}
        for item in items
    ]
    limits = SimpleNamespace(
        time_ms=submission_timeout_ms + case_timeout_ms + 1000,
        memory_mb=128,
        output_kb=2048,
        comparison='exact',
    )
    outcome = run_case(
        batch_harness(source, case_timeout_ms, submission_timeout_ms),
        json.dumps(public_spec, ensure_ascii=False),
        '',
        limits,
    )

    def uniform(verdict):
        return [[CaseOutcome(verdict, 0) for _input in item['inputs']] for item in items]

    if outcome.verdict not in ('AC', 'WA'):
        return uniform(outcome.verdict)
    try:
        payload = json.loads(outcome.stdout)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InfrastructureError('BATCH_OUTPUT_INVALID') from exc
    load_verdict = payload.get('load_verdict')
    if load_verdict:
        if load_verdict not in {'CE', 'RE', 'TLE'}:
            raise InfrastructureError('BATCH_LOAD_VERDICT_INVALID')
        return uniform(load_verdict)
    rows = payload.get('results')
    if not isinstance(rows, list) or len(rows) != len(items):
        raise InfrastructureError('BATCH_RESULT_COUNT_MISMATCH')
    results = []
    for item, expected, case_rows in zip(
        items, (item.get('expected', []) for item in items), rows, strict=True
    ):
        if len(expected) != len(item['inputs']):
            raise InfrastructureError('EXPECTED_RESULTS_UNAVAILABLE')
        if not isinstance(case_rows, list) or len(case_rows) != len(item['inputs']):
            raise InfrastructureError('BATCH_CASE_COUNT_MISMATCH')
        item_results = []
        for answer, row in zip(expected, case_rows, strict=True):
            if not isinstance(row, dict):
                raise InfrastructureError('BATCH_CASE_INVALID')
            verdict = row.get('verdict')
            elapsed_ms = max(0, int(row.get('elapsed_ms', 0)))
            if verdict == 'OK':
                verdict = 'AC' if values_equal(row.get('value'), answer) else 'WA'
            elif verdict not in {'CE', 'RE', 'TLE', 'MLE', 'OLE'}:
                raise InfrastructureError('BATCH_CASE_VERDICT_INVALID')
            item_results.append(
                CaseOutcome(
                    verdict,
                    elapsed_ms,
                    json.dumps(row['value'], ensure_ascii=False) if 'value' in row else '',
                )
            )
        results.append(item_results)
    return results


def _package_error(package_id, message):
    EvaluationPackage.objects.filter(pk=package_id, status='validating').update(
        status='error', validation_error=message[:240], validated_at=None
    )
    from .package_update_services import mark_package_updates_error

    mark_package_updates_error(package_id, message)


def validate_package(package_id):
    """Run a trusted package reference once, then atomically publish expected values."""
    if not EvaluationPackage.objects.filter(pk=package_id, status='pending').update(
        status='validating', validation_error='', validated_at=timezone.now()
    ):
        return False
    from .package_update_services import mark_package_updates_validating

    mark_package_updates_validating(package_id)
    package = EvaluationPackage.objects.get(pk=package_id)
    try:
        reference = read_private(package.reference_path)
        limits = SimpleNamespace(time_ms=30000, memory_mb=256, output_kb=2048, comparison='exact')
        outcome = run_case(reference_harness(reference, package.spec), '', '', limits)
        if outcome.verdict not in ('AC', 'WA'):
            raise InfrastructureError('REFERENCE_' + outcome.verdict)
        try:
            payload = json.loads(outcome.stdout)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InfrastructureError('REFERENCE_OUTPUT_INVALID') from exc
        if payload.get('error'):
            error = payload['error']
            _package_error(
                package_id,
                f'{error.get("function")} 第 {error.get("order")} 条用例：{error.get("kind")}',
            )
            return False
        if len(payload.get('results', [])) != len(package.spec):
            raise InfrastructureError('REFERENCE_RESULT_COUNT_MISMATCH')
        spec = deepcopy(package.spec)
        for item, expected in zip(spec, payload['results'], strict=True):
            if len(expected) != len(item['inputs']):
                raise InfrastructureError('REFERENCE_CASE_COUNT_MISMATCH')
            item['expected'] = expected
        with transaction.atomic():
            locked = EvaluationPackage.objects.select_for_update().get(pk=package_id)
            if locked.status != 'validating':
                return False
            locked.spec = spec
            locked.status = 'ready'
            locked.validation_error = ''
            locked.validated_at = timezone.now()
            locked.save(update_fields=['spec', 'status', 'validation_error', 'validated_at'])
            for work in Coursework.objects.select_related('package').filter(package=locked):
                state = snapshot(work)
                for entry in work.entries.filter(status='waiting'):
                    entry.snapshot = state
                    entry.status = 'pending'
                    entry.error = ''
                    entry.save(update_fields=['snapshot', 'status', 'error'])
                    entry.questions.update(verdict='PENDING', score=None)
        from .package_update_services import activate_ready_package_updates

        activate_ready_package_updates(package_id)
        return True
    except Exception as exc:  # noqa: BLE001 -- package validation boundary
        code = str(exc) if isinstance(exc, InfrastructureError) else 'REFERENCE_VALIDATION_FAILED'
        logger.warning('Course package validation failed: package=%s code=%s', package_id, code)
        _package_error(package_id, code)
        return False


def evaluate(entry_id):
    token = uuid.uuid4()
    if not CourseworkSubmission.objects.filter(
        pk=entry_id, status__in=['pending', 'queued']
    ).update(status='running', worker_token=token, heartbeat=timezone.now(), total=None, error=''):
        return
    entry = CourseworkSubmission.objects.get(pk=entry_id)
    owned = CourseworkSubmission.objects.filter(pk=entry_id, status='running', worker_token=token)
    try:
        if not entry.snapshot.get('ready'):
            owned.update(status='waiting')
            return
        source = read_private(entry.source_path)
        items = entry.snapshot['items']
        questions = list(entry.questions.all())
        if len(questions) != len(items):
            raise InfrastructureError('QUESTION_COUNT_MISMATCH')
        for item in items:
            if len(item.get('expected', [])) != len(item['inputs']):
                raise InfrastructureError('EXPECTED_RESULTS_UNAVAILABLE')
        if not owned.update(heartbeat=timezone.now()):
            return
        outcomes = grade_submission(source, items)
        if not owned.update(heartbeat=timezone.now()):
            return
        results = []
        for question, item, item_outcomes in zip(questions, items, outcomes, strict=True):
            cases = []
            for order, outcome in enumerate(item_outcomes, 1):
                cases.append(
                    CourseworkCaseResult(
                        question=question,
                        order=order,
                        verdict=outcome.verdict,
                        elapsed_ms=outcome.elapsed_ms,
                        actual_output=outcome.stdout[:65536],
                    )
                )
            passed = sum(case.verdict == 'AC' for case in cases)
            total_cases = len(cases)
            score = (Decimal(item['points']) * Decimal(passed) / Decimal(total_cases)).quantize(
                SCORE_QUANTUM, rounding=ROUND_HALF_UP
            )
            verdict = next((case.verdict for case in cases if case.verdict != 'AC'), 'AC')
            results.append((question, verdict, score, passed, total_cases, cases))
        with transaction.atomic():
            if not owned.select_for_update().exists():
                return
            CourseworkCaseResult.objects.filter(question__submission=entry).delete()
            for question, verdict, score, passed, total_cases, cases in results:
                question.verdict = verdict
                question.score = score
                question.passed_cases = passed
                question.total_cases = total_cases
                question.save(update_fields=['verdict', 'score', 'passed_cases', 'total_cases'])
                CourseworkCaseResult.objects.bulk_create(cases)
            owned.update(
                status='done',
                total=sum((result[2] for result in results), Decimal(0)),
                error='',
                finished_at=timezone.now(),
            )
    except Exception as exc:  # noqa: BLE001 -- worker boundary must leave a retriable state
        code = str(exc)[:200] if isinstance(exc, InfrastructureError) else 'GRADING_FAILED'
        logger.warning('Coursework grading failed: entry=%s code=%s', entry_id, code)
        with transaction.atomic():
            if owned.select_for_update().exists():
                entry.questions.update(score=None, verdict='ERROR', passed_cases=0, total_cases=0)
                owned.update(status='error', total=None, error=code, finished_at=timezone.now())


def recover_stale():
    CourseworkSubmission.objects.filter(
        status='queued', heartbeat__lt=timezone.now() - timezone.timedelta(minutes=5)
    ).update(status='pending')
    CourseworkSubmission.objects.filter(
        status='running', heartbeat__lt=timezone.now() - timezone.timedelta(minutes=20)
    ).update(status='error', total=None, error='WORKER_LOST', finished_at=timezone.now())
    stale_packages = list(
        EvaluationPackage.objects.filter(
        status='validating',
        validated_at__lt=timezone.now() - timezone.timedelta(minutes=20),
        ).values_list('pk', flat=True)
    )
    if stale_packages:
        EvaluationPackage.objects.filter(pk__in=stale_packages).update(
            status='pending', validation_error='', validated_at=None
        )
        from school.models import CourseworkPackageUpdate

        CourseworkPackageUpdate.objects.filter(
            package_id__in=stale_packages, status='validating'
        ).update(status='pending')

    from .package_update_services import activate_ready_package_updates

    ready_updates = (
        EvaluationPackage.objects.filter(
            status='ready', package_updates__status__in=['pending', 'validating']
        )
        .distinct()
        .values_list('pk', flat=True)
    )
    for package_id in ready_updates:
        activate_ready_package_updates(package_id)
