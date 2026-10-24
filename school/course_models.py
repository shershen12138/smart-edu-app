"""Simplified coursework records. Historical assessment tables remain intact."""
# ruff: noqa: RUF012

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class DataDictionary(models.Model):
    code = models.SlugField('字典代码', max_length=60, unique=True)
    name = models.CharField('字典名称', max_length=80)
    description = models.CharField('说明', max_length=240, blank=True)
    active = models.BooleanField('启用', default=True)

    def __str__(self):
        return self.name


class DictionaryItem(models.Model):
    dictionary = models.ForeignKey(DataDictionary, on_delete=models.CASCADE, related_name='items')
    value = models.CharField('项目代码', max_length=60)
    label = models.CharField('显示名称', max_length=80)
    order = models.PositiveIntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['dictionary', 'value'], name='dict_value_unique')
        ]


class EvaluationPackage(models.Model):
    STATUS = [
        ('pending', '等待验证'),
        ('validating', '正在验证'),
        ('ready', '验证通过'),
        ('error', '验证失败'),
    ]
    code = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=160)
    owner = models.ForeignKey(
        'school.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='judge_packages'
    )
    description = models.TextField(blank=True)
    document_digest = models.CharField(max_length=64, blank=True, db_index=True)
    archive_path = models.CharField(max_length=200, blank=True)
    template_path = models.CharField(max_length=200, blank=True)
    reference_path = models.CharField(max_length=200, blank=True)
    spec = models.JSONField(default=list)
    digest = models.CharField(max_length=64)
    note = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default='pending', db_index=True)
    validation_error = models.CharField(max_length=240, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Coursework(models.Model):
    GRADING_MODES = [
        ('automatic', '机器批阅'),
        ('manual', '非机器批阅'),
    ]

    classroom = models.ForeignKey(
        'school.Classroom', on_delete=models.CASCADE, related_name='coursework'
    )
    owner = models.ForeignKey('school.User', on_delete=models.SET_NULL, null=True)
    title = models.CharField('作业名称', max_length=160)
    description = models.TextField('题目说明', blank=True)
    document_path = models.CharField(max_length=200, blank=True)
    document_name = models.CharField(max_length=200, blank=True)
    category = models.CharField('作业类型', max_length=60, blank=True)
    grading_mode = models.CharField(
        '批阅方式', max_length=12, choices=GRADING_MODES, default='automatic'
    )
    package = models.ForeignKey(EvaluationPackage, null=True, blank=True, on_delete=models.PROTECT)
    materials_path = models.CharField(max_length=200, blank=True)
    materials_name = models.CharField(max_length=200, blank=True)
    opens_at = models.DateTimeField('开放时间')
    deadline = models.DateTimeField('截止时间')
    max_attempts = models.PositiveIntegerField(
        '最多提交次数', default=20, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    status = models.CharField(
        '状态', max_length=12, default='draft', choices=[('draft', '草稿'), ('open', '已发布')]
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def max_score(self):
        return sum(item.points for item in self.items.all())


class CourseworkItem(models.Model):
    coursework = models.ForeignKey(Coursework, on_delete=models.CASCADE, related_name='items')
    function_name = models.CharField('函数名', max_length=80)
    title = models.CharField('题目名称', max_length=160)
    points = models.PositiveIntegerField(
        '满分', default=10, validators=[MinValueValidator(1), MaxValueValidator(1000)]
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['coursework', 'function_name'], name='course_function_unique'
            )
        ]


class CourseworkSubmission(models.Model):
    STATUS = [
        ('waiting', '待接入批阅'),
        ('pending', '等待批阅'),
        ('queued', '等待批阅'),
        ('running', '正在批阅'),
        ('review', '待教师批阅'),
        ('done', '批阅完成'),
        ('error', '批阅服务异常'),
    ]
    coursework = models.ForeignKey(Coursework, on_delete=models.CASCADE, related_name='entries')
    student = models.ForeignKey(
        'school.User', on_delete=models.CASCADE, related_name='course_entries'
    )
    sequence = models.PositiveIntegerField()
    request_id = models.UUIDField(default=uuid.uuid4, unique=True)
    source_path = models.CharField(max_length=200)
    source_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=STATUS, default='pending', db_index=True)
    total = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    error = models.CharField(max_length=240, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    heartbeat = models.DateTimeField(null=True)
    worker_token = models.UUIDField(null=True)
    finished_at = models.DateTimeField(null=True)
    graded_by = models.ForeignKey(
        'school.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='graded_entries',
    )

    class Meta:
        ordering = ['-submitted_at', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['coursework', 'student', 'sequence'], name='course_attempt_unique'
            )
        ]


class CourseworkQuestionResult(models.Model):
    submission = models.ForeignKey(
        CourseworkSubmission, on_delete=models.CASCADE, related_name='questions'
    )
    function_name = models.CharField(max_length=80)
    title = models.CharField(max_length=160)
    order = models.PositiveIntegerField()
    points = models.PositiveIntegerField()
    score = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    passed_cases = models.PositiveIntegerField(default=0)
    total_cases = models.PositiveIntegerField(default=0)
    verdict = models.CharField(max_length=20, default='PENDING')
    feedback = models.TextField(blank=True)

    class Meta:
        ordering = ['order', 'pk']


class PrivateFileCleanup(models.Model):
    path = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CourseworkCaseResult(models.Model):
    question = models.ForeignKey(
        CourseworkQuestionResult, on_delete=models.CASCADE, related_name='cases'
    )
    order = models.PositiveIntegerField()
    verdict = models.CharField(max_length=20)
    elapsed_ms = models.PositiveIntegerField(default=0)
    actual_output = models.TextField(blank=True)

    class Meta:
        ordering = ['order', 'pk']


class CourseworkPackageUpdate(models.Model):
    STATUS = [
        ('pending', '等待验证'),
        ('validating', '正在验证'),
        ('activated', '已生效'),
        ('error', '验证失败'),
        ('superseded', '已失效'),
    ]

    coursework = models.ForeignKey(
        Coursework, on_delete=models.CASCADE, related_name='package_updates'
    )
    previous_package = models.ForeignKey(
        EvaluationPackage,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='replaced_by_updates',
    )
    package = models.ForeignKey(
        EvaluationPackage,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='package_updates',
    )
    requested_by = models.ForeignKey(
        'school.User', null=True, on_delete=models.SET_NULL, related_name='package_updates'
    )
    changed_path = models.CharField(max_length=300)
    grading_changed = models.BooleanField(default=False)
    document_path = models.CharField(max_length=200)
    document_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    previous_materials_path = models.CharField(max_length=200, blank=True)
    materials_path = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default='pending', db_index=True)
    error = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class CourseworkGradeHistory(models.Model):
    submission = models.ForeignKey(
        CourseworkSubmission, on_delete=models.CASCADE, related_name='grade_history'
    )
    package = models.ForeignKey(
        EvaluationPackage, on_delete=models.PROTECT, related_name='historical_grades'
    )
    package_update = models.ForeignKey(
        CourseworkPackageUpdate, on_delete=models.CASCADE, related_name='archived_grades'
    )
    snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=12)
    total = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    error = models.CharField(max_length=240, blank=True)
    results = models.JSONField(default=list)
    finished_at = models.DateTimeField(null=True)
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-archived_at', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['submission', 'package_update'], name='course_grade_history_update_unique'
            )
        ]


