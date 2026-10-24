from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from school.models import Coursework, DataDictionary, User

from .access import allowed, classes_for, role
from .pagination import pagination
from .reporting_services import roster_rows
from .rosters import visible_students


def page(request, template, title, **context):
    return render(request, 'portal/' + template + '.html', {'title': title, **context})


def form_page(request, title, form, back_url, **context):
    return page(request, 'form', title, form=form, back_url=back_url, **context)


def table(request, title, headers, rows, row_builder=None, **context):
    pages = pagination(request, rows)
    if row_builder:
        pages['page'].object_list = [row_builder(row) for row in pages['page'].object_list]
    return page(
        request,
        'table',
        title,
        headers=headers,
        **pages,
        **context,
    )


def link(label, name, *args):
    return {'label': str(label), 'url': reverse(name, args=args)}


def work_for(user, pk, action=None):
    work = get_object_or_404(
        Coursework.objects.select_related('classroom', 'package').prefetch_related('items'),
        pk=pk,
        deleted_at__isnull=True,
        classroom__archived=False,
        classroom__deleted_at__isnull=True,
    )
    if role(user) == 'student':
        if (
            action
            or work.status != 'open'
            or not classes_for(user).filter(pk=work.classroom_id).exists()
        ):
            raise PermissionDenied
    elif not allowed(user, work.classroom, action or 'view_grades') and (
        action or not allowed(user, work.classroom, 'edit')
    ):
        raise PermissionDenied
    return work


def private_download(key, filename):
    path = (settings.PRIVATE_STORAGE / key).resolve()
    if not key or not path.is_relative_to(settings.PRIVATE_STORAGE.resolve()) or not path.is_file():
        from django.http import Http404

        raise Http404
    response = FileResponse(path.open('rb'), as_attachment=True, filename=filename)
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def safe_csv(value):
    value = str(value) if value is not None else ''
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value


