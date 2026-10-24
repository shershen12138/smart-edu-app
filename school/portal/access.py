from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from school.models import Classroom


def role(user):
    if not user.is_authenticated or not user.is_active:
        return ''
    for value in ('admin', 'teacher', 'student'):
        if user.has_role(value):
            return value
    return ''


def require_role(user, expected):
    if role(user) != expected:
        raise PermissionDenied


def classes_for(user, action=None):
    qs = Classroom.objects.filter(deleted_at__isnull=True, archived=False)
    current = role(user)
    if current == 'admin':
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
