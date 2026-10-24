import time
from django.core.management.base import BaseCommand
from school.models import JudgeRun, ProblemVersion
from school.judge import evaluate, verify_reference
from school.tasks import recover_stale
from school.models import CourseworkSubmission, EvaluationPackage
from school.portal.grading import (
    evaluate as evaluate_coursework,
    recover_stale as recover_coursework,
    validate_package,
)


class Command(BaseCommand):
    help = '开发环境持久化队列工作进程；只在 Docker 中执行程序。生产使用 Celery。'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        self.stdout.write('评测进程已启动，Ctrl+C 停止。')
        try:
            while True:
                recover_stale()
                recover_coursework()
                for pk in (
                    EvaluationPackage.objects.filter(status='pending')
                    .exclude(reference_path='')
                    .values_list('pk', flat=True)[:10]
                ):
                    validate_package(pk)
                for pk in (
                    CourseworkSubmission.objects.filter(status__in=['pending', 'queued'])
                    .order_by('pk')
                    .values_list('pk', flat=True)[:20]
                ):
                    evaluate_coursework(pk)
                for version in (
                    ProblemVersion.objects.filter(
                        reference_verified=False, verification_error='', cases__is_sample=False
                    )
                    .exclude(reference_path='')
                    .distinct()
                ):
                    verify_reference(version.pk)
                for run in JudgeRun.objects.filter(status__in=['pending', 'queued']).order_by('pk')[
                    :20
                ]:
                    evaluate(run.pk)
                if options['once']:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write('评测进程已停止。')
