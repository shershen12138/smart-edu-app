from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from school.models import Coursework, CourseworkItem, CourseworkQuestionResult, EvaluationPackage
from school.portal.services import snapshot


class Command(BaseCommand):
    help = '后台关联作业与批阅配置，并将此前等待接入的提交加入批阅队列。'

    def add_arguments(self, parser):
        parser.add_argument('work_id', type=int)
        parser.add_argument('package_code')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            work = Coursework.objects.select_for_update().get(
                pk=options['work_id'], deleted_at__isnull=True
            )
            package = EvaluationPackage.objects.get(code=options['package_code'], active=True)
        except (Coursework.DoesNotExist, EvaluationPackage.DoesNotExist) as exc:
            raise CommandError('作业或配置不存在。') from exc
        if work.entries.exclude(status='waiting').exists():
            raise CommandError('已有提交进入批阅，不能更换该作业的批阅配置。')
        if not package.reference_path or not package.spec:
            raise CommandError('该章节没有自动批阅配置。')
        work.package = package
        work.revision += 1
        work.save(update_fields=['package', 'revision', 'updated_at'])
        work.items.all().delete()
        for order, item in enumerate(package.spec, 1):
            CourseworkItem.objects.create(
                coursework=work,
                function_name=item['function'],
                title=item['function'],
                points=item['points'],
                order=order,
            )
        state = snapshot(work)
        count = 0
        for entry in work.entries.filter(status='waiting'):
            entry.questions.all().delete()
            for item in state['items']:
                CourseworkQuestionResult.objects.create(
                    submission=entry,
                    function_name=item['function'],
                    title=item['title'],
                    points=item['points'],
                    order=item['order'],
                    verdict='PENDING' if state['ready'] else 'WAITING',
                )
            entry.snapshot = state
            entry.status = 'pending' if state['ready'] else 'waiting'
            entry.save(update_fields=['snapshot', 'status'])
            count += 1
        self.stdout.write(self.style.SUCCESS(f'已关联，{count} 次历史提交进入队列。'))
