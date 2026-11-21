import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from school.models import User, UserRole


class Command(BaseCommand):
    help = '交互式创建管理员账号（系统 / 安全 / 审计），不允许覆盖已有账号。'

    ROLE_NAMES = {
        'admin': '系统管理员',
        'security_admin': '安全管理员',
        'audit_admin': '审计管理员',
    }

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')
        parser.add_argument('--name', default=None)
        parser.add_argument(
            '--role',
            default='admin',
            choices=sorted(self.ROLE_NAMES),
            help='三员角色：admin（系统）、security_admin（安全）、audit_admin（审计）。',
        )

    def handle(self, *args, **options):
        role = options['role']
        if User.objects.filter(username=options['username']).exists():
            raise CommandError('账号已存在。')
        password = getpass.getpass('初始密码: ')
        if password != getpass.getpass('再次输入: '):
            raise CommandError('两次密码不一致。')
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError('；'.join(exc.messages))
        with transaction.atomic():
            user = User.objects.create_user(
                username=options['username'],
                full_name=options['name'] or self.ROLE_NAMES[role],
                password=password,
                must_change_password=True,
            )
            UserRole.objects.create(user=user, role=role)
        self.stdout.write(
            f'{self.ROLE_NAMES[role]}账号已创建，首次登录须修改密码；三员账号请勿互相兼任。'
        )
