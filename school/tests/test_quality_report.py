import hashlib
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.course_models import CourseworkRubric, CourseworkSubmission, QualityReport
from school.models import (
    Classroom,
    ClassStaff,
    ClassStudent,
    Coursework,
    CourseworkItem,
    User,
    UserRole,
)
from school.portal import quality_service, submission_services
from school.storage import read_private, save_private

SOURCE = (
    "def func301(A, B):\n"
    "    C = A + B\n"
    "    return C[7:15]\n"
)

MANUAL_ARCHIVE = b'PK\x03\x04fake'

RUBRIC_MARKDOWN = (
    '## 二、5 分制量表\n\n'
    '| 维度 | 权重 | 5 分 | 4 分 | 3 分 | 2 分 | 1 分 |\n'
    '| --- | --- | --- | --- | --- | --- | --- |\n'
    '| 知识点掌握 | 50 | A | B | C | D | E |\n'
    '| 语法规范 | 20 | A | B | C | D | E |\n'
    '| 边界健壮 | 20 | A | B | C | D | E |\n'
    '| 逻辑正确 | 10 | A | B | C | D | E |\n'
)

UPDATED_RUBRIC_MARKDOWN = (
    RUBRIC_MARKDOWN.replace('| 知识点掌握 | 50 |', '| 知识点掌握 | 30 |')
    .replace('| 语法规范 | 20 |', '| 语法规范 | 30 |')
    .replace('| 逻辑正确 | 10 |', '| 逻辑正确 | 20 |')
)


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class QualityReportTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

        self.teacher = self._user('teacher', 'teacher')
        self.student = self._user('student', 'student')
        self.other = self._user('other', 'student')
        self.classroom = Classroom.objects.create(code='Q1', name='评测班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
            can_export=True,
        )
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        ClassStudent.objects.create(classroom=self.classroom, student=self.other)

        self.work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='列表作业',
            description='实现 func301',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        CourseworkItem.objects.create(
            coursework=self.work,
            function_name='func301',
            title='合并两列表并取第 8~15 个',
            points=10,
            order=1,
        )
        self.entry = CourseworkSubmission.objects.create(
            coursework=self.work,
            student=self.student,
            sequence=1,
            source_path=save_private(SOURCE, '.py'),
            source_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
            snapshot={'items': [], 'max_score': 10, 'grading_mode': 'automatic'},
            status='done',
        )

    def _user(self, username, role):
        user = User.objects.create_user(
            username=username,
            full_name=username,
            student_no=username,
            password='Password-2026!',
            must_change_password=False,
        )
        UserRole.objects.create(user=user, role=role)
        return user

    def test_student_sees_own_report(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'func301')
        self.assertContains(response, '代码评测报告')
        report = QualityReport.objects.get(submission=self.entry)
        self.assertEqual(report.source_sha256, self.entry.source_hash)
        self.assertTrue(report.payload['tasks'])
        self.assertTrue(report.markdown_key)

    def test_report_is_reused_for_same_source(self):
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        first = QualityReport.objects.get(submission=self.entry)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        second = QualityReport.objects.get(submission=self.entry)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.markdown_key, second.markdown_key)

    def test_other_student_is_forbidden(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_teacher_can_view(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)

    def test_radar_and_markdown_download(self):
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        report = QualityReport.objects.get(submission=self.entry)
        if report.radar_key:
            radar = self.client.get(reverse('quality_radar', args=[self.entry.pk]))
            self.assertEqual(radar.status_code, 200)
            self.assertEqual(radar['Content-Type'], 'image/png')
        download = self.client.get(reverse('quality_markdown', args=[self.entry.pk]))
        self.assertEqual(download.status_code, 200)
        # 读完流并关闭，避免 Windows 上临时文件句柄未释放导致清理失败
        b''.join(download.streaming_content)
        download.close()

    def test_manual_work_has_no_report(self):
        manual = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='人工批阅作业',
            grading_mode='manual',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        entry = CourseworkSubmission.objects.create(
            coursework=manual,
            student=self.student,
            sequence=1,
            source_path=save_private(MANUAL_ARCHIVE, '.zip'),
            source_hash=hashlib.sha256(MANUAL_ARCHIVE).hexdigest(),
            snapshot={'items': [], 'max_score': 10, 'grading_mode': 'manual'},
            status='review',
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[entry.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(QualityReport.objects.filter(submission=entry).exists())
        page = self.client.get(reverse('work', args=[manual.pk]))
        self.assertNotContains(page, '查看评测报告')

    def _rubric(self, markdown):
        return CourseworkRubric.objects.create(
            coursework=self.work,
            markdown=markdown,
            knowledge_points=[],
            dimensions=[],
            source='rule',
        )

    def test_report_uses_coursework_rubric_markdown(self):
        self._rubric(RUBRIC_MARKDOWN)
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        report = QualityReport.objects.get(submission=self.entry)
        scores = report.payload['scores']
        self.assertEqual(
            [item['key'] for item in scores],
            ['knowledge', 'syntax', 'boundary', 'logic'],
        )
        self.assertEqual([item['weight'] for item in scores], [50, 20, 20, 10])
        self.assertIn('取自评分标准 Markdown', report.payload['rubric_note'])
        page = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        # 只有 4 个维度、无法对应 6 个主能力时，仍按评分维度展示
        self.assertContains(page, '评分维度得分与雷达图')

    def test_rubric_change_regenerates_report(self):
        rubric = self._rubric(RUBRIC_MARKDOWN)
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        first = QualityReport.objects.get(submission=self.entry)
        rubric.markdown = UPDATED_RUBRIC_MARKDOWN
        rubric.save()
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        second = QualityReport.objects.get(submission=self.entry)
        self.assertNotEqual(first.markdown_key, second.markdown_key)
        self.assertEqual(
            [item['weight'] for item in second.payload['scores']],
            [30, 30, 20, 20],
        )

    def test_work_page_shows_report_button(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('work', args=[self.work.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '查看评测报告')
        self.assertContains(response, reverse('quality_report', args=[self.entry.pk]))

    def test_entry_page_shows_report_button(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('entry', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('quality_report', args=[self.entry.pk]))

    def test_report_table_headers_and_lint_issues(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertContains(response, '题目编号')
        self.assertContains(response, '作业考察的知识点')

        report = QualityReport.objects.get(submission=self.entry)
        issues = report.payload['tasks'][0]['issues']
        # SOURCE 里的 A/B/C 是单字母变量名，pylint 的命名提示必须出现在缺陷表里
        self.assertTrue(issues)
        self.assertIn('命名', ''.join(item['message'] for item in issues))
        # 修改建议只给方向，不能附代码
        self.assertNotIn('def ', ''.join(item['advice'] for item in issues))

    def test_markdown_report_uses_required_headers(self):
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        report = QualityReport.objects.get(submission=self.entry)
        text = read_private(report.markdown_key)
        self.assertIn('| 题目编号 | 作业考察的知识点 | 缺陷及所在代码行 | 修改建议 |', text)
        self.assertIn('| 维度 | 权重 | 得分 |', text)

    def test_branch_course_reports_knowledge_points(self):
        work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='04-分支结构习题说明',
            description='实现 func404',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        CourseworkItem.objects.create(
            coursework=work,
            function_name='func404',
            title='比较两个正整数并返回较大值',
            points=10,
            order=1,
        )
        source = 'def func404(a, b):\n    return a if a > b else b\n'
        entry = CourseworkSubmission.objects.create(
            coursework=work,
            student=self.student,
            sequence=1,
            source_path=save_private(source, '.py'),
            source_hash=hashlib.sha256(source.encode()).hexdigest(),
            snapshot={'items': [], 'max_score': 10, 'grading_mode': 'automatic'},
            status='done',
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[entry.pk]))
        self.assertEqual(response.status_code, 200)
        # 知识点名统一为《Python教学Tag库》标准名（if_else → if-else 双分支）
        self.assertContains(response, 'if-else 双分支')
        self.assertNotContains(response, '未配置知识点模板')

    def test_missing_rubric_is_generated_and_saved(self):
        """作业还没有评分标准时，首次出报告会按该任务题目自动生成并存库。"""
        self.assertFalse(CourseworkRubric.objects.filter(coursework=self.work).exists())
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        rubric = CourseworkRubric.objects.get(coursework=self.work)
        self.assertEqual(len(rubric.dimensions), 6)
        self.assertEqual(len(rubric.abilities), 6)
        self.assertTrue(rubric.knowledge_points)
        self.assertEqual(rubric.source, 'rule')

    def test_report_uses_coursework_rubric_knowledge_points(self):
        """逐题明细的知识点列取作业评分标准，而不是评测器按题库规格推断的标签。"""
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        CourseworkRubric.objects.update_or_create(
            coursework=self.work,
            defaults={
                'markdown': '## 一、作业考察的知识点\n\n## 二、5 分制量表\n',
                'knowledge_points': [
                    {
                        'name': '列表切片边界换算',
                        'detail': '1 起始计数换算为 0 起始下标',
                        'tasks': ['func301'],
                    }
                ],
                'dimensions': [],
                'source': 'rule',
            },
        )
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '列表切片边界换算')
        self.assertNotContains(response, '未配置知识点模板')
        self.assertNotContains(response, '列表合并（+ / extend）')

        report = QualityReport.objects.get(submission=self.entry)
        points = report.payload['tasks'][0]['points']
        self.assertEqual([point['label'] for point in points], ['列表切片边界换算'])
        # 模型自定义名称无法对应到题库检测标签，只展示、不给出 ✓/✗
        self.assertFalse(points[0]['judged'])
        markdown = read_private(report.markdown_key)
        self.assertIn('列表切片边界换算', markdown)
        self.assertNotIn('列表切片边界换算 ✓', markdown)

    def test_knowledge_point_matching_curriculum_label_is_judged(self):
        """评分标准里的知识点与题库标签同名时，仍能判断学生代码是否用到。"""
        CourseworkRubric.objects.create(
            coursework=self.work,
            markdown='## 一、作业考察的知识点\n',
            knowledge_points=[{'name': '列表合并（+ / extend）', 'tasks': ['func301']}],
            dimensions=[],
            source='rule',
        )
        self.client.force_login(self.student)
        self.client.get(reverse('quality_report', args=[self.entry.pk]))
        report = QualityReport.objects.get(submission=self.entry)
        point = report.payload['tasks'][0]['points'][0]
        self.assertEqual(point['label'], '列表合并（+ / extend）')
        self.assertTrue(point['judged'])
        self.assertTrue(point['ok'])

    # ---- 逐题明细知识点以评分标准 Markdown 的知识点表格为准 ----

    def test_knowledge_points_table_parser(self):
        from tools.code_quality_agent import rubric as agent_rubric

        markdown = (
            '# 测试作业 · 评分标准\n\n'
            '## 一、作业考察的知识点\n\n'
            '| 序号 | 知识点 | 说明 | 涉及题目 |\n'
            '| --- | --- | --- | --- |\n'
            '| 1 | 切片起始换算 | 下标从 1 起需减一 | func301 |\n'
            '| 2 | 列表合并 | 拼接两个列表 | func301、func302 |\n'
            '| 3 | 通用程序设计 | 函数定义与返回值 | 全部题目 |\n'
        )
        self.assertEqual(
            agent_rubric.knowledge_points_from_text(markdown),
            [
                ('切片起始换算', ['func301']),
                ('列表合并', ['func301', 'func302']),
                ('通用程序设计', []),
            ],
        )
        # 没有知识点表格时返回 None，由调用方回退到结构化字段
        self.assertIsNone(agent_rubric.knowledge_points_from_text('## 一、作业考察的知识点\n'))

    def test_detail_points_follow_rubric_markdown_table(self):
        """知识点表格优先于 JSON 字段，涉及题目支持题目名称与“全部题目”。"""
        CourseworkRubric.objects.create(
            coursework=self.work,
            markdown=(
                '## 一、作业考察的知识点\n\n'
                '| 序号 | 知识点 | 说明 | 涉及题目 |\n'
                '| --- | --- | --- | --- |\n'
                '| 1 | 切片起始换算 | 下标换算 | 合并两列表并取第 8~15 个 |\n'
                '| 2 | 通用程序设计 | 函数定义 | 全部题目 |\n'
            ),
            knowledge_points=[{'name': '过期字段里的知识点', 'tasks': ['func301']}],
            dimensions=[],
            source='rule',
        )
        mapping = quality_service.knowledge_points_for(
            self.work, [('func301', '合并两列表并取第 8~15 个')]
        )
        self.assertEqual(mapping, {'func301': ('切片起始换算', '通用程序设计')})

    def test_radar_axes_are_six_abilities(self):
        """评分标准有 6 个主能力时，雷达图与得分表按能力名展示。"""
        abilities = [
            {'label': '数据组织与容器操作', 'dimension': 'knowledge', 'points': []},
            {'label': '流程控制与分支循环', 'dimension': 'logic', 'points': []},
            {'label': '字符串与内置方法', 'dimension': 'syntax', 'points': []},
            {'label': '函数设计与结构', 'dimension': 'structure', 'points': []},
            {'label': '边界与异常处理', 'dimension': 'boundary', 'points': []},
            {'label': '规范与可读性', 'dimension': 'readability', 'points': []},
        ]
        CourseworkRubric.objects.create(
            coursework=self.work,
            markdown='## 一、作业考察的知识点\n',
            knowledge_points=[],
            dimensions=[
                {'key': 'knowledge', 'label': '知识点覆盖', 'weight': 25},
                {'key': 'syntax', 'label': '语法与规范', 'weight': 20},
                {'key': 'boundary', 'label': '边界与健壮性', 'weight': 15},
                {'key': 'logic', 'label': '题意正确性', 'weight': 25},
                {'key': 'structure', 'label': '代码结构', 'weight': 5},
                {'key': 'readability', 'label': '可读性', 'weight': 10},
            ],
            abilities=abilities,
            source='llm',
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '主能力得分与雷达图')
        self.assertContains(response, '数据组织与容器操作')

        report = QualityReport.objects.get(submission=self.entry)
        scores = report.payload['scores']
        self.assertEqual(
            [item['label'] for item in scores],
            [ability['label'] for ability in abilities],
        )
        self.assertEqual(
            [item['key'] for item in scores],
            [ability['dimension'] for ability in abilities],
        )
        self.assertEqual(report.payload['axis_label'], '主能力')
        self.assertContains(response, 'data-radar')
        self.assertContains(response, 'radar-tooltip')
        radar = report.payload['radar']
        self.assertEqual(len(radar['axes']), 6)
        self.assertEqual(len(radar['rings']), 4)
        self.assertEqual(
            [axis['label'] for axis in radar['axes']],
            [ability['label'] for ability in abilities],
        )

    def test_knowledge_axes_are_top_tags(self):
        """雷达图六轴：该作业最主要的六个知识点 Tag，分数取 Tag 检测点覆盖率。"""
        from tools.code_quality_agent import models as agent_models
        from tools.code_quality_agent.pipeline import StudentAnalysis

        knowledge_points = {
            'func301': ('列表拼接', '列表切片'),
            'func303': ('步长切片',),
        }
        results = [
            agent_models.TaskResult(
                spec=agent_models.TaskSpec('func301', '合并截取', ('list_concat', 'slice_bounds')),
                parsed=True,
                covered=['list_concat'],
            ),
            agent_models.TaskResult(
                spec=agent_models.TaskSpec('func303', '回文判断', ('slice_reverse',)),
                parsed=True,
                covered=['slice_reverse'],
            ),
        ]
        analysis = StudentAnalysis(
            name='学生', file_name='a.py', results=results,
            scores={'knowledge': 80.0}, total=80.0,
        )
        # func301 分值 20（每 tag 重要度 3.0）> func303 分值 10（2.0）
        axes = quality_service.knowledge_axes(
            knowledge_points, {'func301': 20, 'func303': 10}, analysis
        )
        self.assertIsNotNone(axes)
        dimensions, tag_scores, tag_levels = axes
        labels = [dimension.label for dimension in dimensions]
        self.assertEqual(
            labels, ['列表切片', '列表拼接', '步长切片']
        )
        # 权重归一化
        self.assertAlmostEqual(sum(item.weight for item in dimensions), 1.0, places=2)
        # 五分制量表：覆盖率 100% → 5 级 → 100 分
        self.assertEqual(tag_scores['tag:步长切片'], 100.0)
        self.assertEqual(tag_levels['tag:步长切片'], 5)
        self.assertEqual(tag_scores['tag:列表拼接'], 100.0)
        # 列表切片：slice_bounds 未覆盖 → 1 级（量表的 1 分）→ 20 分
        self.assertEqual(tag_scores['tag:列表切片'], 20.0)
        self.assertEqual(tag_levels['tag:列表切片'], 1)

    def test_knowledge_axes_follow_rubric_scale(self):
        """雷达轴与等级以评分标准“考察重点（雷达图维度）”的五分制量表为准。"""
        from tools.code_quality_agent import models as agent_models
        from tools.code_quality_agent.pipeline import StudentAnalysis

        knowledge_points = {'func301': ('列表拼接',)}
        results = [
            agent_models.TaskResult(
                spec=agent_models.TaskSpec('func301', '合并截取', ('list_concat',)),
                parsed=True,
                covered=['list_concat'],
            ),
        ]
        analysis = StudentAnalysis(
            name='学生', file_name='a.py', results=results,
            scores={'knowledge': 80.0}, total=80.0,
        )
        rubric_axes = [
            {
                'name': '列表拼接',
                'share': 0.7,
                'levels': {'5': 'a', '4': 'b', '3': 'c', '2': 'd', '1': 'e'},
                'tasks': ['func301'],
            },
            {
                'name': '列表切片',
                'share': 0.3,
                'levels': {'5': 'a', '4': 'b', '3': 'c', '2': 'd', '1': 'e'},
                'tasks': ['func301'],
            },
        ]
        axes = quality_service.knowledge_axes(
            knowledge_points, {'func301': 20}, analysis, rubric_axes=rubric_axes
        )
        dimensions, tag_scores, tag_levels = axes
        # 轴的名称与权重来自评分标准，而不是重新按频次挑选
        self.assertEqual([d.label for d in dimensions], ['列表拼接', '列表切片'])
        self.assertEqual([round(d.weight, 2) for d in dimensions], [0.7, 0.3])
        self.assertEqual(tag_scores['tag:列表拼接'], 100.0)
        # 列表切片在该作业没有可机检检测点 → 退回“知识点覆盖”维度得分 80 → 4 级/80 分
        self.assertEqual(tag_levels['tag:列表切片'], 4)
        self.assertEqual(tag_scores['tag:列表切片'], 80.0)

    def test_knowledge_axes_fall_back_for_legacy_names(self):
        """旧评分标准的自定义知识点名无法归一到词表时，退回主能力轴。"""
        from tools.code_quality_agent.pipeline import StudentAnalysis

        analysis = StudentAnalysis(
            name='学生', file_name='a.py', results=[],
            scores={'knowledge': 80.0}, total=80.0,
        )
        axes = quality_service.knowledge_axes(
            {'func301': ('切片起始换算', '通用程序设计')}, {'func301': 10}, analysis
        )
        self.assertIsNone(axes)

    def test_report_radar_uses_tag_axes(self):
        """评分标准知识点为 Tag 标准名时，报告页六轴展示考察重点。"""
        CourseworkRubric.objects.create(
            coursework=self.work,
            markdown=(
                '## 一、作业考察的知识点\n\n'
                '| 序号 | 知识点 | 说明 | 涉及题目 |\n| --- | --- | --- | --- |\n'
                '| 1 | 列表拼接 | + 拼接 | func301 |\n'
                '| 2 | 列表切片 | 1 起始换算 | func301 |\n'
            ),
            knowledge_points=[
                {'name': '列表拼接', 'detail': '', 'tasks': ['func301']},
                {'name': '列表切片', 'detail': '', 'tasks': ['func301']},
            ],
            dimensions=[],
            source='rule',
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('quality_report', args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        report = QualityReport.objects.get(submission=self.entry)
        self.assertEqual(report.payload['axis_label'], '考察重点')
        labels = [item['label'] for item in report.payload['scores']]
        # 同重要度按名称排序：列表切片 < 列表拼接
        self.assertEqual(labels, ['列表切片', '列表拼接'])
        self.assertEqual(
            [axis['label'] for axis in report.payload['radar']['axes']], labels
        )

    # ---- 学生提交后后台预生成质量报告 ----

    def test_submit_schedules_quality_analysis_for_automatic(self):
        with mock.patch.object(submission_services, 'schedule_generate') as scheduled:
            entry = submission_services.submit(
                self.student,
                self.work.pk,
                {'request_id': str(uuid.uuid4()), 'source': SOURCE},
            )
        scheduled.assert_called_once_with(entry.pk)

    def test_submit_skips_quality_analysis_for_manual(self):
        manual_work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='非机器批阅作业',
            grading_mode='manual',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        with mock.patch.object(submission_services, 'schedule_generate') as scheduled:
            entry = submission_services.submit(
                self.student,
                manual_work.pk,
                {'request_id': str(uuid.uuid4()), 'source': {'raw': MANUAL_ARCHIVE}},
            )
        scheduled.assert_not_called()

    def test_generate_entry_job_creates_report(self):
        quality_service._generate_entry_job(self.entry.pk)
        report = QualityReport.objects.get(submission=self.entry)
        self.assertEqual(report.source_sha256, self.entry.source_hash)

    def test_generate_entry_job_ignores_unsupported_submission(self):
        manual_work = Coursework.objects.create(
            classroom=self.classroom,
            owner=self.teacher,
            title='非机器批阅作业',
            grading_mode='manual',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
            status='open',
        )
        manual_entry = CourseworkSubmission.objects.create(
            coursework=manual_work,
            student=self.student,
            sequence=1,
            source_path=save_private(MANUAL_ARCHIVE, '.zip'),
            snapshot={'items': [], 'max_score': 10, 'grading_mode': 'manual'},
            status='review',
        )
        quality_service._generate_entry_job(manual_entry.pk)
        self.assertFalse(QualityReport.objects.filter(submission=manual_entry).exists())
