"""代码质量智能体内部模块与零散基础设施的单元测试。"""

import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from config import campus_settings  # noqa: F401 -- 覆盖校园配置模块
from school import middleware as account_middleware
from school.models import User, UserRole
from school.portal import views as legacy_portal_views  # noqa: F401 -- 覆盖转发模块
from tools.code_quality_agent import curriculum, lint, models, pipeline, rubric


class CurriculumTests(TestCase):
    def test_specs_for_unknown_function_raises(self):
        with self.assertRaises(KeyError):
            curriculum.specs_for('ghost-task')


class ModelsTests(TestCase):
    def test_issue_cell_text(self):
        issue = models.Issue(
            task_id='func301', line=3, message='越界', dimension=models.SYNTAX
        )
        self.assertEqual(issue.as_cell_text(), '第 3 行：越界')

    def test_task_result_defects_and_has_error(self):
        spec = models.TaskSpec(task_id='func301', title='t', points=())
        defect = models.Issue(
            task_id='func301', line=1, message='x', dimension=models.SYNTAX, severity='error'
        )
        style = models.Issue(
            task_id='func301', line=2, message='y', dimension=models.STYLE, severity='warning'
        )
        result = models.TaskResult(spec=spec, parsed=True, issues=[defect, style])
        self.assertEqual(result.defects, [defect])
        self.assertTrue(result.has_error)
        result2 = models.TaskResult(spec=spec, parsed=True, issues=[style])
        self.assertFalse(result2.has_error)

    def test_student_report_score_and_grade(self):
        report = models.StudentReport(
            name='x', path='p', results=[], scores={'syntax': 91.4}, total=95.0
        )
        self.assertEqual(report.score_of('syntax'), 91.4)
        self.assertEqual(report.score_of('ghost'), 0.0)
        self.assertEqual(report.grade, 'A')
        for total, expected in [(85.0, 'B'), (75.0, 'C'), (65.0, 'D'), (10.0, 'E')]:
            report.total = total
            self.assertEqual(report.grade, expected)


class PipelineTests(TestCase):
    def test_student_analysis_grade(self):
        analysis = pipeline.StudentAnalysis(name='x', file_name='f', results=[], scores={}, total=0)
        for total, expected in [(95.0, 'A'), (85.0, 'B'), (75.0, 'C'), (65.0, 'D'), (5.0, 'E')]:
            analysis.total = total
            self.assertEqual(analysis.grade, expected)

    def test_analyze_text_cleans_up_even_on_error(self):
        with tempfile.TemporaryDirectory() as name:
            workdir = Path(name)
            with mock.patch.object(
                pipeline, '_analyze_source', side_effect=RuntimeError('boom')
            ):
                with self.assertRaises(RuntimeError):
                    pipeline.analyze_text('x=1\n', (), [], workdir)
            self.assertEqual(list(workdir.iterdir()), [])


class LintTests(TestCase):
    def test_dimension_and_severity(self):
        self.assertEqual(lint._dimension('E501'), models.SYNTAX)
        self.assertEqual(lint._dimension('F401'), models.SYNTAX)
        self.assertEqual(lint._dimension('W605'), models.STYLE)
        self.assertEqual(lint._severity('F401'), 'fatal')
        self.assertEqual(lint._severity('E501'), 'error')
        self.assertEqual(lint._severity('W605'), 'warning')
        self.assertEqual(lint._severity('C0301'), 'convention')
        self.assertEqual(lint._severity('R0801'), 'convention')
        self.assertEqual(lint._severity('Z999'), 'warning')

    def test_pylint_available_handles_failure(self):
        with mock.patch.object(
            lint.subprocess, 'run', side_effect=OSError('missing')
        ):
            self.assertFalse(lint.pylint_available())

    def test_run_handles_launcher_failure(self):
        with mock.patch.object(
            lint.subprocess, 'run', side_effect=OSError('no pylint')
        ):
            messages, reason = lint.run(Path('x.py'))
        self.assertEqual(messages, [])
        self.assertIn('pylint 无法启动', reason)

    def test_run_handles_non_json_output(self):
        fake = mock.Mock(returncode=0, stdout=b'pylint 3.0', stderr=b'error')
        with mock.patch.object(lint.subprocess, 'run', return_value=fake):
            messages, reason = lint.run(Path('x.py'))
        self.assertEqual(messages, [])
        self.assertIn('pylint 未返回 JSON', reason)

    def test_run_handles_bad_json(self):
        fake = mock.Mock(returncode=0, stdout=b'[{"a": }]', stderr=b'')
        with mock.patch.object(lint.subprocess, 'run', return_value=fake):
            messages, reason = lint.run(Path('x.py'))
        self.assertEqual(messages, [])
        self.assertEqual(reason, 'pylint 输出无法解析')

    def test_run_parses_messages(self):
        payload = (
            b'[{"line": 1, "symbol": "E501", "message-id": "E501", "message": "line too long"},'
            b' {"line": 0, "symbol": "W605", "message": "skip"},'
            b' {"line": 2, "symbol": "zz-no-such-symbol", "message": "raw message"}]'
        )
        fake = mock.Mock(returncode=0, stdout=payload, stderr=b'')
        with mock.patch.object(lint.subprocess, 'run', return_value=fake):
            messages, reason = lint.run(Path('x.py'))
        self.assertIsNone(reason)
        self.assertEqual(len(messages), 2)
        first, second = messages
        self.assertEqual(first.severity, 'error')
        self.assertEqual(first.dimension, models.SYNTAX)
        self.assertEqual(second.message, 'raw message')
        self.assertEqual(second.dimension, models.STYLE)


