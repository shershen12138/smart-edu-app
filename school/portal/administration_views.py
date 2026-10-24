import csv
import io

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from school.imports import HEADERS, commit_import, preview_import
from school.models import (
    Classroom,
    ClassStaff,
    ClassStudent,
    DataDictionary,
    DictionaryItem,
    User,
)
from school.services import audit, set_membership

from . import admin_forms as forms
from .access import classes_for, require_role, role
from .account_services import save_person
from .common_views import csv_response, form_page, link, page, table
from .rosters import students_in, visible_students, with_student_counts


@login_required
def people(request, kind):
    require_role(request.user, 'admin')
    qs = (
        visible_students()
        if kind == 'student'
        else User.objects.filter(roles__role=kind, deleted_at__isnull=True)
    ).order_by('username', 'pk')
    query = request.GET.get('q', '').strip()
    if query:
        qs = qs.filter(
            Q(username__icontains=query)
            | Q(full_name__icontains=query)
            | Q(student_no__icontains=query)
        )
    selected_class = request.GET.get('classroom', '')
    classroom = None
    if selected_class.isdigit() and kind == 'student':
        classroom = get_object_or_404(classes_for(request.user), pk=int(selected_class))
        qs = qs.filter(pk__in=students_in(classroom).values('pk'))
    if kind == 'student':
        qs = qs.prefetch_related(
            Prefetch(
                'memberships',
                queryset=ClassStudent.objects.filter(
                    active=True,
                    classroom__archived=False,
                    classroom__deleted_at__isnull=True,
                ).select_related('classroom').order_by('classroom__code', 'classroom_id'),
                to_attr='visible_memberships',
            )
        )

    def person_row(user):
        actions = [
            link('编辑 / 重置密码', 'person_edit', kind, user.pk),
            link('删除', 'person_delete', kind, user.pk),
        ]
        if kind == 'teacher':
            actions.insert(0, link('班级与权限', 'teacher_grants', user.pk))
        cells = [user.username, user.full_name, user.student_no]
        if kind == 'student':
            cells.append('；'.join(str(m.classroom) for m in user.visible_memberships) or '未分班')
        cells.append('可登录' if user.is_active else '已停用')
        return {
            'pk': user.pk,
            'cells': cells,
            'actions': actions,
        }

    extras = (
        [link('批量导入', 'students_import'), link('下载导入模板', 'students_template')]
        if kind == 'student'
        else []
    )
    description = '按当前筛选条件统计人数。'
    if kind == 'student':
        description = (
            f'当前范围：{classroom}，与该班教师名单使用相同人数口径。'
            if classroom
            else '当前范围：全平台学生账号（含未分班），不等于某一个班级的在班人数。请选择具体教学班核对人数。'
        )
        description += '停用账号仍保留在班关系，移出班级后才不计入在班人数。'
    return table(
        request,
        '教师用户管理' if kind == 'teacher' else '教学班名单管理',
        ['登录名', '姓名', '学号 / 工号']
        + (['所属教学班'] if kind == 'student' else [])
        + ['账号状态'],
        qs.distinct(),
        row_builder=person_row,
        count_unit='人',
        description=description,
        create=link('新建教师' if kind == 'teacher' else '新建学生', 'person_new', kind),
        extras=extras,
        search=True,
        batch=kind == 'student',
        classrooms=classes_for(request.user),
        selected_class=selected_class,
        class_filter_all_label='全部学生账号（含未分班）' if kind == 'student' else '全部教学班',
    )


def managed_person(kind, pk):
    if kind not in ('teacher', 'student'):
        raise PermissionDenied
    queryset = (
        visible_students()
        if kind == 'student'
        else User.objects.filter(roles__role=kind, deleted_at__isnull=True)
    )
    return get_object_or_404(queryset, pk=pk)


@login_required
def person_edit(request, kind, pk=None):
    require_role(request.user, 'admin')
    if kind not in ('teacher', 'student'):
        raise PermissionDenied
    user = managed_person(kind, pk) if pk else None
    form = forms.PersonForm(request.POST or None, instance=user, kind=kind)
    back = reverse('teachers' if kind == 'teacher' else 'students')
    if request.method == 'POST' and form.is_valid():
        try:
            save_person(request.user, form, kind)
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None, exc if isinstance(exc, ValidationError) else '账号或学工号重复，请检查。'
            )
        else:
            messages.success(
                request, '账号已保存。临时密码由管理员直接交给本人，首次登录需修改，无需邮箱。'
            )
            return redirect(back)
    response = form_page(
        request,
        ('编辑' if pk else '新建') + ('教师账号' if kind == 'teacher' else '学生账号'),
        form,
        back,
        recovery_password=user.recovery_password
        if user and settings.STORE_RECOVERY_PASSWORDS
        else '',
        recovery_available=bool(user and settings.STORE_RECOVERY_PASSWORDS),
    )
    response['Cache-Control'] = 'no-store'
    return response


