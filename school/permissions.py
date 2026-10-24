from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone
from .models import Classroom, ClassStaff, ClassStudent


def is_admin(user):
    return user.is_authenticated and user.has_role('admin')


def student_workspace(user):
    return (
        user.is_authenticated
        and user.has_role('student')
        and not (user.has_role('teacher') or user.has_role('assistant') or is_admin(user))
    )


def require_admin(user):
    if not is_admin(user):
        raise PermissionDenied('仅管理员可管理账号、身份及学生名单。')


def staff_for(user, classroom):
    if not user.is_active:
        return None
    return (
        ClassStaff.objects.filter(user=user, classroom=classroom, active=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now()))
        .first()
    )


def permitted(user, classroom, action='view'):
    staff = staff_for(user, classroom)
    if not staff or not user.has_role(staff.role):
        return False
    if classroom.archived and (action not in ('view', 'grades', 'export') or not staff.can_archive):
        return False
    if staff.role == 'teacher':
        return True
    return {
        'view': True,
        'edit': staff.can_edit,
        'grades': staff.can_view_grades,
        'export': staff.can_view_grades and staff.can_export,
        'publish': False,
    }.get(action, False)


def require_staff(user, classroom, action='view'):
    if not permitted(user, classroom, action):
        raise PermissionDenied('你没有此教学班的相应权限，或授权已到期。')


def is_member(user, classroom):
    return (
        user.is_active
        and user.has_role('student')
        and ClassStudent.objects.filter(student=user, classroom=classroom, active=True).exists()
    )


def visible_classes(user):
    if is_admin(user):
        return Classroom.objects.all()
    ids = (
        set(
            ClassStudent.objects.filter(student=user, active=True).values_list(
                'classroom_id', flat=True
            )
        )
        if user.has_role('student')
        else set()
    )
    for c in Classroom.objects.filter(staff__user=user).distinct():
        if permitted(user, c):
            ids.add(c.pk)
    return Classroom.objects.filter(pk__in=ids)
