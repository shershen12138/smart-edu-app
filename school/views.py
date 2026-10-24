import csv
import io
import uuid
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import Q, Max, Avg, Count, F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import *
from .forms import *
from .permissions import *
from .services import *
from .storage import read_private, save_private
from .imports import preview_import, commit_import, HEADERS
from .teaching import latest_drafts


def form_page(request, title, form, **context):
    return render(request, 'school/form.html', {'title': title, 'form': form, **context})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST':
        import hashlib

        ip = request.META.get('REMOTE_ADDR', 'unknown')
        name = request.POST.get('username', '').strip().lower()
        keys = [
            'login:ip:' + hashlib.sha256(ip.encode()).hexdigest(),
            'login:user:' + hashlib.sha256(name.encode()).hexdigest(),
        ]
        if any(cache.get(key, 0) >= 10 for key in keys):
            form.add_error(None, '失败次数过多，请 10 分钟后重试。')
        elif form.is_valid():
            login(request, form.get_user())
            for key in keys:
                cache.delete(key)
            audit(request.user, 'auth.login', 'session', request=request)
            return redirect('dashboard')
        else:
            for key in keys:
                cache.set(key, cache.get(key, 0) + 1, 600)
            audit(None, 'auth.failed', 'session', request=request)
    return render(request, 'school/login.html', {'form': form, 'title': '登录'})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def password_view(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=['must_change_password'])
        update_session_auth_hash(request, user)
        audit(user, 'auth.password_change', 'self')
        messages.success(request, '密码已更新。')
        return redirect('dashboard')
    return form_page(
        request,
        '修改密码',
        form,
        description='首次使用需要设置新密码。忘记密码时请联系管理员核验身份后重置。',
    )


@login_required
def profile_view(request):
    form = ProfileForm(
        request.POST or None,
        user=request.user,
        initial={
            'email': request.user.email,
            'active_role': request.session.get('active_role', ''),
        },
    )
    if request.method == 'POST' and form.is_valid():
        request.user.email = form.cleaned_data['email']
        request.user.save(update_fields=['email'])
        request.session['active_role'] = form.cleaned_data['active_role']
        audit(request.user, 'profile.update', 'self')
        messages.success(request, '个人资料和工作身份已更新。')
        return redirect('dashboard')
    return form_page(
        request,
        '个人中心',
        form,
        description=f'{request.user.full_name} · {request.user.student_no or request.user.username}。姓名、学工号及身份授权由管理员维护。',
    )


@login_required
def dashboard(request):
    classes = visible_classes(request.user)
    assignments = (
        Assignment.objects.filter(classroom__in=classes, current_version__isnull=False)
        .select_related('current_version__rule', 'classroom')
        .order_by('-created_at')
    )
    editable_classes = [c.pk for c in classes if permitted(request.user, c, 'edit')]
    drafts = latest_drafts(editable_classes)
    published_count = assignments.count()
    assignments = assignments.exclude(pk__in=drafts.values('assignment_id'))
    learning = student_workspace(request.user)
    submissions = Submission.objects.filter(student=request.user).select_related(
        'question__problem_version'
    )[:5]
    announcements = Announcement.objects.filter(
        Q(classroom__isnull=True) | Q(classroom__in=classes)
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now()))[:5]
    return render(
        request,
        'school/dashboard.html',
        {
            'title': '学习工作台' if learning else '教学工作台',
            'classes': classes,
            'assignments': assignments[:12],
            'drafts': drafts[:6],
            'submissions': submissions,
            'announcements': announcements,
            'stats': [
                ('教学班', classes.count()),
                ('已发布作业', published_count),
                ('我的提交', request.user.submissions.count())
                if learning
                else ('待发布作业', drafts.count()),
                ('未读通知', request.user.notifications.filter(read_at__isnull=True).count()),
            ],
        },
    )


@login_required
def classes_view(request):
    return render(
        request,
        'school/classes.html',
        {'title': '教学班', 'classes': visible_classes(request.user)},
    )


@login_required
def class_create(request):
    require_admin(request.user)
    form = ClassroomForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        classroom = form.save()
        audit(request.user, 'class.create', f'class:{classroom.pk}')
        return redirect('class_detail', pk=classroom.pk)
    return form_page(request, '新建教学班', form)


