"""Only Docker executes student code. There is deliberately no host-execution fallback."""

import math
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import JudgeRun, JudgeCaseResult, ProblemVersion
from .storage import read_private


class InfrastructureError(Exception):
    pass


@dataclass
class CaseOutcome:
    verdict: str
    elapsed_ms: int
    stdout: str = ''


def compare_output(actual, expected, mode):
    if mode == 'exact':
        return actual == expected

    def normalize(value):
        return '\n'.join(line.rstrip(' \t\r') for line in value.split('\n')).rstrip('\n')

    return normalize(actual) == normalize(expected)


def run_case(code, stdin, expected, version):
    runtime = getattr(version, 'runtime', None) or settings.JUDGE_IMAGE
    try:
        readiness = subprocess.run(
            ['docker', 'image', 'inspect', runtime], capture_output=True, timeout=10
        )
        if readiness.returncode:
            raise InfrastructureError('DOCKER_OR_IMAGE_UNAVAILABLE')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InfrastructureError('DOCKER_UNAVAILABLE') from exc
    name = 'coursejudge-' + uuid.uuid4().hex
    sandbox_root = settings.PRIVATE_STORAGE / 'sandbox'
    sandbox_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=sandbox_root) as directory:
        Path(directory).chmod(0o755)
        source = Path(directory) / 'main.py'
        source.write_text(code, encoding='utf-8')
        source.chmod(0o644)
        relative = Path(directory).relative_to(settings.PRIVATE_STORAGE).as_posix()
        host_dir = settings.JUDGE_HOST_STORAGE.rstrip('/\\').replace('\\', '/') + '/' + relative
        command = [
            'docker',
            'run',
            '--name',
            name,
            '--network',
            'none',
            '--read-only',
            '--cap-drop',
            'ALL',
            '--security-opt',
            'no-new-privileges',
            '--pids-limit',
            '16',
            '--cpus',
            '1',
            '--memory',
            f'{version.memory_mb}m',
            '--memory-swap',
            f'{version.memory_mb}m',
            '--ulimit',
            f'cpu={math.ceil(version.time_ms / 1000) + 1}',
            '--ulimit',
            'nofile=64:64',
            '--ulimit',
            'fsize=1048576:1048576',
            '--user',
            '65534:65534',
            '--tmpfs',
            '/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777',
            '--mount',
            f'type=bind,src={host_dir},dst=/code,readonly',
            '--workdir',
            '/tmp',
            '--log-driver',
            'none',
            '-i',
            runtime,
            'python',
            '-I',
            '-B',
            '/code/main.py',
        ]
        started = time.monotonic()
        output = bytearray()
        error = bytearray()
        exceeded = threading.Event()
        limit = version.output_kb * 1024
        process = None

        def read_stream(stream, buffer):
            while True:
                data = stream.read1(4096)
                if not data:
                    break
                room = max(0, limit - len(buffer))
                buffer.extend(data[:room])
                if len(data) > room:
                    exceeded.set()
                    break

        try:
            try:
                process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
            except OSError as exc:
                raise InfrastructureError('DOCKER_UNAVAILABLE') from exc
            readers = [
                threading.Thread(target=read_stream, args=(process.stdout, output), daemon=True),
                threading.Thread(target=read_stream, args=(process.stderr, error), daemon=True),
            ]
            for reader in readers:
                reader.start()

            def write_input():
                try:
                    process.stdin.write(stdin.encode('utf-8'))
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()
            timed_out = False
            # Docker Desktop can need several seconds to create the first bind-mounted
            # container. Keep that infrastructure delay outside the student's time budget;
            # CPU is still bounded independently by the container ulimit.
            startup_grace = max(
                1.0, float(getattr(settings, 'JUDGE_CONTAINER_START_GRACE_SECONDS', 10))
            )
            while process.poll() is None:
                if exceeded.is_set():
                    break
                if time.monotonic() - started > version.time_ms / 1000 + startup_grace:
                    timed_out = True
                    break
                time.sleep(0.02)
            if timed_out or exceeded.is_set():
                state = subprocess.run(
                    ['docker', 'inspect', '--format', '{{.State.Status}}', name],
                    capture_output=True,
                    timeout=10,
                )
                if state.returncode:
                    raise InfrastructureError('CONTAINER_START_TIMEOUT')
                status = state.stdout.strip()
                if timed_out and status not in (b'running', b'exited', b'dead'):
                    raise InfrastructureError('CONTAINER_START_TIMEOUT')
                if status == b'running':
                    subprocess.run(['docker', 'kill', name], capture_output=True, timeout=10)
                    process.kill()
                elif exceeded.is_set():
                    # The container may have exited while the Docker client is still
                    # blocked flushing output into the intentionally capped pipe.
                    process.kill()
            process.wait(timeout=10)
            for reader in readers:
                reader.join(timeout=2)
            elapsed = int((time.monotonic() - started) * 1000)
            if exceeded.is_set():
                return CaseOutcome('OLE', elapsed)
            if timed_out:
                return CaseOutcome('TLE', elapsed)
            if process.returncode in (125, 126, 127):
                raise InfrastructureError('CONTAINER_START_FAILED')
            info = subprocess.run(
                ['docker', 'inspect', '--format', '{{.State.OOMKilled}}', name],
                capture_output=True,
                timeout=10,
            )
            if info.returncode:
                raise InfrastructureError('CONTAINER_INSPECT_FAILED')
            if info.stdout.strip() == b'true' or b'MemoryError' in error:
                return CaseOutcome('MLE', elapsed)
            if timed_out or process.returncode in (137, 152):
                return CaseOutcome('TLE', elapsed)
            if process.returncode:
                verdict = 'CE' if b'SyntaxError' in error or b'IndentationError' in error else 'RE'
                return CaseOutcome(verdict, elapsed)
            actual = output.decode('utf-8', errors='replace')
            return CaseOutcome(
                'AC' if compare_output(actual, expected, version.comparison) else 'WA',
                elapsed,
                actual,
            )
        except subprocess.TimeoutExpired as exc:
            raise InfrastructureError('DOCKER_TIMEOUT') from exc
        finally:
            if process and process.poll() is None:
                process.kill()
            try:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    try:
                        pipe.close()
                    except OSError:
                        pass


