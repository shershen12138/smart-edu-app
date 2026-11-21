"""现行路由下认证与健康检查视图的单元测试（config.urls）。"""

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from school.models import User, UserRole


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class AuthViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.student = User.objects.create_user(
            username='stu',
            password='SafePassword_2026',
            full_name='学生',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.student, role='student')

    def test_login_page_renders(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)

    def test_login_redirects_authenticated_user(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('login'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_success(self):
        response = self.client.post(
            reverse('login'), {'username': 'stu', 'password': 'SafePassword_2026'}
        )
        self.assertRedirects(response, reverse('dashboard'))

    def test_failed_login_increments_throttle(self):
        import hashlib

        key = 'login:user:' + hashlib.sha256(b'stu').hexdigest()
        self.client.post(reverse('login'), {'username': 'stu', 'password': 'wrong'})
        self.assertEqual(cache.get(key), 1)
        self.client.post(reverse('login'), {'username': 'stu', 'password': 'wrong'})
        self.assertEqual(cache.get(key), 2)

    def test_throttle_blocks_after_ten_failures(self):
        import hashlib

        key = 'login:ip:' + hashlib.sha256(b'127.0.0.1').hexdigest()
        cache.set(key, 10, 600)
        response = self.client.post(
            reverse('login'), {'username': 'stu', 'password': 'SafePassword_2026'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '失败次数过多')

    def test_successful_login_clears_throttle(self):
        import hashlib

        key = 'login:user:' + hashlib.sha256(b'stu').hexdigest()
        # 未达到失败阈值（默认 5 次）时仍允许登录，并在成功后清零计数
        cache.set(key, 4, 600)
        self.client.post(
            reverse('login'), {'username': 'stu', 'password': 'SafePassword_2026'}
        )
        self.assertIsNone(cache.get(key))

    def test_logout_requires_post_and_redirects(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'))

    def test_password_change_updates_and_unlocks(self):
        self.student.must_change_password = True
        self.student.save()
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('password'),
            {
                'old_password': 'SafePassword_2026',
                'new_password1': 'AnotherSafe_2027!',
                'new_password2': 'AnotherSafe_2027!',
            },
        )
        self.assertRedirects(response, reverse('dashboard'))
        self.student.refresh_from_db()
        self.assertFalse(self.student.must_change_password)
        self.assertTrue(self.student.check_password('AnotherSafe_2027!'))

    def test_weak_existing_password_warns_after_login(self):
        weak = User.objects.create_user(
            username='weakuser', password='123456', must_change_password=False
        )
        UserRole.objects.create(user=weak, role='student')
        response = self.client.post(
            reverse('login'),
            {'username': 'weakuser', 'password': '123456'},
            follow=True,
        )
        # 工作台弹出可关闭的提醒，带确认按钮
        self.assertContains(response, 'id="weak-password-dialog"')
        self.assertContains(response, '密码安全提醒')
        self.assertContains(response, 'data-weak-password-close')
        # 提醒只出现一次：会话标记在渲染时已消费，刷新不再弹出
        again = self.client.get(reverse('dashboard'))
        self.assertNotContains(again, 'id="weak-password-dialog"')

    def test_strong_password_does_not_warn_after_login(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'stu', 'password': 'SafePassword_2026'},
            follow=True,
        )
        self.assertNotContains(response, 'id="weak-password-dialog"')

    def test_password_page_renders(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('password'))
        self.assertEqual(response.status_code, 200)

    def test_health_returns_ok(self):
        response = self.client.get(reverse('health'))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'status': 'ok'})
