"""为已有评分标准补「每题布鲁姆认知层次」。

新生成的评分标准会在大模型分析时一并产出 ``bloom_map``；此命令用于处理
在此之前生成的历史数据：配置了大模型的作业用模型判断，未配置或调用失败时
按「知识点 → 教学模块 → 模块认知层次」的规则兜底，并在 Markdown 追加
「三、每题认知层次（布鲁姆）」一节。

    python manage.py backfill_bloom            # 有模型用模型，否则规则
    python manage.py backfill_bloom --offline  # 全部用规则，不调用大模型
    python manage.py backfill_bloom --dry-run  # 只统计待补数量
"""

from django.core.management.base import BaseCommand

from school.course_models import Coursework
from school.portal import rubric_agent


class Command(BaseCommand):
    help = '为已有评分标准补每题布鲁姆认知层次（大模型优先，规则兜底）'

    def add_arguments(self, parser):
        parser.add_argument('--offline', action='store_true', help='只用规则推断，不调用大模型')
        parser.add_argument('--limit', type=int, default=0, help='最多处理多少个作业，0 表示不限')
        parser.add_argument('--dry-run', action='store_true', help='只统计待补数量，不写数据库')

    def handle(self, *args, **options):
        offline = bool(options['offline'])
        limit = int(options['limit'] or 0)
        dry_run = bool(options['dry_run'])

        queryset = (
            Coursework.objects.filter(deleted_at__isnull=True, rubric__isnull=False)
            .select_related('owner', 'rubric')
            .prefetch_related('items')
            .order_by('pk')
        )
        pending = [work for work in queryset if rubric_agent.needs_bloom(work)]
        if limit:
            pending = pending[:limit]

        if dry_run:
            self.stdout.write(f'待补标 {len(pending)} 个作业（预览模式，未写库）')
            for work in pending:
                self.stdout.write(f'  - {work.pk} {work.title}')
            return

        filled = failed = 0
        for work in pending:
            try:
                rubric_agent.fill_bloom(work, user=work.owner, offline=offline)
            except Exception as exc:  # noqa: BLE001 -- 单个作业失败不中断整批
                failed += 1
                self.stderr.write(f'  ! {work.pk} {work.title}：{exc}')
                continue
            filled += 1

        mode = '规则兜底' if offline else '大模型优先（失败回落规则）'
        self.stdout.write(f'已补标 {filled} 个作业，失败 {failed} 个（{mode}）')
