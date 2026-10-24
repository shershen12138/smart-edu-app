import secrets
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from school.models import *
from school.storage import save_private
from school.services import set_membership, set_staff


class Command(BaseCommand):
    help = '创建本地演示账号及练习，随机凭据只写入 .runtime/demo-accounts.txt。'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('演示数据只允许在 DEBUG=true 的本地环境生成。')
        if Classroom.objects.filter(code='DEMO-PY2026').exists():
            self.stdout.write('演示班已存在，未重复创建或重置密码。')
            return
        users = {}
        credentials = []
        for role, name in [
            ('admin', '演示管理员'),
            ('teacher', '林老师'),
            ('assistant', '陈助教'),
            ('student', '李同学'),
        ]:
            username = 'demo_' + role
            if User.objects.filter(username=username).exists():
                raise CommandError('演示账号冲突。')
            password = secrets.token_urlsafe(15)
            user = User.objects.create_user(
                username=username,
                password=password,
                full_name=name,
                student_no='DEMO-' + role,
                must_change_password=False,
            )
            UserRole.objects.create(user=user, role=role)
            users[role] = user
            credentials.append(f'{name}: {username} / {password}')
        classroom = Classroom.objects.create(
            code='DEMO-PY2026',
            name='Python 程序设计 · 实验一班',
            course_name='Python 程序设计',
            course_code='CS101',
            term='2026 秋季',
        )
        set_membership(users['admin'], classroom, users['student'])
        set_staff(
            users['admin'],
            classroom,
            users['teacher'],
            'teacher',
            can_edit=True,
            can_view_grades=True,
            can_export=True,
            can_archive=True,
        )
        set_staff(
            users['admin'],
            classroom,
            users['assistant'],
            'assistant',
            can_edit=True,
            can_view_grades=True,
            can_export=False,
        )
        specs = [
            (
                'A+B：从输入到输出',
                '给定两个整数 a 和 b，请输出它们的和。',
                '一行包含两个整数 a 和 b，用空格分隔。',
                '输出一个整数，表示 a+b。',
                '-10^9 ≤ a,b ≤ 10^9',
                'a, b = map(int, input().split())\nprint(a + b)\n',
                [
                    ('2 3\n', '5\n', True),
                    ('0 0\n', '0\n', False),
                    ('-5 8\n', '3\n', False),
                    ('1000000000 1000000000\n', '2000000000\n', False),
                ],
            ),
            (
                '列表求和：处理一组数据',
                '给定 n 个整数，计算它们的总和。',
                '第一行是 n，第二行是 n 个整数。',
                '输出整数之和。',
                '1 ≤ n ≤ 1000；每个整数绝对值不超过 10000。',
                'n = int(input())\nprint(sum(map(int, input().split())))\n',
                [
                    ('3\n1 2 3\n', '6\n', True),
                    ('1\n-8\n', '-8\n', False),
                    ('5\n1 -1 2 -2 0\n', '0\n', False),
                ],
            ),
        ]
        problems = []
        for index, (title, statement, inf, outf, bounds, reference, cases) in enumerate(specs, 1):
            problem = Problem.objects.create(
                code=f'DEMO-P{index:03}', classroom=classroom, created_by=users['teacher']
            )
            version = ProblemVersion.objects.create(
                problem=problem,
                number=1,
                title=title,
                statement=statement,
                input_format=inf,
                output_format=outf,
                data_range=bounds,
                knowledge='输入输出 · 基础运算' if index == 1 else '列表 · 循环',
                reference_path=save_private(reference, '.py'),
                runtime=settings.JUDGE_IMAGE,
            )
            for order, (stdin, expected, sample) in enumerate(cases, 1):
                TestCase.objects.create(
                    version=version,
                    order=order,
                    input_path=save_private(stdin),
                    output_path=save_private(expected),
                    is_sample=sample,
                    hidden=not sample,
                )
            problems.append(version)
        assignment = Assignment.objects.create(classroom=classroom, created_by=users['teacher'])
        rule = SubmissionRuleVersion.objects.create(
            assignment=assignment,
            number=1,
            opens_at=timezone.now() - timedelta(days=1),
            deadline=timezone.now() + timedelta(days=7),
            late_deadline=timezone.now() + timedelta(days=9),
            late_penalty='.1',
        )
        version = AssignmentVersion.objects.create(
            assignment=assignment,
            number=1,
            title='01 · Python 起步练习',
            description='熟悉输入输出和基础运算，用两道小题开启本学期的编程之旅。',
            rule=rule,
        )
        for index, problem in enumerate(problems, 1):
            AssignmentQuestion.objects.create(
                version=version,
                question_key=problem.problem.code,
                problem_version=problem,
                order=index,
                max_score=50,
            )
        Announcement.objects.create(
            classroom=classroom,
            title='欢迎来到 Python 实验课堂',
            content='先阅读题意与样例，再编写代码。每题需要通过全部正式测试用例，记得留意作业截止时间。',
            author=users['teacher'],
        )
        path = settings.RUNTIME / 'demo-accounts.txt'
        path.write_text(
            '仅限本机开发演示，不要上传到仓库或生产服务器。\n\n'
            + '\n'.join(credentials)
            + '\n\n参考程序待验证。运行 python manage.py run_judge 后，由教师审核并发布演示作业。\n',
            encoding='utf-8',
        )
        self.stdout.write(f'演示数据已创建。账号凭据保存在 {path}（已被 Git 忽略）。')
