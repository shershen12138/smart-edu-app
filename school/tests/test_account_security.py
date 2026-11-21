"""账号与会话安全：会话超时、登录阈值、口令有效期与历史口令、长期未登录停用。"""

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.models import PasswordHistory, User, UserRole
from school.tasks import deactivate_stale_accounts


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class PasswordAgeAndHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='secureuser',
            password='SafePassword_2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.user, role='student')

    def test_session_and_login_defaults(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 1800)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertEqual(settings.LOGIN_FAIL_LIMIT, 5)

    def test_initial_password_is_recorded_in_history(self):
        self.assertTrue(PasswordHistory.objects.filter(user=self.user).exists())

    def test_cannot_reuse_previous_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('password'),
            {
                'old_password': 'SafePassword_2026!',
                'new_password1': 'AnotherSafe_2027!',
                'new_password2': 'AnotherSafe_2027!',
            },
        )
        self.assertRedirects(response, reverse('dashboard'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('AnotherSafe_2027!'))

        # 再改回旧密码应被拒绝，并保持新密码不变
        response = self.client.post(
            reverse('password'),
            {
                'old_password': 'AnotherSafe_2027!',
                'new_password1': 'SafePassword_2026!',
                'new_password2': 'SafePassword_2026!',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '不能与最近')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('AnotherSafe_2027!'))

    def test_history_keeps_only_configured_count(self):
        for index in range(settings.PASSWORD_HISTORY_COUNT + 3):
            self.user.set_password(f'Temporary_{index:02d}!')
            self.user.save()
        self.assertEqual(
            PasswordHistory.objects.filter(user=self.user).count(),
            settings.PASSWORD_HISTORY_COUNT,
        )

    def test_expired_password_forces_change(self):
        User.objects.filter(pk=self.user.pk).update(
            password_changed_at=timezone.now()
            - timedelta(days=settings.PASSWORD_MAX_AGE_DAYS + 1),
            must_change_password=False,
        )
        response = self.client.post(
            reverse('login'),
            {'username': 'secureuser', 'password': 'SafePassword_2026!'},
        )
        # 登录后立即标记为待改密，因此重定向目标会再跳修改密码页
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)
        # 下一次访问被中间件引导到修改密码页
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('password'))


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class InactiveAccountTaskTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='stale', password='StaleSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.student, role='student')
        self.admin = User.objects.create_user(
            username='admin1', password='AdminSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')

    def test_stale_student_is_disabled_but_admin_is_kept(self):
        User.objects.filter(pk=self.student.pk).update(
            last_login=timezone.now()
            - timedelta(days=settings.INACTIVE_ACCOUNT_DAYS + 1)
        )
        deactivate_stale_accounts()
        self.student.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertFalse(self.student.is_active)
        self.assertTrue(self.admin.is_active)
