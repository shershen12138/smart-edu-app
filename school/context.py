from django.conf import settings

from .permissions import is_admin, student_workspace
from .portal import llm_client
from .portal.access import role


def common(request):
    user = request.user
    llm_config = llm_client.get_config(user) if user.is_authenticated else None
    return {
        'shell_template': 'school/base.html'
        if getattr(request, 'urlconf', settings.ROOT_URLCONF) == 'config.legacy_urls'
        else 'portal/base.html',
        'portal_role': role(user),
        'administrator': is_admin(user),
        'student_workspace': student_workspace(user),
        # 大模型配置弹窗：服务商预设 + 当前账号已有配置（Key 只回显打码值）
        'llm_providers': llm_client.PROVIDERS,
        'llm_current': llm_config,
        'llm_current_masked': llm_client.mask_key(llm_config.api_key) if llm_config else '',
        'unread_count': user.notifications.filter(read_at__isnull=True).count()
        if user.is_authenticated
        else 0,
        'role_labels': ' / '.join(user.roles.values_list('role', flat=True))
        if user.is_authenticated
        else '',
    }
