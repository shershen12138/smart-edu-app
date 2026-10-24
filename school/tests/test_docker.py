import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings

from school.judge import run_case


@skipUnless(os.getenv('RUN_DOCKER_TESTS') == '1', '设置 RUN_DOCKER_TESTS=1 后运行真实 Docker 验收')
class DockerTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(
            PRIVATE_STORAGE=Path(self.temp.name), JUDGE_HOST_STORAGE=self.temp.name
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.version = SimpleNamespace(time_ms=1000, memory_mb=64, output_kb=8, comparison='trim')

    def check_case(self, code, stdin, expected, verdict):
        result = run_case(code, stdin, expected, self.version)
        self.assertEqual(result.verdict, verdict)

    def test_correct(self):
        self.check_case('a,b=map(int,input().split());print(a+b)', '2 3\n', '5\n', 'AC')

    def test_wrong(self):
        self.check_case('print(4)', '', '5\n', 'WA')

    def test_function_adapter_correct(self):
        from school.portal.grading import grade_submission

        results = grade_submission(
            'calls = 0\ndef func1(x):\n global calls\n calls += 1\n return calls',
            [
                {
                    'function': 'func1',
                    'argc': 1,
                    'inputs': ['0', '0'],
                    'expected': [
                        {'type': 'int', 'value': 1},
                        {'type': 'int', 'value': 2},
                    ],
                }
            ],
        )
        self.assertEqual([case.verdict for case in results[0]], ['AC', 'AC'])

    def test_function_adapter_wrong_and_missing_function(self):
        from school.portal.grading import grade_submission

        results = grade_submission(
            'def func1(x): return x',
            [
                {
                    'function': 'func1',
                    'argc': 1,
                    'inputs': ['1'],
                    'expected': [{'type': 'int', 'value': 2}],
                },
                {
                    'function': 'func2',
                    'argc': 1,
                    'inputs': ['1'],
                    'expected': [{'type': 'int', 'value': 2}],
                },
            ],
        )
        self.assertEqual(results[0][0].verdict, 'WA')
        self.assertEqual(results[1][0].verdict, 'RE')

    def test_legacy_argument_separator_preserves_container_arguments(self):
        from school.portal.grading import grade_submission, harness, reference_harness

        source = 'def kind(value): return type(value).__name__'
        cases = [
            ('10,', 'int'),
            ('"hello",', 'str'),
            ('[1, 2],', 'list'),
            ("{'x': 1},", 'dict'),
            ('(1, 2),', 'tuple'),
            ('(1,), ', 'tuple'),
            ('(1,)', 'tuple'),
            ('(1, 2)', 'tuple'),
            ('[1]', 'list'),
            ('1', 'int'),
        ]
        expected = [{'type': 'str', 'value': kind} for _, kind in cases]
        items = [{'function': 'kind', 'argc': 1, 'inputs': [raw for raw, _ in cases]}]
        reference = run_case(reference_harness(source, items), '', '', self.version)
        self.assertIn(reference.verdict, ('AC', 'WA'))
        self.assertEqual(json.loads(reference.stdout), {'results': [expected]})
        items[0]['expected'] = expected
        results = grade_submission(source, items)
        self.assertEqual([case.verdict for case in results[0]], ['AC'] * len(cases))
        single = run_case(harness(source, 'kind', 1), '10,', '', self.version)
        self.assertIn(single.verdict, ('AC', 'WA'))
        self.assertEqual(json.loads(single.stdout), expected[0])

    def test_function_adapter_case_timeout_continues_in_same_container(self):
        from school.portal.grading import grade_submission

        with override_settings(COURSEWORK_CASE_TIME_MS=100, COURSEWORK_SUBMISSION_TIME_MS=2000):
            results = grade_submission(
                'def slow(x):\n while True: pass\ndef quick(x): return x + 1',
                [
                    {
                        'function': 'slow',
                        'argc': 1,
                        'inputs': ['1'],
                        'expected': [{'type': 'int', 'value': 1}],
                    },
                    {
                        'function': 'quick',
                        'argc': 1,
                        'inputs': ['1'],
                        'expected': [{'type': 'int', 'value': 2}],
                    },
                ],
            )
        self.assertEqual(results[0][0].verdict, 'TLE')
        self.assertEqual(results[1][0].verdict, 'AC')

    def test_syntax(self):
        self.check_case('if :', '', '', 'CE')

    def test_runtime(self):
        self.check_case('raise ValueError()', '', '', 'RE')

    def test_timeout(self):
        self.check_case('while True: pass', '', '', 'TLE')

    def test_output_limit(self):
        self.check_case('print("x"*100000)', '', '', 'OLE')

    def test_memory_limit(self):
        self.check_case('x=bytearray(256*1024*1024)', '', '', 'MLE')

    def test_no_network(self):
        code = 'import socket\ns=socket.socket()\ns.settimeout(0.3)\ntry:\n s.connect(("1.1.1.1",80));print("connected")\nexcept OSError:\n print("blocked")\n'
        self.check_case(code, '', 'blocked\n', 'AC')

    def test_filesystem_readonly_and_nonroot(self):
        code = 'import os\nprint(os.getuid())\ntry:\n open("/code/main.py","w").write("changed")\n print("writable")\nexcept OSError:\n print("readonly")\n'
        self.check_case(code, '', '65534\nreadonly\n', 'AC')
