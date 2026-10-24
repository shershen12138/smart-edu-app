from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from school.models import AuditLog, Classroom, ClassStaff, ClassStudent, User, UserRole


class Command(BaseCommand):
    help = (
        '明确确认后移除现有账号，建立 admin/teacher/student，初始密码 123456 且首次登录强制修改。'
    )

    def add_arguments(self, parser):
        parser.add_argument('--confirm-reset', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        if not options['confirm_reset']:
            raise CommandError('此命令将停用全部现有账号。请先备份数据库，再传入 --confirm-reset。')
        now = timezone.now()
        retired = User.objects.filter(deleted_at__isnull=True).count()
        User.objects.update(is_active=False, deleted_at=now, recovery_password='')
        ClassStudent.objects.update(active=False, left_at=now)
        ClassStaff.objects.update(active=False)
        for old in User.objects.filter(username__in=['admin', 'teacher', 'student']):
            old.username = f'retired-{old.pk}-{old.username}'
            old.save(update_fields=['username'])
        accounts = {}
        for username, label in [('admin', '管理员'), ('teacher', '教师'), ('student', '学生')]:
            user = User.objects.create_user(
                username=username,
                password='123456',
                full_name=label,
                student_no=None,
                must_change_password=True,
            )
            user.student_no = f'{username.upper()}-{user.pk:04d}'
            user.save(update_fields=['student_no'])
            UserRole.objects.create(user=user, role=username if username != 'admin' else 'admin')
            accounts[username] = user
        classroom = Classroom.objects.filter(deleted_at__isnull=True, archived=False).first()
        if not classroom:
            classroom = Classroom.objects.create(
                code=f'PY-{now:%Y%m%d%H%M%S}',
                name='Python 教学班',
                course_name='Python 程序设计',
                term='2026 秋季',
            )
        ClassStaff.objects.create(
            classroom=classroom,
            user=accounts['teacher'],
            role='teacher',
            can_edit=True,
            can_view_grades=True,
            can_export=True,
        )
        ClassStudent.objects.create(classroom=classroom, student=accounts['student'])
        AuditLog.objects.create(
            actor=accounts['admin'],
            action='portal.accounts.reset',
            target='accounts',
            detail={'retired': retired},
        )
        self.stdout.write(
            self.style.SUCCESS(
                f'旧账号已停用并移出清单：{retired} 个。已新建三个账号，均要求首次改密。'
            )
        )
