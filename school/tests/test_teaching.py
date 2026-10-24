from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from school.forms import ProblemForm
from school.judge import verify_reference
from school.models import ClassStaff, ProblemVersion, UserRole
from school.services import make_revision, publish_assignment, publish_grades
from school.teaching import edit_token, save_assignment

from . import test_workflows as workflows


@override_settings(
    ROOT_URLCONF='config.legacy_urls',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class TeachingTests(TestCase):
    setUp = workflows.WorkflowTests.setUp
    submit = workflows.WorkflowTests.submit
    finish = workflows.WorkflowTests.finish

    def assignment_data(self, version=None, **changes):
        version = version or self.a.versions.order_by('-number').first()
        data = {
            'title': '更新后的作业',
            'description': '新说明',
            'opens_at': self.rule.opens_at,
            'deadline': self.rule.deadline,
            'late_deadline': self.rule.late_deadline,
            'max_attempts': 30,
            'selection': 'best',
            'late_penalty': Decimal('0.1'),
            'problems': [self.p],
            'points': Decimal(100),
            'edit_token': edit_token(version),
        }
        data.update(changes)
        return data

    def problem_data(self, **changes):
        data = {field: getattr(self.p, field) for field in ProblemForm._meta.fields}
        data.update(changes)
        return data

    def test_teachers_and_assistants_only_see_teaching_navigation(self):
        for actor in (self.teacher, self.assistant, self.admin):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                page = self.client.get('/')
                self.assertNotContains(page, '我的提交')
                self.assertNotContains(page, '我的成绩')
                self.assertNotContains(page, '继续今天的编程练习')
                for url in ('submissions', 'my_grades'):
                    self.assertRedirects(self.client.get(reverse(url)), '/')
        self.client.force_login(self.student)
        page = self.client.get('/')
        self.assertContains(page, '我的提交')
        self.assertContains(page, '我的成绩')

    def test_switching_to_student_identity_restores_student_navigation(self):
        UserRole.objects.create(user=self.teacher, role='student')
        self.client.force_login(self.teacher)
        self.assertNotContains(self.client.get('/'), '我的提交')
        session = self.client.session
        session['active_role'] = 'student'
        session.save()
        self.assertContains(self.client.get('/'), '我的提交')

    def test_staff_question_preview_does_not_show_student_controls(self):
        for actor in (self.teacher, self.assistant):
            self.client.force_login(actor)
            page = self.client.get(reverse('question', args=[self.q.pk]))
            self.assertContains(page, '题目预览')
            self.assertContains(page, '查看学生成绩与提交')
            self.assertNotContains(page, '编写并提交')
            self.assertNotContains(page, '本题提交记录')
            self.assertEqual(page.context['back_url'], reverse('assignment', args=[self.a.pk]))

    def test_assistant_without_edit_or_grades_does_not_see_controls(self):
        ClassStaff.objects.filter(user=self.assistant).update(can_edit=False, can_view_grades=False)
        self.client.force_login(self.assistant)
        page = self.client.get(reverse('question', args=[self.q.pk]))
        self.assertNotContains(page, '编辑题目')
        self.assertNotContains(page, '查看学生成绩与提交')
        self.assertEqual(
            self.client.get(reverse('problem_create', args=[self.c.pk])).status_code, 403
        )

    def test_repeated_draft_save_updates_same_record_and_questions(self):
        version, _ = save_assignment(self.teacher, self.c, None, self.assignment_data())
        assignment = version.assignment
        question_id = version.questions.get().pk
        again, _ = save_assignment(
            self.teacher, self.c, assignment, self.assignment_data(version, title='草稿的最新内容')
        )
        self.assertEqual(again.pk, version.pk)
        self.assertEqual(assignment.versions.count(), 1)
        self.assertEqual(assignment.rules.count(), 1)
        self.assertEqual(again.questions.get().pk, question_id)
        self.assertEqual(again.title, '草稿的最新内容')
        self.client.force_login(self.teacher)
        page = self.client.get(reverse('assignment', args=[assignment.pk]))
        self.assertContains(page, '草稿的最新内容')
        self.assertNotContains(page, 'VERSION')
        self.assertEqual(page.context['back_url'], reverse('class_detail', args=[self.c.pk]))
        self.assertRedirects(
            self.client.get(reverse('assignment_version', args=[version.pk])),
            reverse('assignment', args=[assignment.pk]),
        )

    def test_teacher_edit_applies_immediately_and_preserves_submission_and_grade(self):
        submission = self.submit()
        self.finish(submission)
        grade = make_revision(self.teacher, self.a)
        publish_grades(self.teacher, grade)
        snapshot = submission.rule_snapshot.copy()
        original_question = submission.question_id
        version, pending = save_assignment(
            self.teacher,
            self.c,
            self.a,
            self.assignment_data(**{f'score_{self.p.problem_id}': Decimal(80)}),
        )
        self.a.refresh_from_db()
        submission.refresh_from_db()
        self.v.refresh_from_db()
        self.rule.refresh_from_db()
        self.assertEqual(pending, '')
        self.assertEqual(version.status, 'published')
        self.assertEqual(self.a.current_version_id, version.pk)
        self.assertEqual(version.questions.get().max_score, 80)
        self.assertEqual(self.v.title, '测试作业')
        self.assertEqual(self.rule.max_attempts, 20)
        self.assertEqual(submission.question_id, original_question)
        self.assertEqual(submission.rule_snapshot, snapshot)
        self.assertEqual(self.a.current_grade_id, grade.pk)
        self.assertEqual(grade.students.get().total, 100)

    def test_edit_form_posts_and_redirects_to_same_assignment(self):
        self.client.force_login(self.teacher)
        url = reverse('assignment_edit', args=[self.c.pk, self.a.pk])
        data = self.assignment_data(problems=[self.p.pk])
        page = self.client.post(url, data, follow=True)
        self.assertContains(page, '作业已更新，学生打开作业即可看到当前内容')
        self.assertContains(page, '更新后的作业')
        self.assertEqual(page.redirect_chain[-1][0], reverse('assignment', args=[self.a.pk]))

    def test_assistant_edits_stay_in_single_draft_until_teacher_publishes(self):
        draft, _ = save_assignment(self.assistant, self.c, self.a, self.assignment_data())
        again, _ = save_assignment(
            self.assistant, self.c, self.a, self.assignment_data(draft, title='助教修改后的作业')
        )
        self.a.refresh_from_db()
        self.assertEqual(draft.pk, again.pk)
        self.assertEqual(self.a.current_version_id, self.v.pk)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('assignment', args=[self.a.pk])), '测试作业')
        self.client.force_login(self.assistant)
        page = self.client.get('/')
        self.assertContains(page, '助教修改后的作业', count=1)
        self.assertNotContains(page, 'v2')
        self.assertEqual(
            self.client.post(
                reverse('assignment_action', args=[draft.pk]),
                {'action': 'publish', 'edit_token': edit_token(again)},
            ).status_code,
            403,
        )
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('assignment_action', args=[draft.pk]),
            {'action': 'publish', 'edit_token': edit_token(again)},
        )
        self.a.refresh_from_db()
        self.assertEqual(self.a.current_version_id, draft.pk)

    def test_stale_editor_cannot_overwrite_another_person(self):
        data = self.assignment_data()
        draft, _ = save_assignment(self.assistant, self.c, self.a, data)
        with self.assertRaisesMessage(ValidationError, '已被更新'):
            save_assignment(self.teacher, self.c, self.a, data)
        stale = self.assignment_data(draft)
        save_assignment(
            self.assistant, self.c, self.a, self.assignment_data(draft, title='同一个草稿已更新')
        )
        with self.assertRaisesMessage(ValidationError, '已被更新'):
            save_assignment(self.teacher, self.c, self.a, stale)

    def test_stale_publish_page_cannot_publish_unseen_draft_changes(self):
        draft, _ = save_assignment(self.assistant, self.c, self.a, self.assignment_data())
        token = edit_token(draft)
        save_assignment(
            self.assistant, self.c, self.a, self.assignment_data(draft, title='再次修改')
        )
        self.client.force_login(self.teacher)
        page = self.client.post(
            reverse('assignment_action', args=[draft.pk]),
            {'action': 'publish', 'edit_token': token},
            follow=True,
        )
        self.assertContains(page, '重新打开并检查当前内容后发布')
        self.a.refresh_from_db()
        self.assertEqual(self.a.current_version_id, self.v.pk)

    def test_existing_submissions_keep_stable_question_set_and_selection(self):
        self.submit()
        with self.assertRaisesMessage(ValidationError, '已有提交'):
            save_assignment(self.teacher, self.c, self.a, self.assignment_data(selection='latest'))
        with self.assertRaisesMessage(ValidationError, '已有提交'):
            save_assignment(self.teacher, self.c, self.a, self.assignment_data(problems=[]))
        self.assertEqual(self.a.versions.count(), 1)

    def test_create_problem_with_no_cases_or_reference_program(self):
        self.client.force_login(self.teacher)
        url = reverse('problem_create', args=[self.c.pk])
        page = self.client.get(url)
        self.assertContains(page, '预留接入')
        self.assertNotContains(page, 'name="reference_code"')
        self.assertNotContains(page, 'id_cases-')
        with patch('school.teaching_views.dispatch_reference') as dispatch:
            self.assertEqual(
                self.client.post(url, self.problem_data(title='等待接入的新题')).status_code, 302
            )
            dispatch.assert_not_called()
        problem = ProblemVersion.objects.latest('pk')
        self.assertEqual(problem.reference_path, '')
        self.assertFalse(problem.cases.exists())
        self.assertFalse(problem.reference_verified)
        self.assertFalse(problem.evaluation_configured)

    def test_problem_edit_preserves_existing_judge_assets_and_shows_only_current(self):
        self.client.force_login(self.teacher)
        url = reverse('problem_edit', args=[self.c.pk, self.p.pk])
        self.client.post(url, self.problem_data(title='更新的题目标题'))
        latest = self.p.problem.versions.latest('number')
        self.assertEqual(latest.reference_path, self.p.reference_path)
        self.assertEqual(latest.cases.count(), self.p.cases.count())
        self.assertTrue(latest.reference_verified)
        self.p.refresh_from_db()
        self.assertEqual(self.p.title, '加法')
        page = self.client.get(reverse('problems', args=[self.c.pk]))
        self.assertEqual(len(page.context['versions']), 1)
        self.assertContains(page, '更新的题目标题')
        self.assertNotContains(page, '>v1<')
        self.assertRedirects(
            self.client.get(url), reverse('problem_edit', args=[self.c.pk, latest.pk])
        )
        page = self.client.post(url, self.problem_data(title='过期的修改'))
        self.assertContains(page, '题目已被更新')
        self.assertEqual(self.p.problem.versions.count(), 2)
        form = self.client.get(reverse('assignment_edit', args=[self.c.pk, self.a.pk])).context[
            'form'
        ]
        self.assertEqual(list(form.fields['problems'].queryset), [latest])
        self.assertEqual(form.initial['problems'], [latest.pk])

    def test_changing_judge_limits_requires_fresh_validation(self):
        self.client.force_login(self.teacher)
        with patch('school.teaching_views.dispatch_reference') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    reverse('problem_edit', args=[self.c.pk, self.p.pk]),
                    self.problem_data(time_ms=500),
                )
                dispatch.assert_not_called()
            dispatch.assert_called_once()
        latest = self.p.problem.versions.latest('number')
        self.assertFalse(latest.reference_verified)

    def test_pending_problem_saves_assignment_draft_without_replacing_published_content(self):
        self.p.reference_path = ''
        self.p.reference_verified = False
        self.p.save()
        draft, pending = save_assignment(self.teacher, self.c, self.a, self.assignment_data())
        self.a.refresh_from_db()
        self.assertIn('评测待接入', pending)
        self.assertEqual(draft.status, 'draft')
        self.assertEqual(self.a.current_version_id, self.v.pk)
        with self.assertRaisesMessage(ValidationError, '评测待接入'):
            publish_assignment(self.teacher, draft)

    def test_pending_problem_does_not_start_docker_or_become_a_failure(self):
        self.p.reference_path = ''
        self.p.reference_verified = False
        self.p.save()
        with patch('school.judge.subprocess.run') as run:
            self.assertFalse(verify_reference(self.p.pk))
            run.assert_not_called()
        self.p.refresh_from_db()
        self.assertEqual(self.p.verification_error, '')

    def test_return_links_for_grades_submission_and_assignment_edit(self):
        sub = self.submit()
        self.client.force_login(self.teacher)
        for name, args, expected in (
            ('grades', [self.a.pk], reverse('assignment', args=[self.a.pk])),
            ('submission', [sub.pk], reverse('grades', args=[self.a.pk])),
            ('assignment_edit', [self.c.pk, self.a.pk], reverse('assignment', args=[self.a.pk])),
            ('problem_create', [self.c.pk], reverse('problems', args=[self.c.pk])),
        ):
            with self.subTest(name=name):
                page = self.client.get(reverse(name, args=args))
                self.assertEqual(page.context['back_url'], expected)
                self.assertContains(page, f'href="{expected}"')

    def test_student_cannot_read_draft_or_use_teaching_mutations(self):
        draft, _ = save_assignment(self.teacher, self.c, None, self.assignment_data())
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse('assignment', args=[draft.assignment_id])).status_code, 404
        )
        for name, args in (
            ('problem_create', [self.c.pk]),
            ('assignment_edit', [self.c.pk, self.a.pk]),
        ):
            self.assertEqual(self.client.post(reverse(name, args=args), {}).status_code, 403)
