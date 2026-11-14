"""用户级大模型配置：保存/清除/隔离，以及调用时只使用本人 Key。"""

import io
import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from school.models import User, UserLLMConfig, UserRole
from school.portal import llm_client


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    LLM_TIMEOUT=5,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class LLMConfigTests(TestCase):
    def setUp(self):
        self.teacher = self._user('teacher', 'teacher')
        self.student = self._user('student', 'student')

    def _user(self, username, role):
        user = User.objects.create_user(
            username=username,
            full_name=username,
            student_no=username,
            password='Password-2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def _payload(self, api_key='sk-abcdef0123456789'):
        return {
            'provider': 'deepseek',
            'base_url': 'https://api.deepseek.com',
            'model': 'deepseek-chat',
            'api_key': api_key,
            'next': reverse('practice'),
        }

    # ---- 客户端层 ----

    def test_save_requires_key_on_first_time(self):
        with self.assertRaisesMessage(llm_client.LLMConfigError, 'API Key'):
            llm_client.save_config(self.student, 'deepseek', 'https://api.deepseek.com', 'm', '')
        self.assertFalse(llm_client.configured(self.student))

    def test_blank_key_keeps_existing(self):
        llm_client.save_config(
            self.student, 'deepseek', 'https://api.deepseek.com', 'deepseek-chat', 'sk-1234567890'
        )
        llm_client.save_config(
            self.student, 'qwen', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus', ''
        )
        config = llm_client.get_config(self.student)
        self.assertEqual(config.provider, 'qwen')
        self.assertEqual(config.model, 'qwen-plus')
        self.assertEqual(config.api_key, 'sk-1234567890')

    def test_save_validates_url_and_model(self):
        with self.assertRaisesMessage(llm_client.LLMConfigError, 'http'):
            llm_client.save_config(self.student, 'custom', 'api.example.com', 'm', 'k')
        with self.assertRaisesMessage(llm_client.LLMConfigError, '模型名'):
            llm_client.save_config(self.student, 'custom', 'https://api.example.com', '', 'k')

    def test_mask_key_hides_middle(self):
        self.assertEqual(llm_client.mask_key('sk-abcdef0123456789'), 'sk-a***6789')
        self.assertEqual(llm_client.mask_key('short'), '***')
        self.assertEqual(llm_client.mask_key(''), '')

    def test_chat_uses_own_key_and_endpoint(self):
        llm_client.save_config(
            self.student, 'custom', 'https://llm.example.com/v1', 'my-model', 'sk-student-key'
        )
        response = io.BytesIO(
            json.dumps({'choices': [{'message': {'content': 'hi'}}]}).encode()
        )
        with mock.patch('urllib.request.urlopen', return_value=response) as urlopen:
            self.assertEqual(llm_client.chat([{'role': 'user', 'content': 'x'}], self.student), 'hi')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://llm.example.com/v1/chat/completions')
        self.assertIn('sk-student-key', request.headers['Authorization'])
        self.assertIn(b'my-model', request.data)

    def test_configs_are_isolated_between_users(self):
        llm_client.save_config(
            self.teacher, 'deepseek', 'https://api.deepseek.com', 'deepseek-chat', 'sk-teacher'
        )
        self.assertTrue(llm_client.configured(self.teacher))
        self.assertFalse(llm_client.configured(self.student))
        with self.assertRaises(llm_client.LLMNotConfigured):
            llm_client.chat([{'role': 'user', 'content': 'x'}], self.student)

    # ---- 视图层 ----

    def test_post_saves_and_redirects_back(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('llm_config'), self._payload())
        self.assertRedirects(response, reverse('practice'))
        config = UserLLMConfig.objects.get(user=self.student)
        self.assertEqual(config.model, 'deepseek-chat')
        self.assertEqual(config.api_key, 'sk-abcdef0123456789')

    def test_invalid_post_shows_error_and_saves_nothing(self):
        self.client.force_login(self.student)
        payload = self._payload()
        payload['api_key'] = ''
        response = self.client.post(reverse('llm_config'), payload)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserLLMConfig.objects.filter(user=self.student).exists())
        follow = self.client.get(reverse('practice'))
        self.assertContains(follow, 'API Key')

    def test_page_never_echoes_full_key(self):
        llm_client.save_config(
            self.student, 'deepseek', 'https://api.deepseek.com', 'deepseek-chat', 'sk-abcdef0123456789'
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('practice'))
        body = response.content.decode('utf-8')
        self.assertIn('sk-a***6789', body)
        self.assertNotIn('sk-abcdef0123456789', body)

    def test_clear_removes_config(self):
        llm_client.save_config(
            self.student, 'deepseek', 'https://api.deepseek.com', 'deepseek-chat', 'sk-123'
        )
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('llm_config_clear'), {'next': reverse('practice')}
        )
        self.assertRedirects(response, reverse('practice'))
        self.assertFalse(UserLLMConfig.objects.filter(user=self.student).exists())

    def test_post_rejects_external_next(self):
        self.client.force_login(self.student)
        payload = self._payload()
        payload['next'] = 'https://evil.example.com/phish'
        response = self.client.post(reverse('llm_config'), payload)
        self.assertRedirects(response, reverse('dashboard'))

    def test_requires_login(self):
        response = self.client.post(reverse('llm_config'), self._payload())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    # ---- 页面结构：弹窗与入口必须内联在 HTML 里（不依赖静态 JS 缓存） ----

    def test_sidebar_entry_and_inline_dialog(self):
        self.client.force_login(self.student)
        body = self.client.get(reverse('dashboard')).content.decode('utf-8')
        self.assertIn('data-llm-config-open', body)
        self.assertIn('id="llm-config-dialog"', body)
        self.assertIn('showModal', body)
        self.assertIn(reverse('llm_config'), body)
