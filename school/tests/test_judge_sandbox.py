"""run_case 沙箱流程的单元测试：Docker 命令全部 mock，不依赖容器运行时。

真实容器行为由 RUN_DOCKER_TESTS=1 门控的 test_docker.py 覆盖。
"""

import io
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from school.judge import CaseOutcome, InfrastructureError, run_case


class FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read1(self, _size):
        return self._chunks.pop(0) if self._chunks else b''

    def close(self):
        self._chunks = []


class RecordingStdin:
    """记录写入内容且可安全关闭的 stdin 替身。"""

    def __init__(self):
        self.buffer = b''
        self.closed = False

    def write(self, data):
        self.buffer += data

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def getvalue(self):
        return self.buffer


class FakeProcess:
    def __init__(
        self,
        stdout_chunks=(),
        stderr_chunks=(),
        returncode=0,
        poll_sequence=None,
        wait_error=None,
    ):
        self.stdout = FakeStream(stdout_chunks)
        self.stderr = FakeStream(stderr_chunks)
        self.stdin = RecordingStdin()
        self.stdin_closed = False
        self._returncode = returncode
        self._poll_sequence = list(poll_sequence) if poll_sequence else []
        self._wait_error = wait_error
        self.killed = False

    @property
    def returncode(self):
        return self._returncode

    @returncode.setter
    def returncode(self, value):
        self._returncode = value

    def poll(self):
        if self._poll_sequence:
            return self._poll_sequence.pop(0)
        return self._returncode

    def wait(self, timeout=None):
        if self._wait_error is not None:
            raise self._wait_error
        return self._returncode

    def kill(self):
        self.killed = True
        self._returncode = 137
        self._poll_sequence = []

    def close_pipes(self):
        self.stdin_closed = True