@login_required
def class_detail(request, pk):
    classroom = get_object_or_404(visible_classes(request.user), pk=pk)
    staff_form = StaffForm(request.POST if request.POST.get('action') == 'staff' else None)
    if request.method == 'POST':
        require_admin(request.user)
        action = request.POST.get('action')
        try:
            if action == 'member':
                student = get_object_or_404(User, pk=request.POST.get('student'))
                set_membership(
                    request.user, classroom, student, request.POST.get('active', '1') == '1'
                )
            elif action == 'staff' and staff_form.is_valid():
                data = dict(staff_form.cleaned_data)
                user, role = data.pop('user'), data.pop('role')
                set_staff(request.user, classroom, user, role, **data)
            elif action == 'revoke':
                staff = get_object_or_404(
                    ClassStaff, pk=request.POST.get('staff'), classroom=classroom
                )
                staff.active = False
                staff.save(update_fields=['active'])
                audit(request.user, 'staff.revoke', f'staff:{staff.pk}')
            elif action == 'archive':
                classroom.archived = not classroom.archived
                classroom.save(update_fields=['archived'])
                audit(
                    request.user,
                    'class.archive',
                    f'class:{classroom.pk}',
                    {'archived': classroom.archived},
                )
            else:
                raise ValidationError('请检查表单内容。')
            messages.success(request, '教学班配置已保存。')
            return redirect('class_detail', pk=pk)
        except ValidationError as exc:
            messages.error(request, '；'.join(exc.messages))
    can_roster = is_admin(request.user) or permitted(request.user, classroom)
    drafts = (
        latest_drafts([pk])
        if permitted(request.user, classroom, 'edit')
        else AssignmentVersion.objects.none()
    )
    return render(
        request,
        'school/class_detail.html',
        {
            'title': classroom.name,
            'back_url': reverse('classes'),
            'back_label': '返回教学班列表',
            'drafts': drafts,
            'classroom': classroom,
            'members': classroom.members.select_related('student') if can_roster else [],
            'staff': classroom.staff.select_related('user') if can_roster else [],
            'staff_form': staff_form,
            'student_choices': User.objects.filter(is_active=True, roles__role='student')
            if is_admin(request.user)
            else [],
            'can_edit': permitted(request.user, classroom, 'edit'),
            'can_publish': permitted(request.user, classroom, 'publish'),
            'assignments': classroom.assignments.filter(current_version__isnull=False)
            .exclude(pk__in=drafts.values('assignment_id'))
            .select_related('current_version'),
        },
    )


@login_required
def users_view(request):
    require_admin(request.user)
    users = User.objects.order_by('username').prefetch_related('roles')
    query = request.GET.get('q', '').strip()
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(full_name__icontains=query)
            | Q(student_no__icontains=query)
        )
    return render(
        request,
        'school/users.html',
        {
            'title': '用户与身份',
            'users': Paginator(users, 30).get_page(request.GET.get('page')),
            'query': query,
        },
    )


@login_required
def user_create(request):
    require_admin(request.user)
    form = AccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            data = dict(form.cleaned_data)
            roles = data.pop('roles')
            user = User.objects.create_user(**data)
            for role in roles:
                UserRole.objects.create(user=user, role=role, granted_by=request.user)
            audit(request.user, 'user.create', f'user:{user.pk}', {'roles': roles})
        messages.success(request, '账号已创建，请将初始密码单独告知本人。')
        return redirect('users')
    return form_page(request, '创建账号', form)


