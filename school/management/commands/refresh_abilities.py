from django.core.management.base import BaseCommand

from school.models import Coursework
from school.portal import rubric_agent


class Command(BaseCommand):
    help = '按每个作业的考察知识点重新归纳雷达图的六大主能力（只更新 abilities）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--offline',
            action='store_true',
            help='只做规则归类，不调用大模型',
        )
        parser.add_argument(
            '--coursework',
            type=int,
            default=0,
            help='只处理指定作业 ID',
        )

    def handle(self, *args, **options):
        queryset = Coursework.objects.select_related('rubric').order_by('pk')
        if options['coursework']:
            queryset = queryset.filter(pk=options['coursework'])
        for work in queryset:
            if getattr(work, 'rubric', None) is None:
                self.stdout.write(f'跳过 {work.pk} {work.title}：没有评分标准')
                continue
            try:
                abilities = rubric_agent.generate_abilities(
                    work, offline=options['offline']
                )
            except Exception as exc:  # noqa: BLE001 - 命令行逐条报告错误
                self.stderr.write(f'{work.pk} {work.title}：{exc}')
                continue
            labels = '、'.join(item['label'] for item in abilities)
            self.stdout.write(f'{work.pk} {work.title}：{labels}')
