from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from school.models import UserRole
from school.services import audit, set_membership

from .access import role


@transaction.atomic
def save_person(actor, form, kind):
    if role(actor) != 'admin':
        raise PermissionDenied
    user = form.save(commit=False)
    if user.pk and (user.is_superuser or user.roles.exclude(role=kind).exists()):
        raise ValidationError('该账号含有其他身份，请使用独立的教师或学生账号。')
    if form.cleaned_data['password'] or not user.pk:
        user.set_password(form.cleaned_data['password'] or '123456')
        user.must_change_password = True
    user.save()
    UserRole.objects.get_or_create(user=user, role=kind, defaults={'granted_by': actor})
    if kind == 'student':
        selected = form.cleaned_data['classrooms']
        user.memberships.exclude(classroom__in=selected).filter(
            active=True, classroom__archived=False
        ).update(active=False, left_at=timezone.now())
        for classroom in selected:
            set_membership(actor, classroom, user)
    audit(actor, 'portal.account.save', str(user.pk), {'role': kind})
    return user
