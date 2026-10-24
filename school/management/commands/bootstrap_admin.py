import getpass
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from school.models import User, UserRole


class Command(BaseCommand):
    help = '交互式创建首个管理员，不允许覆盖已有账号。'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')
        parser.add_argument('--name', default='系统管理员')

    def handle(self, *args, **options):
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
                full_name=options['name'],
                password=password,
                must_change_password=True,
            )
            UserRole.objects.create(user=user, role='admin')
        self.stdout.write('管理员已创建，首次登录须修改密码。')
