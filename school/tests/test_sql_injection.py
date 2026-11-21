"""SQL 注入防护：ORM 参数化回归、应用层拦截、数据库账户与日志巡检。"""

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from school.db_security import parse_grants, privilege_findings, scan_statements
from school.models import AuditLog, User, UserRole
from school.sql_guard import scan

BASE_OVERRIDES = {
    'PASSWORD_HASHERS': ['django.contrib.auth.hashers.MD5PasswordHasher'],
    'REDIS_URL': '',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

PAYLOADS = [
    "' OR 1=1 --",
    "'; DROP TABLE users; --",
    '" OR ""="',
    "1' UNION SELECT username, password FROM users --",
    "' AND SLEEP(5) --",
]


@override_settings(**BASE_OVERRIDES)
class SqlInjectionRegressionTests(TestCase):
    """关闭应用层拦截后，直接验证 ORM 参数绑定本身不会被注入改变结果集。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='AdminSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')
        self.student = User.objects.create_user(
            username='stu_alpha',
            password='StudentSafe_2026!',
            full_name='张三',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.student, role='student')

    def test_search_payload_does_not_change_result_set(self):
        self.client.force_login(self.admin)
        with override_settings(SQL_GUARD_ENABLED=False):
            for payload in PAYLOADS:
                response = self.client.get(reverse('students'), {'q': payload})
                self.assertEqual(response.status_code, 200, payload)
                self.assertNotContains(response, 'stu_alpha', msg_prefix=payload)
                self.assertEqual(User.objects.count(), 2, payload)
                self.assertTrue(User.objects.filter(pk=self.student.pk).exists())

    def test_like_wildcards_are_escaped(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students'), {'q': '%'})
        self.assertEqual(response.status_code, 200)
        # 参数化查询会转义 % ，不会退化为匹配全部学生
        self.assertNotContains(response, 'stu_alpha')

    def test_payload_is_stored_as_plain_text(self):
        hostile = User.objects.create_user(
            username='hostile',
            password='HostileSafe_2026!',
            full_name="Robert'); DROP TABLE users;--",
            must_change_password=False,
        )
        self.assertEqual(User.objects.filter(pk=hostile.pk).count(), 1)
        self.assertEqual(User.objects.filter(full_name="Robert'); DROP TABLE users;--").count(), 1)
        self.assertEqual(User.objects.count(), 3)


@override_settings(**BASE_OVERRIDES)
class SqlGuardMiddlewareTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin2', password='AdminSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')
        self.student = User.objects.create_user(
            username='stu_beta',
            password='StudentSafe_2026!',
            full_name='李四',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.student, role='student')

    def test_high_risk_query_is_blocked_and_audited(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students'), {'q': "' OR 1=1 --"})
        self.assertEqual(response.status_code, 400)
        entry = AuditLog.objects.filter(action='security.sql_injection_blocked').latest('pk')
        self.assertEqual(entry.result, 'failure')
        self.assertEqual(entry.detail['params'], ['q'])
        self.assertIn('quote_tautology', entry.detail['rules'])
        # 审计只记录参数名和规则名，不落原始输入
        self.assertNotIn("OR 1=1", json.dumps(entry.detail, ensure_ascii=False))

    def test_low_risk_keyword_is_allowed(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students'), {'q': 'UNION SELECT 的用法'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action='security.sql_injection_blocked').exists())

    def test_normal_search_still_works(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students'), {'q': '李四'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'stu_beta')

    def test_anonymous_blocked_without_audit_spam(self):
        response = self.client.get(reverse('students'), {'q': "' OR 1=1 --"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuditLog.objects.filter(action='security.sql_injection_blocked').exists())

    def test_post_body_is_not_blocked(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('logout'), {'q': "' OR 1=1 --"})
        self.assertNotEqual(response.status_code, 400)


class SqlGuardRuleTests(SimpleTestCase):
    def test_rules_are_matched(self):
        self.assertEqual(scan([('q', "' OR 1=1 --")])[0][1], 'quote_tautology')
        self.assertEqual(scan([('q', '1 UNION SELECT password FROM users')])[0][1], 'union_select')
        self.assertEqual(scan([('q', '; DROP TABLE users')])[0][1], 'stacked_statement')
        self.assertEqual(scan([('q', "' AND SLEEP(5) --")])[0][1], 'time_delay')

    def test_teaching_content_is_not_matched(self):
        self.assertEqual(scan([('q', '第三章 循环结构 列表切片')]), [])
        self.assertEqual(scan([('q', 'Python 中 SELECT 语句怎么写')]), [])


class GrantParsingTests(SimpleTestCase):
    def test_application_scope_all_privileges_is_not_reported(self):
        grants = parse_grants(['GRANT ALL PRIVILEGES ON `coursejudge`.* TO `coursejudge`@`%`'])
        self.assertEqual(privilege_findings(grants), [])

    def test_global_and_delegation_privileges_are_reported(self):
        grants = parse_grants(
            [
                'GRANT SELECT, FILE ON *.* TO `app`@`%`',
                'GRANT ALL PRIVILEGES ON `coursejudge`.* TO `app`@`%` WITH GRANT OPTION',
            ]
        )
        found = {item['privilege'] for item in privilege_findings(grants)}
        self.assertIn('FILE', found)
        self.assertIn('GRANT OPTION', found)

    def test_role_grants_are_ignored(self):
        self.assertEqual(parse_grants(['GRANT `reader`@`%` TO `app`@`%`']), [])


class SlowLogScanTests(SimpleTestCase):
    def test_injected_statement_is_detected_and_masked(self):
        findings = scan_statements(["SELECT * FROM users WHERE name = '张三' OR 1=1 --"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['rule'], 'quote_tautology')
        self.assertNotIn('张三', findings[0]['statement'])

    def test_normal_statement_is_ignored(self):
        self.assertEqual(scan_statements(['SELECT id FROM users WHERE id = 1']), [])


class DbSecurityCommandTests(SimpleTestCase):
    def test_sqlite_privilege_check_is_skipped(self):
        out = StringIO()
        call_command('db_security_check', stdout=out)
        text = out.getvalue()
        self.assertIn('跳过', text)
        self.assertIn('未指定 --slow-log', text)

    def test_risky_slow_log_fails_when_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'slow.log'
            path.write_text(
                "SELECT * FROM users WHERE name = 'x' OR 1=1 --\n", encoding='utf-8'
            )
            with self.assertRaises(CommandError):
                call_command(
                    'db_security_check',
                    '--skip-privileges',
                    '--slow-log',
                    str(path),
                    '--fail-on-risk',
                    stdout=StringIO(),
                )
