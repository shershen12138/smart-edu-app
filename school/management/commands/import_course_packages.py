from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from school.models import EvaluationPackage
from school.portal.parsers import load_package


class Command(BaseCommand):
    help = '从已解压的章节目录导入批阅配置，只解析文件，不执行压缩包中的代码。'

    def add_arguments(self, parser):
        parser.add_argument('directory')

    @transaction.atomic
    def handle(self, *args, **options):
        root = Path(options['directory']).resolve()
        if not root.is_dir():
            raise CommandError('目录不存在。')
        total = 0
        for folder in sorted(root.iterdir()):
            if (
                not folder.is_dir()
                or not folder.name[:2].isdigit()
                or not 1 <= int(folder.name[:2]) <= 10
            ):
                continue
            data = load_package(folder)
            code = 'chapter-' + folder.name[:2]
            family = EvaluationPackage.objects.filter(Q(code=code) | Q(code__startswith=code + '-'))
            current = family.filter(digest=data['digest']).first()
            if current:
                family.exclude(pk=current.pk).update(active=False)
                fields = []
                if not current.active:
                    current.active = True
                    fields.append('active')
                if current.status == 'error':
                    current.status = 'pending'
                    current.validation_error = ''
                    current.validated_at = None
                    fields += ['status', 'validation_error', 'validated_at']
                if fields:
                    current.save(update_fields=fields)
                self.stdout.write(f'{folder.name}: 已导入，使用 {current.code}')
                continue
            if family.exists():
                # Assets are immutable even when reimporting or reverting chapter configurations.
                family.update(active=False)
                code += '-' + data['digest']
            EvaluationPackage.objects.create(code=code, name=folder.name, **data)
            total += 1
            self.stdout.write(
                f'{folder.name}: {len(data["spec"])} 题，{sum(len(s["inputs"]) for s in data["spec"])} 用例；配置 {code}'
            )
        self.stdout.write(self.style.SUCCESS(f'导入完成：{total} 个章节配置。'))
