from django.core.management.base import BaseCommand, CommandError

from school.course_models import Coursework
from school.portal import rubric_agent


class Command(BaseCommand):
    help = '分析作业题目并生成评分标准（调用大模型；未配置时可用 --offline 走规则兜底）'

    def add_arguments(self, parser):
        parser.add_argument('coursework_id', type=int, help='作业 ID')
        parser.add_argument(
            '--offline',
            action='store_true',
            help='不调用大模型，使用规则兜底（结果标记为规则生成）',
        )
        parser.add_argument(
            '--keep',
            action='store_true',
            help='已有评分标准时直接复用，不重新生成',
        )

    def handle(self, *args, **options):
        try:
            work = Coursework.objects.get(
                pk=options['coursework_id'], deleted_at__isnull=True
            )
        except Coursework.DoesNotExist as exc:
            raise CommandError('作业不存在。') from exc

        try:
            rubric = rubric_agent.generate_for(
                work, offline=options['offline'], force=not options['keep']
            )
        except (
            rubric_agent.LLMNotConfigured,
            rubric_agent.LLMError,
            rubric_agent.RubricParseError,
        ) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f'作业：{work.title}')
        source = rubric.get_source_display()
        if rubric.model:
            source += f' / {rubric.model}'
        self.stdout.write(f'来源：{source}')
        self.stdout.write(
            '维度：' + '、'.join(f"{d['label']}({d['weight']:.0f}%)" for d in rubric.dimensions)
        )
        self.stdout.write(f'知识点：{len(rubric.knowledge_points)} 条')
        for point in rubric.knowledge_points[:10]:
            self.stdout.write(f"  - {point['name']}：{point['detail']}")
        self.stdout.write('已保存到数据库（CourseworkRubric）。')
