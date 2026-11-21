"""只读巡检：数据库账号权限是否收敛、慢查询日志是否出现 SQL 注入特征。"""

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from school.db_security import parse_grants, privilege_findings, scan_statements


class Command(BaseCommand):
    help = (
        '只读检查数据库账户权限与慢查询日志中的 SQL 注入特征；'
        '默认只输出结果，--fail-on-risk 时发现风险以非 0 状态退出，便于接入定时巡检。'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--slow-log',
            default='',
            help='慢查询日志文件路径；传 "-" 表示从标准输入读取（可在宿主机 docker exec 后管道传入）。',
        )
        parser.add_argument(
            '--skip-privileges',
            action='store_true',
            help='只扫描日志，不检查数据库账户权限。',
        )
        parser.add_argument(
            '--fail-on-risk',
            action='store_true',
            help='发现风险时抛出 CommandError，返回非 0 退出码。',
        )

    def handle(self, *args, **options):
        risks = 0
        if not options['skip_privileges']:
            risks += self._check_privileges()
        if options['slow_log']:
            risks += self._check_slow_log(options['slow_log'])
        if not options['slow_log']:
            self.stdout.write(
                '[提示] 未指定 --slow-log，本次未扫描 SQL 日志；'
                '生产环境建议按部署文档定期执行。'
            )
        if options['fail_on_risk'] and risks:
            raise CommandError(f'发现 {risks} 项数据库安全风险，请按上面的输出逐项处理。')
        self.stdout.write(self.style.SUCCESS('数据库安全检查完成。'))

    def _check_privileges(self):
        if connection.vendor != 'mysql':
            self.stdout.write(
                f'[跳过] 当前数据库为 {connection.vendor}，账户权限检查只适用于 MySQL。'
            )
            return 0
        with connection.cursor() as cursor:
            cursor.execute('SHOW GRANTS')
            grants = parse_grants(row[0] for row in cursor.fetchall())
        if not grants:
            self.stdout.write('[提示] 未解析到 GRANT 记录，请人工复核账号权限。')
            return 0
        scope_names = sorted({scope for _, scope in grants})
        self.stdout.write(f'当前账号授权范围：{"、".join(scope_names)}')
        findings = privilege_findings(grants)
        for finding in findings:
            self.stdout.write(
                self.style.ERROR(
                    f'[风险] {finding["privilege"]} on {finding["scope"]}：'
                    f'{finding["reason"]}'
                )
            )
        if findings:
            self.stdout.write('建议用管理员账号回收以上权限，应用账号只保留业务库的增删改查。')
        else:
            self.stdout.write(self.style.SUCCESS('[通过] 未发现全局高危权限。'))
        return len(findings)

    def _check_slow_log(self, source):
        if source == '-':
            lines = sys.stdin.read().splitlines()
            label = '标准输入'
        else:
            path = Path(source)
            if not path.is_file():
                self.stdout.write(f'[跳过] 未找到慢查询日志：{source}')
                return 0
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
            label = str(path)
        findings = scan_statements(lines)
        self.stdout.write(f'已扫描 {label} 共 {len(lines)} 行。')
        for finding in findings:
            self.stdout.write(
                self.style.ERROR(
                    f'[风险] {finding["rule"]}（{finding["severity"]}）：'
                    f'{finding["statement"]}'
                )
            )
        if findings:
            self.stdout.write(
                '请结合请求日志确认来源 IP 与账号；未参数化的 SQL 必须改成占位符绑定。'
            )
        else:
            self.stdout.write(self.style.SUCCESS('[通过] 日志中未发现 SQL 注入特征。'))
        return len(findings)
