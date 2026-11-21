"""安全审计：哈希链防篡改、只读审计页、导出审计与登录失败留痕。"""

import json
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from school.models import AuditLog, User, UserRole
from school.services import audit

BASE_OVERRIDES = dict(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)


@override_settings(**BASE_OVERRIDES)
class AuditChainTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='AdminSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')

    def test_records_are_hash_chained(self):
        first = audit(self.admin, 'test.first', 'obj')
        second = audit(self.admin, 'test.second', 'obj')
        self.assertEqual(first.prev_hash, '')
        self.assertEqual(second.prev_hash, first.record_hash)
        self.assertEqual(second.record_hash, second.compute_hash())
        self.assertEqual(first.role, 'admin')

    def test_tampering_is_detectable(self):
        first = audit(self.admin, 'test.first', 'obj')
        second = audit(self.admin, 'test.second', 'obj')
        AuditLog.objects.filter(pk=first.pk).update(target='tampered')
        first.refresh_from_db()
        # 篡改后重算的哈希与原记录不一致，后续记录仍指向原哈希
        self.assertNotEqual(first.record_hash, first.compute_hash())
        self.assertEqual(second.prev_hash, first.record_hash)

    def test_export_writes_json_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'audit.jsonl'
            with override_settings(AUDIT_LOG_FILE=str(path)):
                audit(self.admin, 'test.export', 'obj', {'k': 'v'})
            lines = path.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload['action'], 'test.export')
        self.assertTrue(payload['record_hash'])


@override_settings(**BASE_OVERRIDES)
class AuditPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin2', password='AdminSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')
        self.student = User.objects.create_user(
            username='stu', password='StudentSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.student, role='student')

    def test_admin_can_view_subject_logs(self):
        audit(self.admin, 'test.page', 'obj')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('audit_logs'))
        self.assertContains(response, '审计日志')
        self.assertContains(response, 'test.page')
        self.assertContains(response, '只追加、不可删除')

    def test_non_admin_is_forbidden(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('audit_logs')).status_code, 403)

    def test_export_is_recorded(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('audit_export'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='audit.export').exists())


@override_settings(**BASE_OVERRIDES)
class LoginAuditTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_failed_login_is_audited(self):
        self.client.post(
            reverse('login'), {'username': 'ghost', 'password': 'WrongPass_2026!'}
        )
        entry = AuditLog.objects.filter(action='auth.login_failed').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.result, 'failure')
        self.assertNotIn('WrongPass_2026!', json.dumps(entry.detail, ensure_ascii=False))
