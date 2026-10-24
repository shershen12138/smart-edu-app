from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.core.cache import cache
from .models import JudgeRun, ProblemVersion


@shared_task
def evaluate_run(run_id):
    from .judge import evaluate

    evaluate(run_id)


@shared_task
def verify_problem(version_id):
    from .judge import verify_reference

    try:
        return verify_reference(version_id)
    finally:
        cache.delete(f'verify-dispatch:{version_id}')


def recover_stale():
    JudgeRun.objects.filter(
        status='queued', heartbeat__lt=timezone.now() - timedelta(minutes=5)
    ).update(status='pending')
    JudgeRun.objects.filter(
        status='running', heartbeat__lt=timezone.now() - timedelta(minutes=20)
    ).update(status='error', error_code='WORKER_LOST', finished_at=timezone.now())


@shared_task
def dispatch_pending():
    from .services import dispatch, dispatch_reference

    from .cleanup import drain_file_cleanup
    drain_file_cleanup()
    recover_stale()
    for pk in (
        ProblemVersion.objects.filter(
            reference_verified=False, verification_error='', cases__is_sample=False
        )
        .exclude(reference_path='')
        .distinct()
        .values_list('pk', flat=True)[:20]
    ):
        dispatch_reference(pk)
    for pk in JudgeRun.objects.filter(status='pending').values_list('pk', flat=True)[:100]:
        dispatch(pk)
    dispatch_coursework()


@shared_task
def evaluate_coursework(entry_id):
    from .portal.grading import evaluate

    evaluate(entry_id)


@shared_task
def validate_course_package(package_id):
    from .portal.grading import validate_package

    validate_package(package_id)


def dispatch_coursework():
    from .models import CourseworkSubmission, EvaluationPackage
    from .portal.grading import recover_stale as recover_coursework

    recover_coursework()
    for pk in (
        EvaluationPackage.objects.filter(status='pending')
        .exclude(reference_path='')
        .values_list('pk', flat=True)[:20]
    ):
        try:
            validate_course_package.delay(pk)
        except Exception:
            EvaluationPackage.objects.filter(pk=pk, status='validating').update(status='pending')
    for pk in CourseworkSubmission.objects.filter(status='pending').values_list('pk', flat=True)[
        :100
    ]:
        if CourseworkSubmission.objects.filter(pk=pk, status='pending').update(
            status='queued', heartbeat=timezone.now()
        ):
            try:
                evaluate_coursework.delay(pk)
            except Exception:
                CourseworkSubmission.objects.filter(pk=pk, status='queued').update(status='pending')
