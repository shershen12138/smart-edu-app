from django.test import TestCase, override_settings
from django.urls import reverse

from school.models import Classroom, ClassStudent, User, UserRole

from . import test_portal


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class RosterScopeTests(TestCase):
    setUp = test_portal.PortalTests.setUp
    create_work = test_portal.PortalTests.create_work
    get_as = test_portal.PortalTests.get_as

    def extra_student(self, username):
        user = User.objects.create_user(username=username, student_no=username)
        UserRole.objects.create(user=user, role='student')
        return user

    def test_unassigned_account_adds_to_admin_total_but_not_class_rosters(self):
        for i in range(91):
            student = self.extra_student(f'roster_{i:03}')
            ClassStudent.objects.create(classroom=self.classroom, student=student)
        self.extra_student('unassigned')
        all_students = self.get_as(self.admin, reverse('students'))
        self.assertEqual(all_students.context['page'].paginator.count, 93)
        filtered = self.get_as(
            self.admin, reverse('students') + f'?classroom={self.classroom.pk}'
        )
        self.assertEqual(filtered.context['page'].paginator.count, 92)
        self.assertNotContains(filtered, '<td>unassigned</td>', html=True)
        for user in [self.admin, self.teacher]:
            response = self.get_as(user, reverse('class_detail', args=[self.classroom.pk]))
            self.assertEqual(response.context['page'].paginator.count, 92)

    def test_student_management_explains_scope_and_shows_class_membership(self):
        self.extra_student('unassigned')
        response = self.get_as(self.admin, reverse('students'))
        self.assertContains(response, '全部学生账号（含未分班）')
        self.assertContains(response, '<th>所属教学班</th>', html=True)
        self.assertContains(response, '<td>未分班</td>', html=True)
        self.assertContains(response, str(self.classroom))
        filtered = self.get_as(
            self.admin, reverse('students') + f'?classroom={self.classroom.pk}'
        )
        self.assertContains(filtered, '与该班教师名单使用相同人数口径')

    def test_other_classes_archives_and_suspended_accounts_keep_consistent_counts(self):
        other = Classroom.objects.create(code='OTHER', name='其他班', term='2026')
        archived = Classroom.objects.create(code='OLD', name='归档班', term='2025', archived=True)
        other_student = self.extra_student('other_student')
        archived_student = self.extra_student('archived_student')
        ClassStudent.objects.create(classroom=other, student=other_student)
        ClassStudent.objects.create(classroom=archived, student=archived_student)
        ClassStudent.objects.create(classroom=other, student=self.student)
        self.student.is_active = False
        self.student.save(update_fields=['is_active'])
        ClassStudent.objects.create(classroom=self.classroom, student=self.teacher)
        response = self.get_as(self.admin, reverse('students'))
        self.assertEqual(response.context['page'].paginator.count, 2)
        self.assertNotContains(response, 'archived_student')
        self.assertNotContains(response, str(archived))
        for user in [self.admin, self.teacher]:
            response = self.get_as(user, reverse('class_detail', args=[self.classroom.pk]))
            self.assertEqual(response.context['page'].paginator.count, 1)
