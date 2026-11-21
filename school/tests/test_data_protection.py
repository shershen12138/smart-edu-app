"""数据保密性：API Key 与口令恢复副本加密落库、个人信息脱敏与敏感查看审计。"""

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from school.models import AuditLog, User, UserLLMConfig, UserRole
from school.templatetags.portal_tags import mask_email, mask_student_no

# 只允许读取测试确实需要的“表.列”，避免 f-string 拼 SQL 的写法被复制到业务代码
ALLOWED_RAW_COLUMNS = {
    ('users', 'recovery_password'),
    ('user_llm_configs', 'api_key'),
}


def raw_column(table, column, pk):
    if (table, column) not in ALLOWED_RAW_COLUMNS:
        raise ValueError(f'未登记的原始列读取：{table}.{column}')
    with connection.cursor() as cursor:
        # 表名/列名已过白名单，值仍然使用占位符绑定
        cursor.execute(f'SELECT {column} FROM {table} WHERE id = %s', [pk])
        row = cursor.fetchone()
    return row[0] if row else None


BASE_OVERRIDES = dict(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)


@override_settings(STORE_RECOVERY_PASSWORDS=True, **BASE_OVERRIDES)
class EncryptedFieldTests(TestCase):
    def test_api_key_is_encrypted_at_rest(self):
        user = User.objects.create_user(
            username='llmuser', password='LlmSafe_2026!', must_change_password=False
        )
        config = UserLLMConfig.objects.create(
            user=user,
            provider='deepseek',
            base_url='https://api.deepseek.com',
            model='deepseek-chat',
            api_key='sk-secret-123',
        )
        stored = raw_column('user_llm_configs', 'api_key', config.pk)
        self.assertTrue(stored.startswith('gAAAAA'))
        self.assertNotIn('sk-secret-123', stored)
        # 业务代码读取到的仍是明文 Key
        self.assertEqual(UserLLMConfig.objects.get(pk=config.pk).api_key, 'sk-secret-123')

    def test_recovery_password_is_encrypted_at_rest(self):
        user = User.objects.create_user(
            username='recuser', password='RecSafe_2026!', must_change_password=False
        )
        stored = raw_column('users', 'recovery_password', user.pk)
        self.assertTrue(stored.startswith('gAAAAA'))
        self.assertNotIn('RecSafe_2026!', stored)
        user.refresh_from_db()
        self.assertEqual(user.recovery_password, 'RecSafe_2026!')

    def test_recovery_password_not_stored_by_default(self):
        with override_settings(STORE_RECOVERY_PASSWORDS=False):
            user = User.objects.create_user(
                username='norec', password='NoRecSafe_2026!', must_change_password=False
            )
        self.assertEqual(raw_column('users', 'recovery_password', user.pk), '')


class MaskFilterTests(SimpleTestCase):
    def test_mask_student_no(self):
        self.assertEqual(mask_student_no('2026010101'), '20******01')
        self.assertEqual(mask_student_no('1234'), '1234')
        self.assertEqual(mask_student_no(''), '')

    def test_mask_email(self):
        self.assertEqual(mask_email('student@example.com'), 's******@example.com')
        self.assertEqual(mask_email('a@example.com'), '*@example.com')


@override_settings(STORE_RECOVERY_PASSWORDS=True, **BASE_OVERRIDES)
class RecoveryPasswordAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin2', password='AdminSafe_2026!', must_change_password=False
        )
        UserRole.objects.create(user=self.admin, role='admin')
        self.student = User.objects.create_user(
            username='stu9',
            password='StuSafe_2026!',
            full_name='学生九',
            student_no='9009',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.student, role='student')
        self.client.force_login(self.admin)

    def test_viewing_recovery_password_is_audited(self):
        response = self.client.get(
            reverse('person_edit', args=['student', self.student.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AuditLog.objects.filter(action='user.password_view').exists()
        )
