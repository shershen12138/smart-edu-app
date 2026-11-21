"""双因素认证：TOTP 生成校验、登录第二步、绑定与恢复码。"""

from django.test import TestCase, override_settings
from django.urls import reverse

from school import totp
from school.models import TOTPDevice, User, UserRole

BASE_OVERRIDES = dict(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    TOTP_ENFORCE=False,
)


@override_settings(**BASE_OVERRIDES)
class TOTPCoreTests(TestCase):
    def test_generated_code_verifies(self):
        secret = totp.generate_secret()
        code = totp.current_code(secret)
        self.assertTrue(totp.verify_code(secret, code))

    def test_wrong_code_rejected(self):
        secret = totp.generate_secret()
        self.assertFalse(totp.verify_code(secret, '000000'))
        self.assertFalse(totp.verify_code(secret, 'abcdef'))

    def test_backup_code_can_be_used_only_once(self):
        user = User.objects.create_user(
            username='backup', password='BackupSafe_2026!', must_change_password=False
        )
        device = TOTPDevice.objects.create(
            user=user, secret=totp.generate_secret(), confirmed=True
        )
        codes = totp.issue_backup_codes(user)
        device.refresh_from_db()
        self.assertTrue(totp.consume_backup_code(device, codes[0]))
        self.assertFalse(totp.consume_backup_code(device, codes[0]))


@override_settings(**BASE_OVERRIDES)
class TOTPLoginTests(TestCase):
    def setUp(self):
        self.secret = totp.generate_secret()
        self.user = User.objects.create_user(
            username='tfa', password='TfaSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.user, role='teacher')
        TOTPDevice.objects.create(user=self.user, secret=self.secret, confirmed=True)

    def test_login_requires_second_factor(self):
        response = self.client.post(
            reverse('login'), {'username': 'tfa', 'password': 'TfaSafe_2026!'}
        )
        self.assertRedirects(
            response, reverse('totp_verify'), fetch_redirect_response=False
        )
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_correct_code_completes_login(self):
        self.client.post(
            reverse('login'), {'username': 'tfa', 'password': 'TfaSafe_2026!'}
        )
        response = self.client.post(
            reverse('totp_verify'), {'code': totp.current_code(self.secret)}
        )
        self.assertRedirects(response, reverse('dashboard'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_wrong_code_keeps_logged_out(self):
        self.client.post(
            reverse('login'), {'username': 'tfa', 'password': 'TfaSafe_2026!'}
        )
        response = self.client.post(reverse('totp_verify'), {'code': '000000'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '动态口令不正确')
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(**BASE_OVERRIDES)
class TOTPSetupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='setup', password='SetupSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.user, role='teacher')
        self.client.force_login(self.user)

    def test_bind_and_disable(self):
        response = self.client.get(reverse('totp_setup'))
        self.assertContains(response, '密钥')
        secret = self.client.session['totp_setup_secret']
        response = self.client.post(
            reverse('totp_setup'), {'action': 'enable', 'code': totp.current_code(secret)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '恢复码')
        self.assertTrue(
            TOTPDevice.objects.filter(user=self.user, confirmed=True).exists()
        )
        response = self.client.post(
            reverse('totp_setup'), {'action': 'disable', 'password': 'SetupSafe_2026!'}
        )
        self.assertRedirects(response, reverse('totp_setup'))
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())

    def test_disable_requires_password(self):
        TOTPDevice.objects.create(
            user=self.user, secret=totp.generate_secret(), confirmed=True
        )
        response = self.client.post(
            reverse('totp_setup'), {'action': 'disable', 'password': 'wrong'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '密码不正确')
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())


@override_settings(**{**BASE_OVERRIDES, 'TOTP_ENFORCE': True})
class TOTPEnforcementTests(TestCase):
    def test_unbound_admin_is_asked_to_bind(self):
        admin = User.objects.create_user(
            username='admin-tfa', password='AdminTfa_2026!', must_change_password=False
        )
        UserRole.objects.create(user=admin, role='admin')
        response = self.client.post(
            reverse('login'), {'username': 'admin-tfa', 'password': 'AdminTfa_2026!'}
        )
        self.assertRedirects(
            response, reverse('totp_setup'), fetch_redirect_response=False
        )
