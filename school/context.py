from django.conf import settings

from .permissions import is_admin, student_workspace
from .portal.access import role


def common(request):
    user = request.user
    return {
        'shell_template': 'school/base.html'
        if getattr(request, 'urlconf', settings.ROOT_URLCONF) == 'config.legacy_urls'
        else 'portal/base.html',
        'portal_role': role(user),
        'administrator': is_admin(user),
        'student_workspace': student_workspace(user),
        'unread_count': user.notifications.filter(read_at__isnull=True).count()
        if user.is_authenticated
        else 0,
        'role_labels': ' / '.join(user.roles.values_list('role', flat=True))
        if user.is_authenticated
        else '',
    }
