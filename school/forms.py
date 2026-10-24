from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from .models import User, UserRole, Classroom, ProblemVersion, SubmissionRuleVersion, Announcement


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='登录名',
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        label='密码', widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'})
    )


class AccountForm(forms.Form):
    username = forms.CharField(
        label='登录名', max_length=150, validators=[UnicodeUsernameValidator()]
    )
    full_name = forms.CharField(label='姓名', max_length=80)
    student_no = forms.CharField(label='学号 / 工号', max_length=40)
    email = forms.EmailField(label='邮箱（可选）', required=False)
    roles = forms.MultipleChoiceField(
        label='系统身份', choices=UserRole.ROLE_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    password = forms.CharField(label='初始密码（首次登录必须修改）', widget=forms.PasswordInput)

    def clean(self):
        data = super().clean()
        if User.objects.filter(username=data.get('username')).exists():
            self.add_error('username', '登录名已存在。')
        if data.get('student_no') and User.objects.filter(student_no=data['student_no']).exists():
            self.add_error('student_no', '学工号已存在。')
        if data.get('password'):
            validate_password(
                data['password'],
                User(username=data.get('username', ''), full_name=data.get('full_name', '')),
            )
        return data


class ProfileForm(forms.Form):
    email = forms.EmailField(label='联系邮箱（可选）', required=False)
    active_role = forms.ChoiceField(label='当前工作身份', required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        roles = set(user.roles.values_list('role', flat=True))
        if settings.ROOT_URLCONF != 'config.legacy_urls':
            roles.discard('assistant')
        self.fields['active_role'].choices = [('', '综合工作台')] + [
            (value, label) for value, label in UserRole.ROLE_CHOICES if value in roles
        ]


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ['code', 'name', 'course_name', 'course_code', 'term']


class StaffForm(forms.Form):
    user = forms.ModelChoiceField(label='任课人员', queryset=User.objects.filter(is_active=True))
    role = forms.ChoiceField(
        label='班内职务', choices=[('teacher', '负责教师'), ('assistant', '助教')]
    )
    can_edit = forms.BooleanField(label='编辑题目与作业草稿', required=False)
    can_view_grades = forms.BooleanField(label='查看成绩', required=False, initial=True)
    can_export = forms.BooleanField(label='导出成绩', required=False)
    can_archive = forms.BooleanField(label='归档后查询', required=False)
    expires_at = forms.DateTimeField(
        label='授权截止（可选）',
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )


class ProblemForm(forms.ModelForm):
    template_code = forms.CharField(
        label='代码模板',
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={'rows': 5, 'class': 'code'}),
    )

    class Meta:
        model = ProblemVersion
        fields = [
            'title',
            'statement',
            'input_format',
            'output_format',
            'data_range',
            'knowledge',
            'difficulty',
            'estimated_minutes',
            'template_code',
            'explanation',
            'time_ms',
            'memory_mb',
            'output_kb',
            'comparison',
        ]
        widgets = {
            key: forms.Textarea(attrs={'rows': 3})
            for key in ['statement', 'input_format', 'output_format', 'data_range', 'explanation']
        }
        widgets['template_code'] = forms.Textarea(attrs={'rows': 5, 'class': 'code'})


class CaseForm(forms.Form):
    input = forms.CharField(
        label='输入',
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'code'}),
    )
    output = forms.CharField(
        label='标准输出',
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'code'}),
    )
    description = forms.CharField(label='说明', required=False)
    is_sample = forms.BooleanField(label='公开样例（用于展示，不参与计分）', required=False)
    enabled = forms.BooleanField(label='使用这个用例', required=False)


CaseFormSet = forms.formset_factory(CaseForm, extra=3, min_num=0, max_num=50, validate_max=True)


