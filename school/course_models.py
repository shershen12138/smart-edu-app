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


class StudentCapabilityProfile(models.Model):
    """学生综合能力画像：跨任务聚合布鲁姆六维与计算思维四维。

    分数由评测报告逐题得分率确定性聚合，大模型只负责归因与诊断；
    payload 与签名一起缓存，数据或提示词版本变化时自动重算。
    """

    SOURCES = [
        ('llm', '大模型诊断'),
        ('rule', '规则诊断'),
    ]

    student = models.OneToOneField(
        'school.User', on_delete=models.CASCADE, related_name='capability_profile'
    )
    signature = models.CharField('数据指纹', max_length=64)
    payload = models.JSONField('能力画像', default=dict)
    source = models.CharField('诊断来源', max_length=8, choices=SOURCES, default='rule')
    model = models.CharField('模型', max_length=80, blank=True)
    generated_at = models.DateTimeField('生成时间', auto_now=True)

    class Meta:
        verbose_name = '学生综合能力画像'
        verbose_name_plural = '学生综合能力画像'


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
    abilities = models.JSONField('主能力维度', default=list)
    source = models.CharField('来源', max_length=8, choices=SOURCES, default='llm')
    model = models.CharField('模型', max_length=80, blank=True)
    prompt_version = models.CharField('提示词版本', max_length=20, default='v1')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '题目评分标准'
        verbose_name_plural = '题目评分标准'


class PracticePlan(models.Model):
    """训练题智能体为学生生成的一次个性化训练（画像快照 + 题目集合）。"""

    STATUS = [
        ('ready', '已生成'),
        ('failed', '生成失败'),
    ]
    SOURCES = [
        ('llm', '大模型生成'),
        ('rule', '规则兜底'),
    ]

    student = models.ForeignKey(
        'school.User', on_delete=models.CASCADE, related_name='practice_plans'
    )
    classroom = models.ForeignKey(
        'school.Classroom', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='practice_plans',
    )
    profile_snapshot = models.JSONField('知识点画像快照', default=dict)
    status = models.CharField('状态', max_length=10, choices=STATUS, default='ready')
    source = models.CharField('来源', max_length=8, choices=SOURCES, default='llm')
    model = models.CharField('模型', max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '个性化训练计划'
        verbose_name_plural = '个性化训练计划'
        ordering = ['-created_at', '-pk']


class PracticeProblem(models.Model):
    """大模型生成的训练题。字段名与 ProblemVersion 保持一致，
    便于把实例直接传给 school.judge.run_case 做受限 Docker 批阅。"""

    DIFFICULTIES = [
        ('基础', '基础'),
        ('进阶', '进阶'),
    ]

    plan = models.ForeignKey(PracticePlan, on_delete=models.CASCADE, related_name='problems')
    knowledge_point = models.CharField('目标知识点', max_length=100)
    title = models.CharField('标题', max_length=120)
    statement = models.TextField('题面')
    template_code = models.TextField('初始代码（编辑器预填的函数框架）', blank=True)
    reference_code = models.TextField('参考答案（学生不可见）', blank=True)
    explanation = models.TextField('解析（学生不可见）', blank=True)
    difficulty = models.CharField('难度', max_length=8, choices=DIFFICULTIES, default='基础')
    # 函数式题（分层题库文档）：批阅调用该函数比对返回值，为空时走 stdin/stdout 判题。
    function_name = models.CharField('判定函数名', max_length=60, blank=True)
    function_argc = models.PositiveSmallIntegerField('函数参数个数', null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    time_ms = models.PositiveIntegerField('时间限制（毫秒）', default=2000)
    memory_mb = models.PositiveIntegerField('内存限制（MB）', default=128)
    output_kb = models.PositiveIntegerField('输出限制（KB）', default=64)
    comparison = models.CharField(
        '输出比较', max_length=16,
        choices=[('trim', '忽略行尾空格与末尾换行'), ('exact', '精确匹配')],
        default='trim',
    )
    runtime = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = '训练题'
        verbose_name_plural = '训练题'
        ordering = ['order', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'order'], name='practice_order_unique')
        ]

    def __str__(self):
        return f'{self.knowledge_point} · {self.title}'


class PracticeCase(models.Model):
    problem = models.ForeignKey(PracticeProblem, on_delete=models.CASCADE, related_name='cases')
    order = models.PositiveIntegerField()
    input_path = models.CharField(max_length=200)
    output_path = models.CharField(max_length=200)
    is_sample = models.BooleanField(default=False)

    class Meta:
        verbose_name = '训练题用例'
        verbose_name_plural = '训练题用例'
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['problem', 'order'], name='practice_case_order_unique')
        ]


class PracticeAttempt(models.Model):
    """学生对训练题的一次提交与批阅结果，不计入正式作业成绩。"""

    problem = models.ForeignKey(
        PracticeProblem, on_delete=models.CASCADE, related_name='attempts'
    )
    student = models.ForeignKey(
        'school.User', on_delete=models.CASCADE, related_name='practice_attempts'
    )
    code_path = models.CharField(max_length=200)
    score = models.DecimalField(max_digits=5, decimal_places=1, null=True)
    passed_cases = models.PositiveIntegerField(default=0)
    total_cases = models.PositiveIntegerField(default=0)
    verdict = models.CharField(max_length=20, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        verbose_name = '训练题提交'
        verbose_name_plural = '训练题提交'
        ordering = ['-created_at', '-pk']


class PracticeCaseResult(models.Model):
    """训练题逐用例批阅明细：结果、耗时与学生返回值/输出。"""

    attempt = models.ForeignKey(
        PracticeAttempt, on_delete=models.CASCADE, related_name='case_results'
    )
    order = models.PositiveIntegerField()
    verdict = models.CharField(max_length=20, default='PENDING')
    elapsed_ms = models.PositiveIntegerField(default=0)
    actual_output = models.TextField('学生返回值或输出', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '训练题用例结果'
        verbose_name_plural = '训练题用例结果'
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'order'], name='practice_case_result_order_unique'
            )
        ]
