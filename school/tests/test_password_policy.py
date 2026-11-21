"""三级等保口令策略：复杂度校验、页面提示与各入口的拦截行为。"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from school.models import User, UserRole
from school.password_policy import HELP_TEXT, PasswordComplexityValidator
from school.portal.admin_forms import PersonForm


class PasswordComplexityValidatorTests(TestCase):
    def setUp(self):
        self.validator = PasswordComplexityValidator()

    def _messages(self, password):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate(password)
        return ' '.join(ctx.exception.messages)

    def test_accepts_any_three_of_four_categories(self):
        for password in (
            'SafePass2026',      # 大写 + 小写 + 数字
            'SAFEPASS_2026',     # 大写 + 数字 + 特殊
            'safepass_2026',     # 小写 + 数字 + 特殊
            'SafePass_2026',     # 四类齐全
            'Abcdef1!',
        ):
            with self.subTest(password=password):
                self.validator.validate(password)

    def test_rejects_only_two_categories(self):
        self.assertIn('字符种类', self._messages('safe2026'))

    def test_rejects_single_category(self):
        self.assertIn('字符种类', self._messages('safepassword'))

    def test_rejects_short_password(self):
        self.assertIn('长度', self._messages('Aa1!'))

    def test_rejects_password_with_space(self):
        self.assertIn('空格', self._messages('Safe Pass_2026'))

    def test_error_message_says_setting_failed(self):
        self.assertIn('密码设置失败', self._messages('123456'))

    def test_help_text_lists_every_requirement(self):
        for keyword in ('8 位', '至少三类', '大写字母', '小写字母', '数字', '特殊字符', '空格'):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, HELP_TEXT)
                self.assertIn(keyword, self.validator.get_help_text())


class PasswordChangePolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='stu1',
            password='SafePassword_2026!',
            full_name='学生',
            must_change_password=True,
        )
        UserRole.objects.create(user=self.user, role='student')
        self.client.force_login(self.user)

    def test_page_prompts_complexity_rules(self):
        response = self.client.get(reverse('password'))
        self.assertContains(response, '大写字母')
        self.assertContains(response, '特殊字符')
        # 每个密码框右侧都有显示 / 隐藏按钮
        self.assertContains(response, 'data-password-toggle')
        self.assertContains(response, 'class="password-field"')

    def test_weak_password_is_rejected_with_reason(self):
        response = self.client.post(
            reverse('password'),
            {
                'old_password': 'SafePassword_2026!',
                'new_password1': 'weakpassword',
                'new_password2': 'weakpassword',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '密码设置失败')
        # 校验失败后保留刚输入的内容，用户只需修改不符合规则的部分
        self.assertContains(response, 'value="weakpassword"')
        self.assertContains(response, 'value="SafePassword_2026!"')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('SafePassword_2026!'))

    def test_strong_password_is_accepted(self):
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


class AdminPasswordFormPolicyTests(TestCase):
    """管理员新建/重置密码走同一个校验器，错误信息能回显到表单。"""

    def setUp(self):
        self.student = User.objects.create_user(
            username='stu2',
            password='StudentSafe_2026!',
            full_name='学生二',
            student_no='9002',
            must_change_password=False,
        )
        UserRole.objects.create(user=self.student, role='student')

    def _form(self, password):
        return PersonForm(
            data={
                'username': 'stu2',
                'full_name': '学生二',
                'student_no': '9002',
                'is_active': 'on',
                'password': password,
            },
            instance=self.student,
            kind='student',
        )

    def test_weak_password_rejected_by_admin_form(self):
        form = self._form('weakpass')
        self.assertFalse(form.is_valid())
        self.assertIn('密码设置失败', str(form.errors['password']))
        # 管理员修正密码时不必重输，输入框带显示按钮
        rendered = str(form['password'])
        self.assertIn('value="weakpass"', rendered)
        self.assertIn('data-password-toggle', rendered)

    def test_strong_password_accepted_by_admin_form(self):
        form = self._form('ResetSafe_2026!')
        self.assertTrue(form.is_valid(), form.errors)