@login_required
def user_detail(request, pk):
    require_admin(request.user)
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=pk)
                action = request.POST.get('action')
                if user.pk == request.user.pk and action in ('toggle', 'roles', 'reset'):
                    raise ValidationError(
                        '请通过其他管理员管理当前账号；本人密码请在修改密码页处理。'
                    )
                if action == 'toggle':
                    if user.is_superuser:
                        raise ValidationError('初始超级管理员不能在此停用。')
                    user.is_active = not user.is_active
                    user.save(update_fields=['is_active'])
                elif action == 'reset':
                    password = request.POST.get('password', '')
                    validate_password(password, user)
                    user.set_password(password)
                    user.must_change_password = True
                    user.save(update_fields=['password', 'must_change_password'])
                elif action == 'roles':
                    roles = request.POST.getlist('roles')
                    if not roles or not set(roles) <= dict(UserRole.ROLE_CHOICES).keys():
                        raise ValidationError('请选择有效身份。')
                    UserRole.objects.filter(user=user).exclude(role__in=roles).delete()
                    for role in roles:
                        UserRole.objects.get_or_create(
                            user=user, role=role, defaults={'granted_by': request.user}
                        )
                    if 'student' not in roles:
                        ClassStudent.objects.filter(student=user, active=True).update(
                            active=False, left_at=timezone.now()
                        )
                    ClassStaff.objects.filter(user=user).exclude(role__in=roles).update(
                        active=False
                    )
                elif action == 'profile':
                    name = request.POST.get('full_name', '').strip()
                    number = request.POST.get('student_no', '').strip()
                    if not name or len(name) > 80 or len(number) > 40:
                        raise ValidationError('姓名或学工号格式不正确。')
                    user.full_name = name
                    user.student_no = number or None
                    user.save(update_fields=['full_name', 'student_no'])
                else:
                    raise ValidationError('未知操作。')
                audit(
                    request.user,
                    'user.' + action,
                    f'user:{pk}',
                    {'roles': request.POST.getlist('roles')} if action == 'roles' else {},
                )
            messages.success(request, '账号信息已更新。')
            return redirect('user_detail', pk=pk)
        except (ValidationError, IntegrityError) as exc:
            messages.error(
                request,
                '；'.join(exc.messages) if isinstance(exc, ValidationError) else '学工号已被使用。',
            )
    return render(
        request,
        'school/user_detail.html',
        {
            'title': '账号管理',
            'account': user,
            'roles': UserRole.ROLE_CHOICES,
            'assigned_roles': list(user.roles.values_list('role', flat=True)),
        },
    )


@login_required
def users_import(request):
    require_admin(request.user)
    rows = request.session.get('import_preview', [])
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'preview':
                upload = request.FILES.get('file')
                if not upload:
                    raise ValidationError('请选择文件。')
                rows = preview_import(upload)
                request.session['import_preview'] = rows
            elif request.POST.get('action') == 'commit':
                if not rows:
                    raise ValidationError('请先预览导入文件。')
                count = commit_import(request.user, rows, request.POST.get('password', ''))
                del request.session['import_preview']
                messages.success(
                    request, f'导入完成，新建 {count} 个账号，已有相同账号未重复创建。'
                )
                return redirect('users')
        except (ValidationError, IntegrityError) as exc:
            messages.error(
                request,
                '；'.join(exc.messages)
                if isinstance(exc, ValidationError)
                else '数据已变化，请重新预览。',
            )
    return render(
        request,
        'school/import.html',
        {
            'title': '批量导入学生名单',
            'rows': rows,
            'valid': bool(rows) and not any(r['error'] for r in rows),
        },
    )


@login_required
def import_template(request):
    require_admin(request.user)
    response = HttpResponse(
        '\ufeffusername,full_name,student_no,class_code\r\nstudent001,示例学生,2026001,PY2026\r\n',
        content_type='text/csv; charset=utf-8',
    )
    response['Content-Disposition'] = 'attachment; filename="student-import-template.csv"'
    return response


