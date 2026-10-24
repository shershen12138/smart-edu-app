from django import forms
from django.core.exceptions import ValidationError

from .parsers import parse_manual_submission_archive


class SubmitForm(forms.Form):
    source = forms.FileField(
        label='Python 作业文件', widget=forms.FileInput(attrs={'accept': '.py'})
    )
    request_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, grading_mode='automatic', required_files=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.grading_mode = grading_mode
        self.required_files = required_files or []
        if grading_mode == 'manual':
            self.fields['source'].label = '第10章答案ZIP'
            self.fields['source'].help_text = (
                '请上传包含 1001.py 至 1005.py 的ZIP文件。'
                '教师提供的数据文件和程序生成的结果文件无需提交。'
            )
            self.fields['source'].widget.attrs['accept'] = '.zip'

    def clean_source(self):
        upload = self.cleaned_data['source']
        if self.grading_mode == 'manual':
            if not upload.name.lower().endswith('.zip') or upload.size > 2 * 1024 * 1024:
                raise ValidationError('请上传不超过 2 MB 的ZIP文件。')
            return parse_manual_submission_archive(
                upload.read(2 * 1024 * 1024 + 1), upload.name, self.required_files
            )
        if not upload.name.lower().endswith('.py') or upload.size > 128 * 1024:
            raise ValidationError('请上传不超过 128 KB 的 .py 文件。')
        try:
            source = upload.read().decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValidationError('Python 文件请保存为 UTF-8 编码。') from exc
        if not source.strip() or '\x00' in source:
            raise ValidationError('文件不能为空或包含无效字符。')
        return source


class ManualReviewForm(forms.Form):
    def __init__(self, *args, questions, **kwargs):
        super().__init__(*args, **kwargs)
        self.questions = list(questions)
        for question in self.questions:
            self.fields[f'score_{question.pk}'] = forms.DecimalField(
                label=f'{question.title} 得分',
                min_value=0,
                max_value=question.points,
                max_digits=12,
                decimal_places=2,
                initial=question.score,
                help_text=f'本题满分 {question.points} 分',
            )
            self.fields[f'feedback_{question.pk}'] = forms.CharField(
                label=f'{question.title} 评语',
                required=False,
                max_length=2000,
                initial=question.feedback,
                widget=forms.Textarea(attrs={'rows': 2}),
            )

    def reviews(self):
        return [
            {
                'question_id': question.pk,
                'score': self.cleaned_data[f'score_{question.pk}'],
                'feedback': self.cleaned_data[f'feedback_{question.pk}'].strip(),
            }
            for question in self.questions
        ]
