from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from school.models import Classroom


def role(user):
    """返回主角色；三员按“系统 > 安全 > 审计”排序，避免权限叠加造成混权。"""
    if not user.is_authenticated or not user.is_active:
        return ''
    for value in ('admin', 'security_admin', 'audit_admin', 'teacher', 'student'):
        if user.has_role(value):
            return value
    return ''


def require_role(user, expected):
    """expected 可以是单个角色或角色元组，便于让管理员页面同时授权安全管理员。"""
    allowed = (expected,) if isinstance(expected, str) else tuple(expected)
    if role(user) not in allowed:
        raise PermissionDenied


def classes_for(user, action=None):
    qs = Classroom.objects.filter(deleted_at__isnull=True, archived=False)
    current = role(user)
    if current in ('admin', 'security_admin'):
        return qs
    if current == 'student':
        return (
            qs.filter(members__student=user, members__active=True) if action is None else qs.none()
        )
    if current == 'teacher':
        conditions = Q(staff__user=user, staff__role='teacher', staff__active=True)
        conditions &= Q(staff__expires_at__isnull=True) | Q(staff__expires_at__gt=timezone.now())
        if action:
            conditions &= Q(**{'staff__can_' + action: True})
        return qs.filter(conditions).distinct()
    return qs.none()


def allowed(user, classroom, action):
    return (
        role(user) in ('admin', 'teacher')
        and classes_for(user, action).filter(pk=classroom.pk).exists()
    )