@login_required
def person_delete(request, kind, pk):
    require_role(request.user, 'admin')
    user = managed_person(kind, pk)
    if user.pk == request.user.pk or user.is_superuser or user.roles.exclude(role=kind).exists():
        raise PermissionDenied
    back = reverse('teachers' if kind == 'teacher' else 'students')
    if request.method == 'POST':
        with transaction.atomic():
            audit(request.user, 'portal.account.delete', str(user.pk))
            user.delete()
        messages.success(request, '账号及其学生提交、成绩和文件已永久删除。')
        return redirect(back)
    return page(
        request,
        'confirm',
        '删除账号',
        object=user,
        back_url=back,
        description='永久删除账号及其学生提交、成绩、文件和班级关系，无法恢复；教师已布置的作业仍归教学班所有。',
    )


@login_required
def teacher_grants(request, pk):
    require_role(request.user, 'admin')
    user = managed_person('teacher', pk)
    form = forms.GrantForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        classroom = form.cleaned_data['classroom']
        if ClassStudent.objects.filter(classroom=classroom, student=user, active=True).exists():
            form.add_error(None, '同一账号不能同时是本班教师和学生。')
        else:
            ClassStaff.objects.update_or_create(
                classroom=classroom,
                user=user,
                defaults={
                    **{
                        k: form.cleaned_data[k]
                        for k in ('can_edit', 'can_view_grades', 'can_export', 'active')
                    },
                    'role': 'teacher',
                    'expires_at': None,
                },
            )
            audit(request.user, 'portal.grant.save', str(user.pk), {'classroom': classroom.pk})
            messages.success(request, '本班授权已覆盖保存，权限立即生效。')
            return redirect('teacher_grants', pk=pk)
    return form_page(
        request,
        f'{user.full_name} · 用户授权',
        form,
        reverse('teachers'),
        grants=user.teaching.filter(
            classroom__deleted_at__isnull=True, classroom__archived=False
        ).select_related('classroom'),
        description='选择教学班并勾选权限；再次选择同一班级将覆盖原授权。取消启用即可撤销本班访问。',
    )


@login_required
@require_POST
def students_batch(request):
    require_role(request.user, 'admin')
    ids = request.POST.getlist('selected')
    if not ids or len(ids) > 500 or not all(v.isdigit() for v in ids):
        messages.error(request, '请勾选 1～500 名学生。')
        return redirect('students')
    users = (
        visible_students()
        .filter(pk__in=ids)
        .exclude(is_superuser=True)
        .exclude(roles__role__in=['admin', 'teacher'])
    )
    action = request.POST.get('action')
    with transaction.atomic():
        if action in ('activate', 'deactivate'):
            users.update(is_active=action == 'activate')
        elif action == 'delete':
            users.delete()
        elif action in ('add_class', 'remove_class'):
            if not request.POST.get('classroom', '').isdigit():
                messages.error(request, '请先选择目标教学班。')
                return redirect('students')
            classroom = get_object_or_404(
                Classroom,
                pk=request.POST.get('classroom') or 0,
                deleted_at__isnull=True,
                archived=False,
            )
            for user in users:
                if action == 'add_class':
                    set_membership(request.user, classroom, user)
                else:
                    user.memberships.filter(classroom=classroom).update(
                        active=False, left_at=timezone.now()
                    )
        else:
            raise PermissionDenied
        audit(request.user, 'portal.students.batch', 'students', {'action': action, 'ids': ids})
    messages.success(request, '所选学生已批量更新。')
    return redirect('students')


@login_required
def students_import(request):
    require_role(request.user, 'admin')
    error = ''
    if request.method == 'POST':
        try:
            if request.POST.get('confirm') == 'yes':
                rows = request.session.get('portal_import')
                if not rows:
                    raise ValidationError('导入预览已失效，请重新上传。')
                created = commit_import(
                    request.user,
                    rows,
                    request.POST.get('password') or '123456',
                    allow_default_password=True,
                )
                request.session.pop('portal_import', None)
                messages.success(
                    request,
                    f'导入完成：处理 {len(rows)} 条名单，新增账号 {created} 个，已有账号 {len(rows) - created} 个。新账号首次登录需修改密码。',
                )
                codes = {row['class_code'] for row in rows}
                if len(codes) == 1:
                    classroom = Classroom.objects.get(code=codes.pop())
                    return redirect(reverse('students') + f'?classroom={classroom.pk}')
                return redirect('students')
            upload = request.FILES.get('file')
            if not upload:
                raise ValidationError('请选择导入文件。')
            request.session['portal_import'] = preview_import(upload)
        except (ValidationError, IntegrityError, Classroom.DoesNotExist) as exc:
            error = (
                '；'.join(exc.messages)
                if isinstance(exc, ValidationError)
                else '名单或班级状态已变化，请重新预览。'
            )
    rows = request.session.get('portal_import', [])
    return page(
        request,
        'import',
        '批量导入学生名单',
        rows=rows,
        ready=bool(rows) and not any(r['error'] for r in rows),
        error=error,
        back_url=reverse('students'),
    )