def verify_reference(version_id):
    version = ProblemVersion.objects.get(pk=version_id)
    if not version.evaluation_configured:
        return False
    if version.reference_verified:
        return True
    try:
        try:
            image = subprocess.run(
                [
                    'docker',
                    'image',
                    'inspect',
                    '--format',
                    '{{.Id}}',
                    version.runtime or settings.JUDGE_IMAGE,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InfrastructureError('DOCKER_UNAVAILABLE') from exc
        if image.returncode or not image.stdout.strip().startswith('sha256:'):
            raise InfrastructureError('DOCKER_OR_IMAGE_UNAVAILABLE')
        version.runtime = image.stdout.strip()
        version.save(update_fields=['runtime'])
        code = read_private(version.reference_path)
        cases = list(version.cases.all())
        if not any(not c.is_sample for c in cases):
            raise InfrastructureError('NO_JUDGE_CASES')
        for case in cases:
            result = run_case(
                code, read_private(case.input_path), read_private(case.output_path), version
            )
            if result.verdict != 'AC':
                version.verification_error = f'第 {case.order} 个用例：{result.verdict}'
                version.save(update_fields=['verification_error'])
                return False
        version.reference_verified = True
        version.verification_error = ''
        version.save(update_fields=['reference_verified', 'verification_error'])
        return True
    except (InfrastructureError, OSError) as exc:
        version.verification_error = '运行环境异常，请检查评测服务。'
        version.save(update_fields=['verification_error'])
        return False


def evaluate(run_id):
    now = timezone.now()
    claimed = JudgeRun.objects.filter(pk=run_id, status__in=['pending', 'queued']).update(
        status='running', started_at=now, heartbeat=now
    )
    if not claimed:
        return
    run = JudgeRun.objects.select_related('submission', 'question__problem_version').get(pk=run_id)
    version = run.question.problem_version
    try:
        code = read_private(run.submission.code_path)
        outcomes = []
        cases = list(version.cases.all())
        if not any(not case.is_sample for case in cases):
            raise InfrastructureError('NO_JUDGE_CASES')
        for case in cases:
            result = run_case(
                code, read_private(case.input_path), read_private(case.output_path), version
            )
            outcomes.append((case, result))
            JudgeRun.objects.filter(pk=run.pk, status='running').update(heartbeat=timezone.now())
        with transaction.atomic():
            locked = JudgeRun.objects.select_for_update().get(pk=run.pk)
            if locked.status != 'running':
                return
            JudgeCaseResult.objects.bulk_create(
                [
                    JudgeCaseResult(run=run, case=c, verdict=r.verdict, elapsed_ms=r.elapsed_ms)
                    for c, r in outcomes
                ]
            )
            formal_outcomes = [r for c, r in outcomes if not c.is_sample]
            passed = all(r.verdict == 'AC' for r in formal_outcomes)
            locked.status = 'done'
            locked.verdict = (
                'AC' if passed else next(r.verdict for r in formal_outcomes if r.verdict != 'AC')
            )
            locked.base_score = run.question.max_score if passed else 0
            locked.finished_at = timezone.now()
            locked.save()
    except (InfrastructureError, OSError) as exc:
        JudgeRun.objects.filter(pk=run.pk, status='running').update(
            status='error',
            base_score=None,
            error_code=str(exc)[:80] if isinstance(exc, InfrastructureError) else 'STORAGE_ERROR',
            finished_at=timezone.now(),
        )
    except Exception:
        JudgeRun.objects.filter(pk=run.pk, status='running').update(
            status='error', base_score=None, error_code='WORKER_ERROR', finished_at=timezone.now()
        )
        raise
