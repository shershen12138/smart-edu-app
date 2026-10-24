from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from .accounts import AccountManager


class User(AbstractUser):
    objects = AccountManager()
    full_name = models.CharField('姓名', max_length=80)
    student_no = models.CharField('学工号', max_length=40, unique=True, null=True, blank=True)
    must_change_password = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    recovery_password = models.TextField(blank=True, editable=False)

    def set_password(self, raw_password):
        from django.conf import settings
        super().set_password(raw_password)
        # Temporary, explicitly requested local password recovery. Login still uses Django hashes.
        self.recovery_password = (raw_password or '') if getattr(settings, 'STORE_RECOVERY_PASSWORDS', False) else ''

    class Meta:
        db_table = 'users'

    def __str__(self):
        return f'{self.full_name or self.username} ({self.username})'

    def has_role(self, role):
        if getattr(self, 'active_role', '') and self.active_role != role:
            return False
        return self.is_active and (self.is_superuser or self.roles.filter(role=role).exists())


class UserRole(models.Model):
    ROLE_CHOICES = [
        ('student', '学生'),
        ('teacher', '教师'),
        ('assistant', '助教'),
        ('admin', '管理员'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='roles')
    role = models.CharField(max_length=12, choices=ROLE_CHOICES)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_roles'
        constraints = [models.UniqueConstraint(fields=['user', 'role'], name='unique_user_role')]


class Classroom(models.Model):
    code = models.CharField('班级编号', max_length=40, unique=True)
    name = models.CharField('班级名称', max_length=80)
    course_name = models.CharField('课程名称', max_length=80, default='Python 程序设计')
    course_code = models.CharField('课程编号', max_length=40, blank=True)
    term = models.CharField('学期', max_length=40)
    archived = models.BooleanField('已归档', default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'classes'

    def __str__(self):
        return f'{self.code} · {self.name} · {self.term}'


class ClassStudent(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='members')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'class_students'
        constraints = [
            models.UniqueConstraint(fields=['classroom', 'student'], name='unique_class_student')
        ]


class ClassStaff(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='staff')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='teaching')
    role = models.CharField(max_length=12, choices=[('teacher', '教师'), ('assistant', '助教')])
    can_edit = models.BooleanField(default=False)
    can_view_grades = models.BooleanField(default=True)
    can_export = models.BooleanField(default=False)
    can_archive = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = 'class_staff'
        constraints = [
            models.UniqueConstraint(fields=['classroom', 'user'], name='unique_class_staff')
        ]


class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160)
    detail = models.JSONField(default=dict)
    ip = models.GenericIPAddressField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']


class Problem(models.Model):
    code = models.CharField(max_length=40, unique=True)
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'problems'

    def __str__(self):
        return self.code


class ProblemVersion(models.Model):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField(default=1)
    title = models.CharField('标题', max_length=120)
    statement = models.TextField('题意')
    input_format = models.TextField('输入格式')
    output_format = models.TextField('输出格式')
    data_range = models.TextField('数据范围')
    knowledge = models.CharField('知识点', max_length=200, blank=True)
    difficulty = models.CharField(
        '难度',
        max_length=12,
        default='基础',
        choices=[('基础', '基础'), ('进阶', '进阶'), ('挑战', '挑战')],
    )
    estimated_minutes = models.PositiveIntegerField('预计分钟', default=20)
    template_code = models.TextField('初始代码', blank=True)
    reference_path = models.CharField(max_length=200)
    explanation = models.TextField('解析（学生不可见）', blank=True)
    time_ms = models.PositiveIntegerField(
        '时间限制（毫秒）',
        default=2000,
        validators=[MinValueValidator(100), MaxValueValidator(10000)],
    )
    memory_mb = models.PositiveIntegerField(
        '内存限制（MB）', default=128, validators=[MinValueValidator(32), MaxValueValidator(512)]
    )
    output_kb = models.PositiveIntegerField(
        '输出限制（KB）', default=64, validators=[MinValueValidator(1), MaxValueValidator(1024)]
    )
    comparison = models.CharField(
        '输出比较',
        max_length=16,
        choices=[('trim', '忽略行尾空格与末尾换行'), ('exact', '精确匹配')],
        default='trim',
    )
    runtime = models.CharField(max_length=100, default='python:3.12-slim')
    reference_verified = models.BooleanField(default=False)
    verification_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'problem_versions'
        constraints = [
            models.UniqueConstraint(fields=['problem', 'number'], name='unique_problem_version')
        ]

    def __str__(self):
        return f'{self.problem.code} · {self.title} v{self.number}'

    @property
    def evaluation_configured(self):
        return bool(self.reference_path) and self.cases.filter(is_sample=False).exists()