@login_required
def question_view(request, pk):
    question = get_object_or_404(
        AssignmentQuestion.objects.select_related(
            'version__assignment__classroom', 'version__rule', 'problem_version'
        ),
        pk=pk,
    )
    assignment = question.version.assignment
    if not assignment_access(request.user, assignment):
        raise PermissionDenied
    if question.version.status != 'published' and not permitted(
        request.user, assignment.classroom, 'edit'
    ):
        raise PermissionDenied
    form = SubmissionForm(
        request.POST or None,
        request.FILES or None,
        initial={'request_key': uuid.uuid4(), 'code': question.problem_version.template_code},
    )
    if request.method == 'POST' and form.is_valid():
        try:
            sub = accept_submission(
                request.user, pk, form.cleaned_data['code'], form.cleaned_data['request_key']
            )
            return redirect('submission', pk=sub.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    samples = [
        {
            'input': read_private(c.input_path),
            'output': read_private(c.output_path),
            'description': c.description,
        }
        for c in question.problem_version.cases.filter(is_sample=True, hidden=False)
    ]
    used = Submission.objects.filter(
        student=request.user,
        assignment=assignment,
        question_key=question.question_key,
        counted=True,
        extension__isnull=True,
    ).count()
    return render(
        request,
        'school/question.html',
        {
            'title': question.problem_version.title,
            'back_url': reverse('assignment', args=[assignment.pk]),
            'back_label': '返回作业',
            'can_edit': permitted(request.user, assignment.classroom, 'edit'),
            'can_grades': permitted(request.user, assignment.classroom, 'grades'),
            'question': question,
            'problem': question.problem_version,
            'assignment': assignment,
            'samples': samples,
            'form': form,
            'remaining': max(0, question.version.rule.max_attempts - used),
            'can_submit': is_member(request.user, assignment.classroom)
            and not assignment.classroom.archived,
            'history': Submission.objects.filter(
                student=request.user, assignment=assignment, question_key=question.question_key
            )[:10],
        },
    )


def submission_access(user, sub):
    if (
        sub.student_id == user.pk
        or permitted(user, sub.assignment.classroom, 'grades')
        or is_admin(user)
    ):
        return
    raise PermissionDenied


@login_required
def submissions_view(request):
    if not student_workspace(request.user):
        return redirect('dashboard')
    subs = Submission.objects.filter(student=request.user).select_related(
        'question__problem_version', 'assignment__current_version'
    )
    return render(
        request,
        'school/submissions.html',
        {'title': '我的提交', 'submissions': Paginator(subs, 25).get_page(request.GET.get('page'))},
    )


@login_required
def submission_view(request, pk):
    sub = get_object_or_404(
        Submission.objects.select_related('assignment__classroom', 'question__problem_version'),
        pk=pk,
    )
    submission_access(request.user, sub)
    if is_admin(request.user) and sub.student_id != request.user.pk:
        audit(request.user, 'maintenance.submission_read', f'submission:{pk}')
    run = sub.runs.order_by('-execution').first()
    results = run.results.select_related('case') if run else []
    return render(
        request,
        'school/submission.html',
        {
            'title': f'提交 #{pk}',
            'back_url': reverse('grades', args=[sub.assignment_id])
            if permitted(request.user, sub.assignment.classroom, 'grades')
            else reverse('submissions')
            if student_workspace(request.user)
            else reverse('dashboard'),
            'back_label': '返回成绩与提交'
            if permitted(request.user, sub.assignment.classroom, 'grades')
            else '返回我的提交'
            if student_workspace(request.user)
            else '返回工作台',
            'submission': sub,
            'code': read_private(sub.code_path),
            'run': run,
            'results': results,
            'formal_count': run.results.filter(case__is_sample=False).count() if run else 0,
            'passed': run.results.filter(verdict='AC', case__is_sample=False).count() if run else 0,
            'poll': run and run.status in ('pending', 'queued', 'running'),
        },
    )


@login_required
def submission_status(request, pk):
    sub = get_object_or_404(Submission, pk=pk)
    submission_access(request.user, sub)
    run = sub.runs.order_by('-execution').first()
    return JsonResponse(
        {
            'status': run.status,
            'label': run.get_status_display(),
            'verdict': run.verdict,
            'score': str(run.base_score) if run.base_score is not None else None,
        }
    )


@login_required
def my_grades(request):
    if not student_workspace(request.user):
        return redirect('dashboard')
    grades = (
        StudentGrade.objects.filter(
            student=request.user,
            revision__status='published',
            revision__assignment__current_grade_id=F('revision_id'),
        )
        .select_related('revision__version')
        .prefetch_related('questions__question__problem_version')
    )
    return render(request, 'school/my_grades.html', {'title': '我的成绩', 'grades': grades})


@login_required
def extensions_view(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    teaching = permitted(request.user, assignment.classroom, 'grades')
    if not teaching and not is_member(request.user, assignment.classroom):
        raise PermissionDenied
    form = ExtensionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if not is_member(request.user, assignment.classroom) or assignment.classroom.archived:
            raise PermissionDenied
        if assignment.extensions.filter(student=request.user, status='pending').exists():
            form.add_error(None, '已有待处理申请，请勿重复提交。')
        else:
            extension = ExtensionRequest.objects.create(
                student=request.user, assignment=assignment, reason=form.cleaned_data['reason']
            )
            audit(request.user, 'extension.request', f'extension:{extension.pk}')
            messages.success(request, '补交申请已提交。')
            return redirect('extensions', pk=pk)
    extensions = assignment.extensions.select_related('student').order_by('-created_at')
    if not teaching:
        extensions = extensions.filter(student=request.user)
    return render(
        request,
        'school/extensions.html',
        {
            'title': '补交申请',
            'back_url': reverse('assignment', args=[assignment.pk]),
            'back_label': '返回作业',
            'assignment': assignment,
            'form': form,
            'extensions': extensions,
            'teaching': teaching,
        },
    )


@login_required
def announcement_create(request, pk=None):
    classroom = get_object_or_404(Classroom, pk=pk) if pk else None
    if classroom:
        require_staff(request.user, classroom, 'publish')
    else:
        require_admin(request.user)
    form = AnnouncementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        announcement = form.save(commit=False)
        announcement.classroom = classroom
        announcement.author = request.user
        announcement.save()
        audit(request.user, 'announcement.publish', f'announcement:{announcement.pk}')
        return redirect('dashboard')
    return form_page(
        request,
        '发布班级公告' if classroom else '发布平台公告',
        form,
        back_url=reverse('class_detail', args=[pk]) if classroom else reverse('dashboard'),
        back_label='返回教学班' if classroom else '返回工作台',
    )


@login_required
def notifications_view(request):
    if request.method == 'POST':
        request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
        return redirect('notifications')
    return render(
        request,
        'school/notifications.html',
        {'title': '站内通知', 'notifications': request.user.notifications.all()[:100]},
    )


@login_required
def operations(request):
    require_admin(request.user)
    if request.method == 'POST':
        run = get_object_or_404(JudgeRun, pk=request.POST.get('run'))
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=run.submission.student_id)
                run = JudgeRun.objects.select_for_update().get(pk=run.pk)
                if run.status != 'error':
                    raise ValidationError('只能处理系统异常任务。')
                if action == 'retry':
                    new = JudgeRun.objects.create(
                        submission=run.submission,
                        question=run.question,
                        revision=run.revision,
                        execution=(run.submission.runs.aggregate(n=Max('execution'))['n'] or 0) + 1,
                    )
                    run.status = 'superseded'
                    run.save(update_fields=['status'])
                    transaction.on_commit(lambda: dispatch(new.pk))
                elif action == 'refund':
                    if run.revision_id:
                        raise ValidationError('重评任务不占额外提交次数，无需返还。')
                    if run.submission.runs.filter(
                        status__in=['pending', 'queued', 'running', 'done']
                    ).exists():
                        raise ValidationError('提交还有有效评测记录，不能返还。')
                    Submission.objects.filter(pk=run.submission_id, counted=True).update(
                        counted=False
                    )
                    run.status = 'superseded'
                    run.save(update_fields=['status'])
                else:
                    raise ValidationError('无效操作。')
                audit(request.user, 'judge.' + action, f'run:{run.pk}')
            messages.success(request, '异常任务处理完成。')
        except ValidationError as exc:
            messages.error(request, '；'.join(exc.messages))
        return redirect('operations')
    return render(
        request,
        'school/operations.html',
        {
            'title': '运行监控与审计',
            'counts': JudgeRun.objects.values('status').annotate(count=Count('pk')),
            'errors': JudgeRun.objects.filter(status='error').select_related('submission__student')[
                :50
            ],
            'logs': AuditLog.objects.select_related('actor')[:100],
            'judge_image': settings.JUDGE_IMAGE,
        },
    )


def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return JsonResponse({'status': 'ok'})


# Compatibility imports for existing callers; teaching routes have their own module.
from .teaching_views import (
    assignment_access,
    assignment_action,
    assignment_detail,
    assignment_edit,
    assignment_render,
    assignment_version,
    extension_decide,
    grades_export,
    grades_view,
    problem_edit,
    problem_list,
    problem_retry,
    safe_csv,
)