class QualityReport(models.Model):
    """学生代码质量评测结果（静态分析，独立于机器判题得分）。"""

    submission = models.OneToOneField(
        CourseworkSubmission, on_delete=models.CASCADE, related_name='quality_report'
    )
    source_sha256 = models.CharField('源码摘要', max_length=64)
    total = models.DecimalField('总分', max_digits=5, decimal_places=1, default=0)
    payload = models.JSONField('评测明细', default=dict)
    markdown_key = models.CharField('Markdown 文件', max_length=255, blank=True)
    radar_key = models.CharField('雷达图文件', max_length=255, blank=True)
    generated_at = models.DateTimeField('生成时间', auto_now=True)

    class Meta:
        verbose_name = '代码质量报告'
        verbose_name_plural = '代码质量报告'


class CourseworkRubric(models.Model):
    """题目分析智能体产出的评分标准（Markdown + 结构化维度）。"""

    SOURCES = [
        ('llm', '大模型分析'),
        ('rule', '规则兜底'),
    ]

    coursework = models.OneToOneField(
        Coursework, on_delete=models.CASCADE, related_name='rubric'
    )
    markdown = models.TextField('评分标准 Markdown')
    knowledge_points = models.JSONField('考察知识点', default=list)
    dimensions = models.JSONField('评分维度', default=list)
    source = models.CharField('来源', max_length=8, choices=SOURCES, default='llm')
    model = models.CharField('模型', max_length=80, blank=True)
    prompt_version = models.CharField('提示词版本', max_length=20, default='v1')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '题目评分标准'
        verbose_name_plural = '题目评分标准'
