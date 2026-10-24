# ruff: noqa: RUF012
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator

from school.models import Classroom, ClassStaff, DataDictionary, DictionaryItem, User


class PersonForm(forms.ModelForm):
    password = forms.CharField(
        label='初始 / 重置密码',
        required=False,
        widget=forms.PasswordInput,
        help_text='新建时留空使用默认密码 123456；修改时留空保留原密码。设置后首次登录必须修改。',
    )
    classrooms = forms.ModelMultipleChoiceField(
        label='所属教学班',
        queryset=Classroom.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ['username', 'full_name', 'student_no', 'is_active']
        labels = {'username': '登录名', 'student_no': '学号 / 工号', 'is_active': '允许登录'}
        help_texts = {'username': '', 'is_active': ''}

    def __init__(self, *args, kind, **kwargs):
        self.kind = kind
        super().__init__(*args, **kwargs)
        self.fields['username'].validators.append(UnicodeUsernameValidator())
        self.fields['student_no'].required = True
        self.fields['classrooms'].queryset = Classroom.objects.filter(
            deleted_at__isnull=True, archived=False
        )
        if kind == 'teacher':
            del self.fields['classrooms']
        elif self.instance.pk:
            self.fields['classrooms'].initial = self.instance.memberships.filter(
                active=True, classroom__archived=False
            ).values_list('classroom_id', flat=True)

    def clean(self):
        data = super().clean()
        if data.get('password') and data['password'] != '123456':
            validate_password(data['password'], self.instance)
        return data


class GrantForm(forms.ModelForm):
    classroom = forms.ModelChoiceField(label='教学班', queryset=Classroom.objects.none())

    class Meta:
        model = ClassStaff
        fields = ['classroom', 'can_edit', 'can_view_grades', 'can_export', 'active']
        labels = {
            'can_edit': '创建、修改、删除作业',
            'can_view_grades': '查看班级与学生结果',
            'can_export': '导出报表',
            'active': '启用本班授权',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['classroom'].queryset = Classroom.objects.filter(
            deleted_at__isnull=True, archived=False
        )

    def clean(self):
        data = super().clean()
        if data.get('can_export') and not data.get('can_view_grades'):
            self.add_error('can_export', '导出报表需同时授权查看结果。')
        return data


def dictionary_choices(code, current=''):
    items = list(
        DictionaryItem.objects.filter(
            dictionary__code=code, dictionary__active=True, active=True
        ).values_list('value', 'label')
    )
    if current and current not in dict(items):
        items.append((current, current + '（历史值）'))
    return [('', '请选择')] + items


class ClassForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ['code', 'name', 'course_name', 'term']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field, code in [('course_name', 'course'), ('term', 'term')]:
            choices = dictionary_choices(code, getattr(self.instance, field, ''))
            if len(choices) > 1:
                self.fields[field] = forms.ChoiceField(
                    label=self.fields[field].label,
                    choices=choices,
                    initial=getattr(self.instance, field, ''),
                )


class DictionaryForm(forms.ModelForm):
    class Meta:
        model = DataDictionary
        fields = ['code', 'name', 'description', 'active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['code'].disabled = True


class DictionaryItemForm(forms.ModelForm):
    class Meta:
        model = DictionaryItem
        fields = ['value', 'label', 'order', 'active']