class TestCase(models.Model):
    version = models.ForeignKey(ProblemVersion, on_delete=models.CASCADE, related_name='cases')
    order = models.PositiveIntegerField()
    input_path = models.CharField(max_length=200)
    output_path = models.CharField(max_length=200)
    is_sample = models.BooleanField(default=False)
    hidden = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'test_cases'
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['version', 'order'], name='unique_case_order')
        ]


class Assignment(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='assignments')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    current_version = models.ForeignKey(
        'AssignmentVersion', on_delete=models.SET_NULL, null=True, related_name='+'
    )
    current_grade = models.ForeignKey(
        'GradeRevision', on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'assignments'


class SubmissionRuleVersion(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='rules')
    number = models.PositiveIntegerField()
    opens_at = models.DateTimeField('开放时间')
    deadline = models.DateTimeField('正常截止')
    late_deadline = models.DateTimeField('迟交截止', null=True, blank=True)
    max_attempts = models.PositiveIntegerField(
        '每题最多提交次数', default=20, validators=[MinValueValidator(1), MaxValueValidator(1000)]
    )
    interval_seconds = models.PositiveIntegerField(default=10)
    max_pending = models.PositiveIntegerField(default=2)
    max_size_kb = models.PositiveIntegerField(default=128)
    selection = models.CharField(
        '成绩选取',
        max_length=8,
        choices=[('best', '最高分'), ('latest', '最后一次')],
        default='best',
    )
    late_penalty = models.DecimalField(
        '迟交扣分比例（0～1）',
        max_digits=4,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )

    class Meta:
        db_table = 'submission_rule_versions'
        constraints = [
            models.UniqueConstraint(fields=['assignment', 'number'], name='unique_rule_version')
        ]


class AssignmentVersion(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    rule = models.ForeignKey(SubmissionRuleVersion, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=12, choices=[('draft', '草稿'), ('published', '已发布')], default='draft'
    )
    published_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    published_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'assignment_versions'
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'number'], name='unique_assignment_version'
            )
        ]

    def __str__(self):
        return self.title


class AssignmentQuestion(models.Model):
    version = models.ForeignKey(
        AssignmentVersion, on_delete=models.CASCADE, related_name='questions'
    )
    question_key = models.CharField(max_length=40)
    problem_version = models.ForeignKey(ProblemVersion, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=1)
    max_score = models.DecimalField(
        max_digits=7, decimal_places=2, default=100, validators=[MinValueValidator(1)]
    )

    class Meta:
        db_table = 'assignment_questions'
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(
                fields=['version', 'question_key'], name='unique_assignment_question'
            )
        ]


class ExtensionRequest(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='extensions')
    question_keys = models.JSONField(default=list)
    reason = models.TextField()
    status = models.CharField(
        max_length=12,
        choices=[
            ('pending', '待处理'),
            ('approved', '已批准'),
            ('rejected', '已拒绝'),
            ('revoked', '已撤销'),
        ],
        default='pending',
    )
    assistant_note = models.TextField(blank=True)
    decision = models.TextField(blank=True)
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    starts_at = models.DateTimeField(null=True)
    ends_at = models.DateTimeField(null=True)
    extra_attempts = models.PositiveIntegerField(default=3)
    penalty = models.DecimalField(max_digits=4, decimal_places=3, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'extension_requests'


class Submission(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submissions')
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='submissions')
    question = models.ForeignKey(AssignmentQuestion, on_delete=models.CASCADE)
    question_key = models.CharField(max_length=40)
    sequence = models.PositiveIntegerField()
    idempotency_key = models.UUIDField()
    code_path = models.CharField(max_length=200)
    code_hash = models.CharField(max_length=64)
    received_at = models.DateTimeField(default=timezone.now)
    kind = models.CharField(
        max_length=12, choices=[('normal', '正常'), ('late', '迟交'), ('extension', '补交')]
    )
    rule_snapshot = models.JSONField()
    extension = models.ForeignKey(ExtensionRequest, on_delete=models.SET_NULL, null=True)
    counted = models.BooleanField(default=True)

    class Meta:
        db_table = 'submissions'
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'idempotency_key'], name='unique_submission_key'
            ),
            models.UniqueConstraint(
                fields=['student', 'assignment', 'question_key', 'sequence'],
                name='unique_submission_sequence',
            ),
        ]


