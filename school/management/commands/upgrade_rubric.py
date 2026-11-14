"""把数据库中已有的评分标准重渲染为新版结构（不调用大模型）。

新版结构：第一节“作业考察的知识点”，第二节“考察重点（雷达图维度）”，
五分制量表并入第二节（每根轴绑定一个评分维度，用该维度的 5/4/3/2/1 分
描述作为评价标准），不再单独保留“二、5 分制量表”一节。

    python manage.py upgrade_rubric            # 预览
    python manage.py upgrade_rubric --apply    # 写入数据库
"""

from django.core.management.base import BaseCommand

from school.course_models import CourseworkRubric
from school.portal import rubric_agent


class Command(BaseCommand):
    help = '按已存的知识点/维度重渲染评分标准 markdown（不调用大模型）'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='实际写入，否则只预览')

    def handle(self, *args, **options):
        apply = options['apply']
        changed = 0
        skipped = 0
        for rubric in CourseworkRubric.objects.select_related('coursework').iterator():
            work = rubric.coursework
            points = rubric.knowledge_points or []
            if not points:
                skipped += 1
                continue
            try:
                context = rubric_agent.coursework_context(work)
            except Exception:  # noqa: BLE001 -- 单个作业异常不应中断整批
                skipped += 1
                continue
            if not context['items']:
                skipped += 1
                continue
            markdown = rubric_agent.render_markdown(
                context,
                points,
                rubric.dimensions or [],
                rubric.abilities or [],
            )
            if markdown.strip() == (rubric.markdown or '').strip():
                continue
            changed += 1
            if apply:
                rubric.markdown = markdown
                rubric.save(update_fields=['markdown', 'updated_at'])
        action = '已更新' if apply else '待更新'
        self.stdout.write(f'{action} {changed} 份评分标准，跳过 {skipped} 份')
        if not apply:
            self.stdout.write('（预览模式，加 --apply 写入数据库）')