def csv_response(content, filename):
    response = HttpResponse('\ufeff' + content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def profile(request):
    return page(request, 'profile', '个人中心', back_url=reverse('dashboard'))


@login_required
def dashboard(request):
    current = role(request.user)
    if current == 'admin':
        stats = [
            (
                '教师账号',
                User.objects.filter(roles__role='teacher', deleted_at__isnull=True).count(),
            ),
            (
                '学生账号（含未分班）',
                visible_students().count(),
            ),
            ('教学班', classes_for(request.user).count()),
            ('数据字典', DataDictionary.objects.count()),
        ]
        return page(
            request,
            'dashboard',
            '管理工作台',
            stats=stats,
            shortcuts=[
                link('教师用户与授权', 'teachers'),
                link('教学班管理', 'classes'),
                link('教学班名单管理', 'students'),
                link('数据字典配置', 'dictionaries'),
                link('归档管理', 'archives'),
            ],
        )
    if current not in ('teacher', 'student'):
        return page(
            request,
            'dashboard',
            '账号待授权',
            description='当前版本仅开放管理员、教师和学生。请联系管理员分配所需身份。',
        )
    works = (
        Coursework.objects.filter(classroom__in=classes_for(request.user), deleted_at__isnull=True)
        .select_related('classroom', 'package')
        .prefetch_related('items')
    )
    if current == 'student':
        works = works.filter(status='open')
        student_classrooms = list(classes_for(request.user))
        all_cards = []
        for work in works:
            entry = work.entries.filter(student=request.user).first()
            all_cards.append(
                {'work': work, 'entry': entry, 'expired': work.deadline < timezone.now()}
            )
        selected_filter = request.GET.get('filter', 'all')
        if selected_filter == 'submitted':
            cards = [card for card in all_cards if card['entry']]
            card_filter_label = '已提交作业'
        elif selected_filter == 'pending':
            cards = [card for card in all_cards if not card['entry'] and not card['expired']]
            card_filter_label = '未截止且未提交的作业'
        elif selected_filter == 'classrooms':
            cards = all_cards
            card_filter_label = '我的教学班'
        else:
            selected_filter = 'all'
            cards = all_cards
            card_filter_label = '全部作业'
        classroom_cards = [
            {
                'classroom': classroom,
                'work_count': sum(card['work'].classroom_id == classroom.pk for card in all_cards),
            }
            for classroom in student_classrooms
        ]
        displayed_cards = classroom_cards if selected_filter == 'classrooms' else cards
        dashboard_url = reverse('dashboard')
        return page(
            request,
            'board',
            '作业看板',
            cards=cards,
            card_page=Paginator(displayed_cards, 6).get_page(request.GET.get('page')),
            selected_filter=selected_filter,
            card_filter_label=card_filter_label,
            stats=[
                {
                    'label': '我的教学班',
                    'value': len(student_classrooms),
                    'url': f'{dashboard_url}?filter=classrooms#assignments',
                    'active': selected_filter == 'classrooms',
                },
                {
                    'label': '作业总数',
                    'value': len(all_cards),
                    'url': f'{dashboard_url}?filter=all#assignments',
                    'active': selected_filter == 'all',
                },
                {
                    'label': '已提交',
                    'value': sum(bool(c['entry']) for c in all_cards),
                    'url': f'{dashboard_url}?filter=submitted#assignments',
                    'active': selected_filter == 'submitted',
                },
                {
                    'label': '未截止且未提交',
                    'value': sum(not c['entry'] and not c['expired'] for c in all_cards),
                    'url': f'{dashboard_url}?filter=pending#assignments',
                    'active': selected_filter == 'pending',
                },
            ],
        )
    teacher_classrooms = list(classes_for(request.user))
    result_works = works.filter(classroom__in=classes_for(request.user, 'view_grades')).annotate(
        pending_count=Count(
            'entries',
            filter=Q(entries__status__in=['pending', 'queued', 'running', 'review']),
        ),
        error_count=Count('entries', filter=Q(entries__status='error')),
    )
    all_summaries = []
    for work in result_works:
        _rows, stats = roster_rows(work)
        all_summaries.append(
            {
                'work': work,
                'stats': stats,
                'pending_count': work.pending_count,
                'error_count': work.error_count,
            }
        )
    selected_filter = request.GET.get('filter', 'all')
    if selected_filter == 'pending':
        summaries = [item for item in all_summaries if item['pending_count']]
        teacher_filter_label = '有待批阅提交的作业'
    elif selected_filter == 'errors':
        summaries = [item for item in all_summaries if item['error_count']]
        teacher_filter_label = '批阅服务异常的作业'
    elif selected_filter == 'classrooms':
        summaries = all_summaries
        teacher_filter_label = '我的教学班'
    else:
        selected_filter = 'all'
        summaries = all_summaries
        teacher_filter_label = '全部作业进度'
    classroom_cards = [
        {
            'classroom': classroom,
            'work_count': sum(item['work'].classroom_id == classroom.pk for item in all_summaries),
        }
        for classroom in teacher_classrooms
    ]
    displayed_cards = classroom_cards if selected_filter == 'classrooms' else summaries
    dashboard_url = reverse('dashboard')
    return page(
        request,
        'dashboard',
        '教学仪表盘',
        summaries=summaries,
        card_page=Paginator(displayed_cards, 6).get_page(request.GET.get('page')),
        selected_filter=selected_filter,
        teacher_filter_label=teacher_filter_label,
        stats=[
            {
                'label': '教学班',
                'value': len(teacher_classrooms),
                'url': f'{dashboard_url}?filter=classrooms#assignments',
                'active': selected_filter == 'classrooms',
            },
            {
                'label': '已布置作业',
                'value': len(all_summaries),
                'url': f'{dashboard_url}?filter=all#assignments',
                'active': selected_filter == 'all',
            },
            {
                'label': '待批阅提交',
                'value': sum(item['pending_count'] for item in all_summaries),
                'url': f'{dashboard_url}?filter=pending#assignments',
                'active': selected_filter == 'pending',
            },
            {
                'label': '批阅服务异常',
                'value': sum(item['error_count'] for item in all_summaries),
                'url': f'{dashboard_url}?filter=errors#assignments',
                'active': selected_filter == 'errors',
            },
        ],
        shortcuts=[link('上传题目文件', 'work_new'), link('班级清单与报表', 'results')],
    )