class GradeRevision(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='grades')
    number = models.PositiveIntegerField()
    version = models.ForeignKey(AssignmentVersion, on_delete=models.CASCADE)
    cutoff = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=200)
    roster_snapshot = models.JSONField(default=list)
    status = models.CharField(
        max_length=12,
        choices=[('processing', '重评中'), ('ready', '待发布'), ('published', '已发布')],
        default='ready',
    )
    published_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    published_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'grade_revisions'
        constraints = [
            models.UniqueConstraint(fields=['assignment', 'number'], name='unique_grade_revision')
        ]


class JudgeRun(models.Model):
    STATUS_CHOICES = [
        ('pending', '待派发'),
        ('queued', '排队中'),
        ('running', '评测中'),
        ('done', '已完成'),
        ('error', '系统异常'),
        ('superseded', '已作废'),
    ]
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='runs')
    revision = models.ForeignKey(
        GradeRevision, on_delete=models.CASCADE, null=True, related_name='runs'
    )
    question = models.ForeignKey(AssignmentQuestion, on_delete=models.CASCADE)
    execution = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default='pending', db_index=True
    )
    verdict = models.CharField(max_length=16, blank=True)
    base_score = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    error_code = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    heartbeat = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'judge_runs'
        constraints = [
            models.UniqueConstraint(fields=['submission', 'execution'], name='unique_execution')
        ]


class JudgeCaseResult(models.Model):
    run = models.ForeignKey(JudgeRun, on_delete=models.CASCADE, related_name='results')
    case = models.ForeignKey(TestCase, on_delete=models.CASCADE)
    verdict = models.CharField(max_length=16)
    elapsed_ms = models.PositiveIntegerField(default=0)
    memory_kb = models.PositiveIntegerField(null=True)

    class Meta:
        db_table = 'judge_case_results'
        constraints = [models.UniqueConstraint(fields=['run', 'case'], name='unique_run_case')]


class StudentGrade(models.Model):
    revision = models.ForeignKey(GradeRevision, on_delete=models.CASCADE, related_name='students')
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    name_snapshot = models.CharField(max_length=80)
    number_snapshot = models.CharField(max_length=40)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0)

    class Meta:
        db_table = 'student_grades'
        constraints = [
            models.UniqueConstraint(fields=['revision', 'student'], name='unique_student_grade')
        ]


class StudentQuestionGrade(models.Model):
    grade = models.ForeignKey(StudentGrade, on_delete=models.CASCADE, related_name='questions')
    question_key = models.CharField(max_length=40)
    question = models.ForeignKey(AssignmentQuestion, on_delete=models.CASCADE)
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, null=True)
    run = models.ForeignKey(JudgeRun, on_delete=models.CASCADE, null=True)
    base_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    deduction = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    final_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    class Meta:
        db_table = 'student_question_grades'
        constraints = [
            models.UniqueConstraint(fields=['grade', 'question_key'], name='unique_question_grade')
        ]


class Announcement(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=160)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'announcements'
        ordering = ['-created_at']


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    event = models.CharField(max_length=40)
    object_id = models.PositiveBigIntegerField(null=True)
    message = models.CharField(max_length=240)
    dedup_key = models.CharField(max_length=150, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']


from .course_models import (  # noqa: E402,F401
    DataDictionary, DictionaryItem, EvaluationPackage, Coursework, CourseworkItem,
    CourseworkSubmission, CourseworkQuestionResult, CourseworkCaseResult, PrivateFileCleanup,
    CourseworkPackageUpdate, CourseworkGradeHistory,
)