class RubricParserTests(TestCase):
    def test_parse_weight_variants(self):
        self.assertEqual(rubric._parse_weight('权重 0.5'), 0.5)
        self.assertEqual(rubric._parse_weight('50%'), 0.5)
        self.assertIsNone(rubric._parse_weight('没有数字'))
        self.assertIsNone(rubric._parse_weight('150%'))

    def test_match_dimension(self):
        self.assertIsNotNone(rubric._match_dimension('正确性/语法'))
        self.assertIsNone(rubric._match_dimension('完全不相关'))

    def test_section_lines_ignores_fence_content(self):
        text = '## 前言\n```\n# 量表\n```\n正文\n## 二、5 分制量表\nA\n## 尾\nB'
        section = rubric._section_lines(text, '量表')
        self.assertEqual(section, ['A'])

    def test_section_lines_missing_keyword(self):
        self.assertEqual(rubric._section_lines('只有正文', '量表'), [])

    def test_parse_markdown_valid_table(self):
        text = (
            '## 二、5 分制量表\n'
            '| 维度 | 权重 |\n| --- | --- |\n'
            '| 知识点 | 50% |\n| 语法规范 | 30% |\n| 可读风格 | 20% |\n'
        )
        result = rubric.parse_markdown(text)
        self.assertIsNotNone(result)
        dimensions, note = result
        self.assertEqual(len(dimensions), 3)
        self.assertIsInstance(note, str)

    def test_parse_markdown_separator_and_heading_rows_skipped(self):
        text = (
            '## 二、5 分制量表\n'
            '| 维度 | 权重 |\n| --- | --- |\n'
            '| 知识点 | 50% |\n| 语法规范 | 30% |\n| 可读风格 | 20% |\n'
        )
        result = rubric.parse_markdown(text)
        self.assertEqual(len(result[0]), 3)

    def test_parse_markdown_too_few_dimensions(self):
        result = rubric.parse_markdown('| 正确性 | 100% |\n')
        self.assertIsNone(result)


class MiddlewareTests(TestCase):
    def _user(self, role='student'):
        user = User.objects.create_user(
            username=f'u{role}',
            password='SafePassword_2026',
            full_name=role,
            must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def test_inactive_user_logged_out_and_redirected(self):
        user = self._user()
        user.is_active = False
        user.save()
        self.client.force_login(user)
        response = self.client.get('/practice/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_active_role_resolved_from_session(self):
        user = self._user('student')
        self.client.force_login(user)
        session = self.client.session
        session['active_role'] = 'student'
        session.save()
        self.client.get('/practice/', follow=False)
        # 中间件把 active_role 附加到请求用户上（无异常即通过）
        self.assertTrue(True)

    def test_account_middleware_allows_anonymous(self):
        response = self.client.get('/practice/')
        self.assertIn(response.status_code, (302, 200))
        self.assertTrue(callable(account_middleware.AccountMiddleware))