class AssignmentForm(forms.Form):
    edit_token = forms.CharField(required=False, widget=forms.HiddenInput)
    title = forms.CharField(label='作业标题', max_length=160)
    description = forms.CharField(
        label='作业说明', required=False, widget=forms.Textarea(attrs={'rows': 3})
    )
    opens_at = forms.DateTimeField(
        label='开放时间', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'})
    )
    deadline = forms.DateTimeField(
        label='正常截止', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'})
    )
    late_deadline = forms.DateTimeField(
        label='迟交截止（可选）',
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )
    max_attempts = forms.IntegerField(
        label='每题最多提交次数', min_value=1, max_value=1000, initial=20
    )
    selection = forms.ChoiceField(
        label='成绩选取方式', choices=[('best', '最高分'), ('latest', '最后一次')]
    )
    late_penalty = forms.DecimalField(
        label='迟交扣分比例（如 0.1 表示扣 10%）',
        min_value=0,
        max_value=1,
        initial=0,
        decimal_places=3,
    )
    problems = forms.ModelMultipleChoiceField(
        label='选择题目',
        queryset=ProblemVersion.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )
    points = forms.DecimalField(
        label='新增题目默认满分',
        min_value=1,
        max_value=1000,
        decimal_places=2,
        initial=100,
    )

    def __init__(self, *args, classroom, version=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .teaching import latest_problems

        self.fields['problems'].queryset = latest_problems(classroom)
        self.fields['problems'].label_from_instance = lambda p: (
            f'{p.problem.code} · {p.title}' + ('' if p.reference_verified else '（评测待就绪）')
        )
        if version:
            for question in version.questions.select_related('problem_version'):
                self.fields[f'score_{question.problem_version.problem_id}'] = forms.DecimalField(
                    label=f'题目满分：{question.problem_version.title}',
                    required=False,
                    min_value=1,
                    max_value=1000,
                    decimal_places=2,
                    initial=question.max_score,
                )

    def clean(self):
        data = super().clean()
        start, end, late = data.get('opens_at'), data.get('deadline'), data.get('late_deadline')
        if start and end and start >= end:
            raise ValidationError('截止时间应晚于开放时间。')
        if late and end and late <= end:
            raise ValidationError('迟交截止应晚于正常截止。')
        problems = data.get('problems', [])
        if len({p.problem_id for p in problems}) != len(problems):
            raise ValidationError('同一道题不能重复选择。')
        return data


class SubmissionForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    code = forms.CharField(
        label='Python 代码',
        required=False,
        strip=False,
        widget=forms.Textarea(
            attrs={
                'rows': 18,
                'class': 'code',
                'spellcheck': 'false',
                'placeholder': '# 在这里编写 Python 代码',
            }
        ),
    )
    file = forms.FileField(
        label='或上传 .py 文件',
        required=False,
        widget=forms.ClearableFileInput(attrs={'accept': '.py'}),
    )

    def clean(self):
        data = super().clean()
        upload = data.get('file')
        if upload:
            if data.get('code', '').strip():
                raise ValidationError('粘贴代码和上传文件请选择一种。')
            if not upload.name.lower().endswith('.py') or upload.size > 128 * 1024:
                raise ValidationError('请上传不超过 128 KB 的 .py 文件。')
            try:
                data['code'] = upload.read().decode('utf-8-sig')
            except UnicodeDecodeError:
                raise ValidationError('文件必须采用 UTF-8 编码。')
        if not data.get('code', '').strip():
            raise ValidationError('请填写代码或选择文件。')
        return data


class ExtensionForm(forms.Form):
    reason = forms.CharField(
        label='补交原因', min_length=5, max_length=1000, widget=forms.Textarea(attrs={'rows': 4})
    )


class ExtensionDecisionForm(forms.Form):
    question_keys = forms.MultipleChoiceField(
        label='允许补交的题目（不选表示全部题目）',
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    approve = forms.ChoiceField(label='处理结果', choices=[('yes', '批准'), ('no', '拒绝')])
    starts_at = forms.DateTimeField(
        label='补交开放',
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )
    ends_at = forms.DateTimeField(
        label='补交截止',
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )
    attempts = forms.IntegerField(label='每题新增次数', min_value=1, max_value=1000, initial=3)
    penalty = forms.DecimalField(
        label='扣分比例', min_value=0, max_value=1, initial=0, decimal_places=3
    )
    decision = forms.CharField(
        label='处理说明', required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 3})
    )

    def __init__(self, *args, assignment, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['question_keys'].choices = (
            [
                (q.question_key, q.problem_version.title)
                for q in assignment.current_version.questions.select_related('problem_version')
            ]
            if assignment.current_version
            else []
        )


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'content', 'expires_at']
        labels = {'title': '标题', 'content': '内容', 'expires_at': '到期时间（可选）'}
        widgets = {
            'content': forms.Textarea(attrs={'rows': 5}),
            'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
