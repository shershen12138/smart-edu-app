"""One-time cleanup of old logical deletions; defaults to a read-only preview."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from school.cleanup import drain_file_cleanup, is_referenced, queue_file_cleanup
from school.models import Classroom, Coursework, User


class Command(BaseCommand):
    help = '清理旧版逻辑删除记录和无引用文件；默认只预览，--apply 才执行。请先备份。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument(
            '--offline',
            action='store_true',
            help='网站与批阅服务停止后使用，同时清理新产生的无引用文件',
        )

    def handle(self, *args, **options):
        removed = [
            model.objects.filter(deleted_at__isnull=False)
            for model in (Coursework, Classroom, User)
        ]
        for qs in removed:
            self.stdout.write(f'{qs.model.__name__}: 待清理 {qs.count()} 条')
        if options['apply']:
            with transaction.atomic():
                for qs in removed:
                    qs.delete()
        cutoff = (timezone.now() - timedelta(hours=24)).timestamp()
        paths = []
        root = settings.PRIVATE_STORAGE.resolve()
        directory = root / 'objects'
        if directory.is_dir():
            for path in directory.iterdir():
                if path.is_symlink() or not path.is_file():
                    continue
                if not options['offline'] and path.stat().st_mtime >= cutoff:
                    continue
                key = path.relative_to(root).as_posix()
                if not is_referenced(key):
                    paths.append(key)
        self.stdout.write(f'无引用文件: {len(paths)} 个')
        if options['apply']:
            queue_file_cleanup(paths)
            drain_file_cleanup(limit=max(200, len(paths)))
            self.stdout.write('清理完成。文件删除失败会留在重试队列，不会误删仍有引用的文件。')
        else:
            self.stdout.write('以上为预览，未删除任何数据。')
