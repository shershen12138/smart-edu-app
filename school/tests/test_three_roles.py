"""三权分立：系统管理员、安全管理员、审计管理员的权限边界。"""

from django.test import TestCase, override_settings
from django.urls import reverse

from school.models import User, UserRole
from school.portal.access import role

BASE_OVERRIDES = dict(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)


@override_settings(**BASE_OVERRIDES)
class ThreeRolesTests(TestCase):
    def make_user(self, username, role_name):
        user = User.objects.create_user(
            username=username,
            password='RoleSafe_2026!',
            full_name=username,
            must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role_name)
        return user

    def test_role_priority_keeps_admin_first(self):
        user = self.make_user('multi', 'admin')
        UserRole.objects.create(user=user, role='student')
        self.assertEqual(role(user), 'admin')

    def test_audit_admin_only_audits(self):
        auditor = self.make_user('auditor', 'audit_admin')
        self.client.force_login(auditor)
        self.assertEqual(self.client.get(reverse('audit_logs')).status_code, 200)
        self.assertEqual(self.client.get(reverse('students')).status_code, 403)
        self.assertEqual(self.client.get(reverse('teachers')).status_code, 403)

    def test_security_admin_manages_accounts_but_not_audit(self):
        security = self.make_user('security', 'security_admin')
        self.client.force_login(security)
        self.assertEqual(self.client.get(reverse('students')).status_code, 200)
        self.assertEqual(self.client.get(reverse('teachers')).status_code, 200)
        self.assertEqual(self.client.get(reverse('audit_logs')).status_code, 403)

    def test_admin_can_do_both(self):
        admin = self.make_user('admin3', 'admin')
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('students')).status_code, 200)
        self.assertEqual(self.client.get(reverse('audit_logs')).status_code, 200)

    def test_role_dashboard_entries(self):
        auditor = self.make_user('auditor2', 'audit_admin')
        self.client.force_login(auditor)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '审计工作台')
        self.assertNotContains(response, '教师用户与授权')