@login_required
def students_template(request):
    require_role(request.user, 'admin')
    output = io.StringIO()
    csv.writer(output).writerow(HEADERS)
    return csv_response(output.getvalue(), 'students-template.csv')


@login_required
def classes(request):
    rows = [
        {
            'cells': [c.code, c.name, c.course_name, c.term, c.student_count],
            'actions': [link('班级名单', 'class_detail', c.pk)]
            + (
                [link('编辑', 'class_edit', c.pk), link('删除', 'class_delete', c.pk)]
                if role(request.user) == 'admin'
                else []
            ),
        }
        for c in with_student_counts(classes_for(request.user)).order_by('code', 'pk')
    ]
    return table(
        request,
        '教学班管理' if role(request.user) == 'admin' else '班级清单',
        ['班级编号', '教学班', '课程', '学期', '在班人数'],
        rows,
        create=link('新建教学班', 'class_new') if role(request.user) == 'admin' else None,
    )


@login_required
def class_edit(request, pk=None):
    require_role(request.user, 'admin')
    classroom = (
        get_object_or_404(Classroom, pk=pk, deleted_at__isnull=True, archived=False) if pk else None
    )
    form = forms.ClassForm(request.POST or None, instance=classroom)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        audit(request.user, 'portal.class.save', str(saved.pk))
        return redirect('classes')
    return form_page(request, '编辑教学班' if pk else '新建教学班', form, reverse('classes'))


@login_required
def class_delete(request, pk):
    require_role(request.user, 'admin')
    classroom = get_object_or_404(Classroom, pk=pk, deleted_at__isnull=True, archived=False)
    if request.method == 'POST':
        with transaction.atomic():
            classroom.delete()
            audit(request.user, 'portal.class.delete', str(pk))
        messages.success(
            request, '教学班、班级关系、作业、提交、成绩及对应文件已永久删除。学生和教师账号保留。'
        )
        return redirect('classes')
    return page(
        request,
        'confirm',
        '删除教学班',
        object=classroom,
        back_url=reverse('classes'),
        description='永久删除该班、班级关系、全部作业、提交、成绩及相关文件，无法恢复。学生和教师账号及其他班级数据保留；仅想隐藏请使用归档管理。',
    )


@login_required
def class_detail(request, pk):
    classroom = get_object_or_404(classes_for(request.user, 'view_grades'), pk=pk)
    admin = role(request.user) == 'admin'
    return table(
        request,
        str(classroom) + ' · 班级名单',
        ['学号', '姓名', '登录名'],
        students_in(classroom),
        count_unit='人',
        row_builder=lambda user: {
            'cells': [user.student_no, user.full_name, user.username],
            'actions': [link('编辑账号', 'person_edit', 'student', user.pk)]
            if admin
            else [link('查看学生结果', 'student_results', pk, user.pk)],
        },
        back_url=reverse('classes'),
        extras=[{'label': '维护本班名单', 'url': reverse('students') + f'?classroom={pk}'}]
        if admin
        else [{'label': '本班作业', 'url': reverse('works') + f'?classroom={pk}'}],
    )


@login_required
def archives(request):
    require_role(request.user, 'admin')
    if request.method == 'POST':
        identifier = request.POST.get('classroom', '')
        if not identifier.isdigit():
            messages.error(request, '请选择有效的教学班。')
            return redirect('archives')
        with transaction.atomic():
            classroom = get_object_or_404(
                Classroom.objects.select_for_update(), pk=int(identifier), deleted_at__isnull=True
            )
            classroom.archived = request.POST.get('archived') == 'on'
            classroom.save(update_fields=['archived'])
            audit(
                request.user,
                'portal.class.archive' if classroom.archived else 'portal.class.restore',
                str(classroom.pk),
            )
        messages.success(
            request,
            '已归档：所有角色的日常页面和旧链接均不可访问本班内容。'
            if classroom.archived
            else '已取消归档，可以在教学班管理中查看和修改。',
        )
        return redirect('archives')
    from .pagination import pagination

    qs = Classroom.objects.filter(deleted_at__isnull=True).order_by('code', 'pk')
    query = request.GET.get('q', '').strip()
    if query:
        qs = qs.filter(
            Q(code__icontains=query) | Q(name__icontains=query) | Q(term__icontains=query)
        )
    return page(request, 'archives', '归档管理', **pagination(request, qs))


