from django.db.models import Count, Q

from school.models import User


def students_in(classroom):
    """One row per current member; account suspension does not mean leaving a class."""
    return (
        User.objects.filter(
            roles__role='student',
            deleted_at__isnull=True,
            memberships__classroom=classroom,
            memberships__active=True,
        )
        .distinct()
        .order_by('student_no', 'username', 'pk')
    )


def with_student_counts(classrooms):
    return classrooms.annotate(
        student_count=Count(
            'members__student',
            distinct=True,
            filter=Q(
                members__active=True,
                members__student__deleted_at__isnull=True,
                members__student__roles__role='student',
            ),
        )
    )


def visible_students():
    """Hide accounts belonging only to archived classes from the everyday roster."""
    students = User.objects.filter(roles__role='student', deleted_at__isnull=True)
    active = students.filter(
        memberships__active=True,
        memberships__classroom__archived=False,
        memberships__classroom__deleted_at__isnull=True,
    )
    archived = students.filter(memberships__active=True, memberships__classroom__archived=True)
    return students.exclude(pk__in=archived.exclude(pk__in=active).values('pk')).distinct()
