"""大模型客户端：算法端统一配置优先；页面不提供个人配置入口。"""

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
    LLM_VERIFY_ON_SAVE=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class LLMConfigTests(TestCase):
    """客户端层：个人配置仍可作为本地开发兜底，但不再通过页面录入。"""

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

    # ---- 页面入口已删除 ----

    def test_config_urls_are_removed(self):
        self.client.force_login(self.student)
        for path in ('/llm-config/', '/llm-config/reveal/', '/llm-config/clear/'):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_pages_do_not_render_config_entry(self):
        self.client.force_login(self.student)
        for name in ('dashboard', 'practice'):
            body = self.client.get(reverse(name)).content.decode('utf-8')
            self.assertNotIn('data-llm-config-open', body)
            self.assertNotIn('llm-config-dialog', body)
            self.assertNotIn('模型配置', body)

    def test_status_message_points_to_admin(self):
        status = llm_client.status_text(self.student)
        self.assertIn('请联系管理员', status)
        self.assertNotIn('模型配置', status)


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    LLM_TIMEOUT=5,
    LLM_VERIFY_ON_SAVE=False,
    LLM_ALLOW_USER_OVERRIDE=False,
    LLM_BASE_URL='https://server.example.com/v1',
    LLM_MODEL='server-model',
    LLM_API_KEY='sk-server-key',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ServerConfigTests(TestCase):
    """算法端统一配置：优先级高于个人配置。"""

    def setUp(self):
        self.student = User.objects.create_user(
            username='student',
            full_name='student',
            student_no='S-001',
            password='Password-2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.student, role='student')

    def _ok_response(self):
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': 'hi'}}]}).encode())

    def _personal_config(self):
        return UserLLMConfig.objects.create(
            user=self.student,
            provider='custom',
            base_url='https://personal.example.com/v1',
            model='personal-model',
            api_key='sk-personal',
        )

    def test_server_config_wins_over_personal(self):
        self._personal_config()
        with mock.patch('urllib.request.urlopen', return_value=self._ok_response()) as urlopen:
            self.assertEqual(
                llm_client.chat([{'role': 'user', 'content': 'x'}], self.student), 'hi'
            )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://server.example.com/v1/chat/completions')
        self.assertIn('sk-server-key', request.headers['Authorization'])
        self.assertIn(b'server-model', request.data)

    def test_configured_without_personal_config(self):
        self.assertFalse(UserLLMConfig.objects.exists())
        self.assertTrue(llm_client.configured(self.student))

    def test_personal_config_cannot_be_saved(self):
        with self.assertRaisesMessage(llm_client.LLMConfigError, '算法端'):
            llm_client.save_config(
                self.student, 'deepseek', 'https://api.deepseek.com', 'deepseek-chat', 'sk-x'
            )
        self.assertFalse(UserLLMConfig.objects.exists())

    def test_status_reports_algorithm_side_without_key(self):
        status = llm_client.status_text(self.student)
        self.assertIn('算法端统一配置', status)
        self.assertIn('server-model', status)
        self.assertNotIn('sk-server-key', status)

    @override_settings(LLM_ALLOW_USER_OVERRIDE=True)
    def test_override_switch_uses_personal_config(self):
        llm_client.save_config(
            self.student,
            'custom',
            'https://personal.example.com/v1',
            'personal-model',
            'sk-personal',
        )
        with mock.patch('urllib.request.urlopen', return_value=self._ok_response()) as urlopen:
            llm_client.chat([{'role': 'user', 'content': 'x'}], self.student)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://personal.example.com/v1/chat/completions')
        self.assertIn('sk-personal', request.headers['Authorization'])