@login_required
def dictionaries(request):
    require_role(request.user, 'admin')
    return table(
        request,
        '基本数据字典配置',
        ['代码', '名称', '状态', '说明'],
        [
            {
                'cells': [d.code, d.name, '启用' if d.active else '停用', d.description],
                'actions': [
                    link('字典项', 'dictionary_items', d.pk),
                    link('编辑', 'dictionary_edit', d.pk),
                    link('删除', 'dictionary_delete', d.pk),
                ],
            }
            for d in DataDictionary.objects.all().order_by('code')
        ],
        create=link('新建字典', 'dictionary_new'),
    )


@login_required
def dictionary_edit(request, pk=None):
    require_role(request.user, 'admin')
    instance = get_object_or_404(DataDictionary, pk=pk) if pk else None
    form = forms.DictionaryForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        audit(request.user, 'portal.dictionary.save', str(saved.pk))
        return redirect('dictionaries')
    return form_page(
        request,
        '编辑字典' if pk else '新建字典',
        form,
        reverse('dictionaries'),
        description='course、term 分别用于教学班的课程与学期选项；可以添加其他基础字典备用。',
    )


def dictionary_in_use(dictionary, values):
    field = {'course': 'course_name', 'term': 'term'}.get(dictionary.code)
    return (
        field
        and Classroom.objects.filter(**{field + '__in': values}, deleted_at__isnull=True).exists()
    )


@login_required
def dictionary_delete(request, pk, item_id=None):
    require_role(request.user, 'admin')
    dictionary = get_object_or_404(DataDictionary, pk=pk)
    target = (
        get_object_or_404(DictionaryItem, pk=item_id, dictionary=dictionary)
        if item_id
        else dictionary
    )
    back = reverse('dictionary_items', args=[pk]) if item_id else reverse('dictionaries')
    if request.method == 'POST':
        values = [target.value] if item_id else dictionary.items.values_list('value', flat=True)
        if dictionary_in_use(dictionary, values):
            messages.error(request, '字典值正在被教学班使用，不能删除；可以编辑为停用。')
        else:
            audit(request.user, 'portal.dictionary.delete', str(target.pk), {'item': bool(item_id)})
            target.delete()
        return redirect(back)
    return page(
        request,
        'confirm',
        '删除字典项' if item_id else '删除字典',
        object=target.label if item_id else dictionary.name,
        description='删除字典时会同时删除其全部字典项；使用中的数据不能删除。',
        back_url=back,
    )


@login_required
def dictionary_items(request, pk):
    require_role(request.user, 'admin')
    dictionary = get_object_or_404(DataDictionary, pk=pk)
    return table(
        request,
        dictionary.name + ' · 字典项',
        ['代码', '显示名称', '排序', '状态'],
        [
            {
                'cells': [i.value, i.label, i.order, '启用' if i.active else '停用'],
                'actions': [
                    link('编辑', 'dictionary_item_edit', pk, i.pk),
                    link('删除', 'dictionary_item_delete', pk, i.pk),
                ],
            }
            for i in dictionary.items.all()
        ],
        create=link('新建字典项', 'dictionary_item_new', pk),
        back_url=reverse('dictionaries'),
    )


@login_required
def dictionary_item_edit(request, pk, item_id=None):
    require_role(request.user, 'admin')
    dictionary = get_object_or_404(DataDictionary, pk=pk)
    instance = (
        get_object_or_404(DictionaryItem, pk=item_id, dictionary=dictionary)
        if item_id
        else DictionaryItem(dictionary=dictionary)
    )
    old_value = instance.value
    form = forms.DictionaryItemForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        if old_value != form.cleaned_data['value'] and dictionary_in_use(dictionary, [old_value]):
            form.add_error('value', '该代码正在使用，请新增字典项后停用旧项。')
        elif dictionary.items.filter(value=form.cleaned_data['value']).exclude(pk=item_id).exists():
            form.add_error('value', '本字典内的项目代码不能重复。')
        else:
            saved = form.save()
            audit(request.user, 'portal.dictionary.item.save', str(saved.pk))
            return redirect('dictionary_items', pk=pk)
    return form_page(
        request,
        '编辑字典项' if item_id else '新建字典项',
        form,
        reverse('dictionary_items', args=[pk]),
    )
