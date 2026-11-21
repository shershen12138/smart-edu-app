"""返回按钮：每次返回都回到点进来的上一页，不串到其他模块。"""

from __future__ import annotations

import re

from django.test import TestCase, override_settings
from django.urls import reverse

from school.models import User, UserRole


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class BackNavigationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin',
            full_name='管理员',
            student_no='A-001',
            password='Password-2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.admin, role='admin')
        self.student = User.objects.create_user(
            username='student',
            full_name='学生',
            student_no='S-001',
            password='Password-2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.student, role='student')

    def _back_link(self, response) -> str:
        """取出页面顶部「返回上一层」按钮的地址。"""
        body = response.content.decode('utf-8')
        match = re.search(r'href="([^"]*_nav=back[^"]*)"', body)
        self.assertIsNotNone(match, '页面上没有返回上一层按钮')
        return match.group(1).replace('&amp;', '&')

    def test_back_follows_the_page_you_came_from(self):
        """管理员从「教学班管理」进「基本数据字典」，返回应回到教学班管理。"""
        self.client.force_login(self.admin)
        self.client.get(reverse('classes'))
        response = self.client.get(reverse('dictionaries'))
        self.assertEqual(self._back_link(response), f'{reverse("classes")}?_nav=back')

    def test_second_back_keeps_going_up_instead_of_bouncing(self):
        """点过返回之后再点返回，继续往上一层，而不是又跳回刚才那页。"""
        self.client.force_login(self.admin)
        self.client.get(reverse('classes'))
        self.client.get(reverse('dictionaries'))
        returned = self.client.get(f'{reverse("classes")}?_nav=back')
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(self._back_link(returned), '/?_nav=back')

    def test_back_without_history_uses_the_parent_page(self):
        """直接打开页面（没有访问历史）时，退回该页面固定的上一级。"""
        self.client.force_login(self.student)
        response = self.client.get(reverse('practice'))
        self.assertEqual(self._back_link(response), '/?_nav=back')

    def test_refresh_does_not_grow_the_chain(self):
        """刷新同一个页面不应该把访问链撑长，返回仍是上一页。"""
        self.client.force_login(self.admin)
        self.client.get(reverse('classes'))
        self.client.get(reverse('dictionaries'))
        self.client.get(reverse('dictionaries'))
        response = self.client.get(reverse('dictionaries'))
        self.assertEqual(self._back_link(response), f'{reverse("classes")}?_nav=back')

    def test_back_marker_is_not_repeated(self):
        """返回标记只加一次，重复渲染不会叠加参数。"""
        self.client.force_login(self.admin)
        self.client.get(reverse('classes'))
        response = self.client.get(f'{reverse("classes")}?_nav=back')
        self.assertEqual(self._back_link(response).count('_nav=back'), 1)