@override_settings(
    JUDGE_IMAGE='python:3.12-slim',
    JUDGE_HOST_STORAGE='C:/host/storage',
    JUDGE_CONTAINER_START_GRACE_SECONDS=0.2,
)
class RunCaseTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

    def version(self, **kwargs):
        defaults = dict(
            runtime=None,
            memory_mb=64,
            time_ms=50,
            output_kb=64,
            comparison='trim',
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def docker_side_effect(self, image_rc=0, status=b'exited', oom=b'false'):
        def _run(command, **kwargs):
            if command[1] == 'image':
                return SimpleNamespace(returncode=image_rc, stdout=b'')
            if command[1] == 'inspect' and 'State.Status' in command[3]:
                return SimpleNamespace(returncode=0, stdout=status)
            if command[1] == 'inspect' and 'OOMKilled' in command[3]:
                return SimpleNamespace(returncode=0, stdout=oom)
            return SimpleNamespace(returncode=0, stdout=b'')

        return _run

    def patch_docker(self, process, **kwargs):
        return (
            mock.patch('school.judge.subprocess.run', side_effect=self.docker_side_effect(**kwargs)),
            mock.patch('school.judge.subprocess.Popen', return_value=process),
        )

    def test_image_missing_rejected(self):
        run_patch, popen_patch = self.patch_docker(FakeProcess(), image_rc=1)
        with run_patch, popen_patch as popen:
            with self.assertRaisesMessage(InfrastructureError, 'DOCKER_OR_IMAGE_UNAVAILABLE'):
                run_case('print(1)', '', '1', self.version())
        popen.assert_not_called()

    def test_docker_cli_missing_rejected(self):
        run_patch, _ = self.patch_docker(FakeProcess())
        with mock.patch(
            'school.judge.subprocess.run',
            side_effect=subprocess.TimeoutExpired(cmd='docker', timeout=10),
        ):
            with self.assertRaisesMessage(InfrastructureError, 'DOCKER_UNAVAILABLE'):
                run_case('print(1)', '', '1', self.version())

    def test_popen_failure_rejected(self):
        run_patch, _ = self.patch_docker(FakeProcess())
        with run_patch, mock.patch(
            'school.judge.subprocess.Popen', side_effect=OSError('no docker')
        ):
            with self.assertRaisesMessage(InfrastructureError, 'DOCKER_UNAVAILABLE'):
                run_case('print(1)', '', '1', self.version())

    def test_successful_ac_writes_stdin_and_uses_runtime(self):
        process = FakeProcess(stdout_chunks=[b'hello\n'], stderr_chunks=[b''])
        run_patch, popen_patch = self.patch_docker(process)
        version = self.version(runtime='sha256:abc')
        with run_patch, popen_patch as popen:
            outcome = run_case('print(input())', 'hello', 'hello', version)
        self.assertEqual(outcome.verdict, 'AC')
        self.assertEqual(outcome.stdout, 'hello\n')
        # 镜像检查使用题目版本的 runtime 而非默认镜像
        image_command = popen.call_args.args[0]
        self.assertIn('sha256:abc', image_command)
        self.assertIn('hello', process.stdin.getvalue().decode())

    def test_output_mismatch_is_wa(self):
        process = FakeProcess(stdout_chunks=[b'other\n'], stderr_chunks=[b''])
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('print(input())', 'hello', 'hello', self.version())
        self.assertEqual(outcome.verdict, 'WA')

    def test_syntax_error_is_ce(self):
        process = FakeProcess(
            stdout_chunks=[b''], stderr_chunks=[b'SyntaxError: bad'], returncode=1
        )
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('def (', '', '', self.version())
        self.assertEqual(outcome.verdict, 'CE')

    def test_runtime_error_is_re(self):
        process = FakeProcess(
            stdout_chunks=[b''], stderr_chunks=[b'ValueError: x'], returncode=1
        )
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('1/0', '', '', self.version())
        self.assertEqual(outcome.verdict, 'RE')

    def test_oom_killed_is_mle(self):
        process = FakeProcess(stdout_chunks=[b''], stderr_chunks=[b''])
        run_patch, popen_patch = self.patch_docker(process, oom=b'true')
        with run_patch, popen_patch:
            outcome = run_case('big = [0] * 10**9', '', '', self.version())
        self.assertEqual(outcome.verdict, 'MLE')

    def test_memory_error_is_mle(self):
        process = FakeProcess(stdout_chunks=[b''], stderr_chunks=[b'MemoryError'])
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('x = [0] * 10**9', '', '', self.version())
        self.assertEqual(outcome.verdict, 'MLE')

    def test_killed_by_signal_is_tle(self):
        process = FakeProcess(stdout_chunks=[b''], stderr_chunks=[b''], returncode=137)
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('while True: pass', '', '', self.version())
        self.assertEqual(outcome.verdict, 'TLE')

    def test_container_start_failed_code(self):
        process = FakeProcess(stdout_chunks=[b''], stderr_chunks=[b''], returncode=125)
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            with self.assertRaisesMessage(InfrastructureError, 'CONTAINER_START_FAILED'):
                run_case('print(1)', '', '', self.version())

    def test_oom_inspect_failure(self):
        def _run(command, **kwargs):
            if command[1] == 'image':
                return SimpleNamespace(returncode=0, stdout=b'')
            if command[1] == 'inspect' and 'OOMKilled' in command[3]:
                return SimpleNamespace(returncode=1, stdout=b'')
            return SimpleNamespace(returncode=0, stdout=b'')

        process = FakeProcess(stdout_chunks=[b''], stderr_chunks=[b''])
        with mock.patch('school.judge.subprocess.run', side_effect=_run), mock.patch(
            'school.judge.subprocess.Popen', return_value=process
        ):
            with self.assertRaisesMessage(InfrastructureError, 'CONTAINER_INSPECT_FAILED'):
                run_case('print(1)', '', '', self.version())

    def test_output_limit_is_ole(self):
        # 超过 output_kb 的输出触发 OLE；容器此时已退出，进程被强杀兜底
        process = FakeProcess(stdout_chunks=[b'x' * 4096], stderr_chunks=[b''])
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('print("x" * 5000)', '', '', self.version(output_kb=1))
        self.assertEqual(outcome.verdict, 'OLE')

    def test_time_limit_is_tle(self):
        process = FakeProcess(
            stdout_chunks=[b''],
            stderr_chunks=[b''],
            poll_sequence=[None] * 100,
        )
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case(
                'while True: pass', '', '', self.version(time_ms=1)
            )
        self.assertEqual(outcome.verdict, 'TLE')
        self.assertTrue(process.killed)

    def test_status_inspect_failure_is_start_timeout(self):
        def _run(command, **kwargs):
            if command[1] == 'image':
                return SimpleNamespace(returncode=0, stdout=b'')
            if command[1] == 'inspect' and 'State.Status' in command[3]:
                return SimpleNamespace(returncode=1, stdout=b'')
            return SimpleNamespace(returncode=0, stdout=b'')

        process = FakeProcess(stdout_chunks=[b''], stderr_chunks=[b''], poll_sequence=[None] * 100)
        with mock.patch('school.judge.subprocess.run', side_effect=_run), mock.patch(
            'school.judge.subprocess.Popen', return_value=process
        ):
            with self.assertRaisesMessage(InfrastructureError, 'CONTAINER_START_TIMEOUT'):
                run_case('while True: pass', '', '', self.version(time_ms=1))

    def test_unexpected_status_is_start_timeout(self):
        process = FakeProcess(stdout_chunks=[b''], stderr_chunks=[b''], poll_sequence=[None] * 100)
        run_patch, popen_patch = self.patch_docker(process, status=b'created')
        with run_patch, popen_patch:
            with self.assertRaisesMessage(InfrastructureError, 'CONTAINER_START_TIMEOUT'):
                run_case('while True: pass', '', '', self.version(time_ms=1))

    def test_wait_timeout_is_docker_timeout(self):
        process = FakeProcess(
            stdout_chunks=[b''], stderr_chunks=[b''], wait_error=subprocess.TimeoutExpired(cmd='w', timeout=10)
        )
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            with self.assertRaisesMessage(InfrastructureError, 'DOCKER_TIMEOUT'):
                run_case('print(1)', '', '', self.version())

    def test_broken_pipe_on_stdin_is_tolerated(self):
        # 进程提前退出时写入 stdin 会触发 BrokenPipeError，不应影响判题
        process = FakeProcess(stdout_chunks=[b'out\n'], stderr_chunks=[b''])
        process.stdin = mock.Mock()
        process.stdin.write.side_effect = BrokenPipeError('gone')
        process.stdin.close.side_effect = BrokenPipeError('gone')
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('print(1)', 'ignored', 'out', self.version())
        self.assertEqual(outcome.verdict, 'AC')

    def test_cleanup_removes_container_and_closes_pipes(self):
        process = FakeProcess(stdout_chunks=[b'1\n'], stderr_chunks=[b''])
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch as popen, mock.patch(
            'school.judge.subprocess.run', side_effect=self.docker_side_effect()
        ) as run_mock:
            run_case('print(1)', '', '1', self.version())
        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertTrue(any('rm' in command for command in commands))
        self.assertTrue(process.stdin.closed)
        self.assertTrue(
            any(arg.startswith('coursejudge-') for arg in popen.call_args.args[0])
        )

    def test_elapsed_recorded(self):
        process = FakeProcess(stdout_chunks=[b'1\n'], stderr_chunks=[b''])
        run_patch, popen_patch = self.patch_docker(process)
        with run_patch, popen_patch:
            outcome = run_case('print(1)', '', '1', self.version())
        self.assertGreaterEqual(outcome.elapsed_ms, 0)
        self.assertIsInstance(outcome, CaseOutcome)
