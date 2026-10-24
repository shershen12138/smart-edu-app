# ruff: noqa: RUF012
from pathlib import Path, PurePosixPath

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from school.models import Coursework

from .access import classes_for
from .parsers import parse_manual_materials_archive, parse_package_archive


class WorkForm(forms.ModelForm):
    package_file = forms.FileField(
        label='机器批阅包',
        required=False,
        help_text=(
            '机器批阅使用：上传题目 DOCX、sample*.py、gold.py、func_info_list.txt '
            '和 data 目录组成的ZIP，不超过 10 MB。'
        ),
        widget=forms.FileInput(attrs={'accept': '.zip'}),
    )
    revision = forms.IntegerField(widget=forms.HiddenInput, initial=0)

    class Meta:
        model = Coursework
        fields = ['grading_mode', 'classroom', 'deadline']
        labels = {'classroom': '教学班'}
        widgets = {
            'grading_mode': forms.RadioSelect,
            'deadline': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}
            )
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                'grading_mode',
                'classroom',
                'package_file',
                'deadline',
                'revision',
            ]
        )
        self.fields['classroom'].queryset = classes_for(user, 'edit')
        self.fields['grading_mode'].help_text = (
            '机器批阅：学生提交一个 .py；非机器批阅：学生提交包含 1001.py 至 1005.py 的ZIP。'
        )
        if self.instance.pk:
            self.fields['revision'].initial = self.instance.revision
            self.fields['classroom'].disabled = True
            if self.instance.entries.exists():
                self.fields['grading_mode'].disabled = True
                self.fields['grading_mode'].help_text += ' 已有学生提交，不能再切换批阅方式。'
        else:
            self.fields['deadline'].initial = timezone.localtime().replace(
                second=0, microsecond=0
            ) + timezone.timedelta(days=7)
        if self.fields['classroom'].queryset.count() == 1:
            self.fields['classroom'].initial = self.fields['classroom'].queryset.first()

    def clean(self):
        data = super().clean()
        if data.get('deadline') and data['deadline'] <= timezone.now():
            self.add_error('deadline', '截止时间应晚于当前时间。')
        package_upload = data.get('package_file')
        mode = data.get('grading_mode') or 'automatic'
        changing_mode = bool(self.instance.pk and mode != self.instance.grading_mode)
        if (not self.instance.pk or changing_mode) and not package_upload:
            label = '机器批阅包' if mode == 'automatic' else '非机器批阅包'
            raise ValidationError(f'请上传{label}。')
        if package_upload and mode == 'automatic':
            raw = package_upload.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise ValidationError('自动批阅包不能超过 10 MB。')
            parsed = parse_package_archive(raw, package_upload.name)
            data['package_raw'] = raw
            data['package_data'] = parsed
            data['raw_file'] = parsed['document_raw']
            data['document_name'] = parsed['document_name']
            data['description'] = parsed['description']
            data['package'] = None
        if package_upload and mode == 'manual':
            raw = package_upload.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise ValidationError('非机器批阅包不能超过 10 MB。')
            parsed = parse_manual_materials_archive(raw, package_upload.name)
            data['materials_raw'] = raw
            data['materials_name'] = Path(package_upload.name.replace('\\', '/')).name
            data['manual_data'] = parsed
            data['raw_file'] = parsed['document_raw']
            data['document_name'] = parsed['document_name']
            data['description'] = parsed['description']
            data['package'] = None
        return data


class ItemForm(forms.Form):
    function_name = forms.RegexField(
        label='函数名', regex=r'^[A-Za-z_][A-Za-z0-9_]*$', max_length=80
    )
    title = forms.CharField(label='题目名称', max_length=160)
    points = forms.IntegerField(label='满分', min_value=1, max_value=1000, initial=10)


class PackageFileUpdateForm(forms.Form):
    package_member = forms.ChoiceField(label='要替换的包内文件')
    replacement_file = forms.FileField(label='新的单个文件')

    def __init__(self, *args, member_choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['package_member'].choices = member_choices
        self._member_labels = dict(member_choices)

    def clean(self):
        data = super().clean()
        member = data.get('package_member')
        upload = data.get('replacement_file')
        if not member or not upload:
            return data
        if upload.size > 4 * 1024 * 1024:
            self.add_error('replacement_file', '单个替换文件不能超过 4 MB。')
            return data
        expected = PurePosixPath(member).suffix.lower()
        actual = Path(upload.name).suffix.lower()
        if expected != actual:
            self.add_error(
                'replacement_file',
                f'文件类型必须与原文件一致（{expected or "无扩展名"}）。',
            )
        data['member_label'] = self._member_labels.get(member, member)
        return data
