"""综合能力画像：维度映射、规则算分、大模型诊断校验与页面渲染。"""

import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.course_models import (
    Coursework,
    CourseworkItem,
    CourseworkQuestionResult,
    CourseworkRubric,
    CourseworkSubmission,
    QualityReport,
    StudentCapabilityProfile,
)
from school.models import (
    Classroom,
    ClassStaff,
    ClassStudent,
    User,
    UserLLMConfig,
    UserRole,
)
from school.portal import capability_rules, capability_service
from school.storage import save_private
from tools.taglib import loader as taglib

_PRIVATE_TMP = tempfile.TemporaryDirectory()
PRIVATE_STORAGE_OVERRIDE = Path(_PRIVATE_TMP.name).resolve()

TEST_OVERRIDES = dict(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ROOT_URLCONF='config.urls',
    REDIS_URL='',
    PRIVATE_STORAGE=PRIVATE_STORAGE_OVERRIDE,
    CACHES={'default': {'django.core.cache.backends.locmem.LocMemCache'}},
)


def make_user(username, role):
    user = User.objects.create_user(
        username=username,
        full_name=username,
        student_no=username,
        password='Password-2026!',
        must_change_password=False,
    )
    UserRole.objects.create(user=user, role=role)
    return user


class CapabilityRulesTests(SimpleTestCase):
    """模块映射表与关键词兜底。"""

    def test_module_table_covers_tag_library(self):
        """77 个模块都必须有默认能力维度，否则画像会出现静默偏差。"""
        for _unit, module, _tags in taglib.tag_modules():
            code = module.split()[0]
            self.assertIn(code, capability_rules.MODULE_CAPABILITY, module)

    def test_classify_by_module(self):
        bloom, thinking = capability_rules.classify_labels(['列表切片'])
        self.assertEqual(bloom, {'apply': 1.0})
        self.assertEqual(thinking, {'algorithm': 1.0})

    def test_classify_multiple_labels_split_weight(self):
        bloom, thinking = capability_rules.classify_labels(['列表切片', '算术运算符'])
        self.assertEqual(sum(bloom.values()), 1.0)
        self.assertEqual(set(bloom), {'apply'})  # 两个模块同属「应用」
        self.assertEqual(set(thinking), {'algorithm'})

    def test_classify_falls_back_to_title(self):
        bloom, thinking = capability_rules.classify_labels([], '递归求和')
        self.assertEqual(bloom, {'create': 1.0})
        self.assertEqual(thinking, {'decomposition': 1.0})

    def test_classify_unknown_label_defaults(self):
        bloom, thinking = capability_rules.classify_labels(['量子纠缠'])
        self.assertEqual(bloom, {'apply': 1.0})
        self.assertEqual(thinking, {'algorithm': 1.0})

    def test_level_and_coverage_text(self):
        self.assertEqual(capability_rules.level_of(85), ('A', '优秀'))
        self.assertEqual(capability_rules.level_of(84.9), ('B', '良好'))
        self.assertEqual(capability_rules.level_of(55), ('C', '及格'))
        self.assertEqual(capability_rules.level_of(20), ('D', '待提升'))
        self.assertEqual(capability_rules.coverage_text(0), '暂无该维度的判题记录')
        self.assertIn('样本较少', capability_rules.coverage_text(0.2))
        self.assertIn('覆盖 100%', capability_rules.coverage_text(1.0))


def _task(**overrides):
    task = {
        'work_id': 1,
        'work_title': '作业',
        'task_id': 'func301',
        'title': '列表切片',
        'weight': 10.0,
        'rate': 0.5,
        'labels': ['列表切片'],
        'issues': [],
        'code': '',
        'code_hash': 'hash',
        'report_stamp': '2026-11-14T10:00:00',
        'bloom': {'apply': 1.0},
        'thinking': {'algorithm': 1.0},
    }
    task.update(overrides)
    return task


class CapabilityScoringTests(SimpleTestCase):
    """规则算分与 payload 组装（不依赖数据库）。"""

    def test_score_dimensions_weighted(self):
        tasks = [
            _task(weight=10.0, rate=1.0),
            _task(task_id='func302', weight=10.0, rate=0.0),
        ]
        rows = capability_service._score_dimensions(
            tasks, 'bloom', capability_rules.BLOOM_DIMENSIONS
        )
        by_key = {row['key']: row for row in rows}
        self.assertEqual(by_key['apply']['score'], 50.0)
        self.assertEqual(by_key['apply']['coverage'], 1.0)
        self.assertIsNone(by_key['create']['score'])
        self.assertFalse(by_key['create']['covered'])
        self.assertEqual(by_key['create']['coverage_text'], '暂无该维度的判题记录')

    def test_coded_rate_missing_is_excluded(self):
        tasks = [_task(rate=None)]
        rows = capability_service._score_dimensions(
            tasks, 'bloom', capability_rules.BLOOM_DIMENSIONS
        )
        self.assertTrue(all(row['score'] is None for row in rows))

    def test_code_facts_counts_and_dedupe(self):
        code = (
            'class Box:\n'
            '    def __init__(self):\n'
            '        self.items = [i for i in range(3)]\n'
            '\n'
            'def solve(n):\n'
            '    total = 0\n'
            '    for i in range(n):\n'
            '        if i % 2 == 0:\n'
            '            total += 42\n'
            '    return solve(n - 1) if n > 0 else total\n'
        )
        tasks = [
            _task(work_id=1, code=code),
            _task(work_id=1, task_id='func302', code=code),
        ]
        facts = capability_service.code_facts(tasks)
        self.assertEqual(facts['files'], 1)  # 同一份源码只统计一次
        self.assertEqual(facts['tasks'], 2)
        self.assertEqual(facts['functions'], 2)
        self.assertEqual(facts['classes'], 1)
        self.assertEqual(facts['comprehensions'], 1)
        self.assertEqual(facts['loops'], 1)
        self.assertGreaterEqual(facts['magic_numbers'], 2)
        self.assertEqual(facts['max_depth'], 2)
        self.assertGreaterEqual(facts['recursive_functions'], 1)

    def test_build_payload_shape(self):
        tasks = [_task()]
        payload = capability_service.build_payload(
            None, tasks, capability_service.code_facts(tasks)
        )
        self.assertEqual(len(payload['bloom']), 6)
        self.assertEqual(len(payload['thinking']), 4)
        self.assertEqual(len(payload['radar']['axes']), 6)
        self.assertEqual(payload['thinking'][0]['key'], 'abstraction')
        self.assertTrue(payload['summary'])
        self.assertEqual(payload['meta']['diagnosis'], 'rule')

    def test_signature_changes_with_rate(self):
        first = capability_service._signature([_task(rate=0.5)], '')
        second = capability_service._signature([_task(rate=0.6)], '')
        self.assertNotEqual(first, second)
        self.assertEqual(first, capability_service._signature([_task(rate=0.5)], ''))


class DiagnosisNormalizeTests(SimpleTestCase):
    """大模型诊断的强校验：只保留能对应真实题目与行号的结论。"""

    TASKS = [_task(code='line1\nline2\nline3')]

    def test_valid_payload_accepted(self):
        text = json.dumps(
            {
                'summary': ['切片边界需要加强'],
                'observations': [
                    {
                        'dimension': 'bloom.analyze',
                        'task_id': 'func301',
                        'line': 2,
                        'quote': 'line2',
                        'comment': '未处理空列表',
                        'advice': '先判断长度',
                    }
                ],
                'suggestion': '补边界用例',
            },
            ensure_ascii=False,
        )
        result = capability_service.normalize_diagnosis(text, self.TASKS)
        self.assertEqual(result['summary'], ['切片边界需要加强'])
        self.assertEqual(result['observations'][0]['dimension_label'], '布鲁姆·分析')
        self.assertEqual(result['suggestion'], '补边界用例')

    def test_invalid_items_dropped(self):
        text = json.dumps(
            {
                'summary': ['总体建议'],
                'observations': [
                    {'dimension': 'bloom.analyze', 'task_id': 'func999', 'line': 1,
                     'comment': '不存在的题'},
                    {'dimension': 'quantum', 'task_id': 'func301', 'line': 1,
                     'comment': '不存在的维度'},
                    {'dimension': 'thinking.pattern', 'task_id': 'func301', 'line': 99,
                     'comment': '越界行号'},
                    {'dimension': 'thinking.pattern', 'task_id': 'func301', 'line': 1,
                     'comment': '有效结论', 'advice': '继续'},
                ],
            },
            ensure_ascii=False,
        )
        result = capability_service.normalize_diagnosis(text, self.TASKS)
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(result['observations'][0]['comment'], '有效结论')

    def test_no_usable_content_raises(self):
        with self.assertRaises(capability_service.DiagnosisError):
            capability_service.normalize_diagnosis('{"summary": []}', self.TASKS)
        with self.assertRaises(capability_service.DiagnosisError):
            capability_service.normalize_diagnosis('不是 JSON', self.TASKS)


@override_settings(**TEST_OVERRIDES)
class CapabilityProfileTests(TestCase):
    """真实数据链路：报告 + 代码 → 规则分 → 大模型诊断 → 页面。"""

    def setUp(self):
        self.teacher = make_user('teacher', 'teacher')
        self.student = make_user('student', 'student')
        self.other = make_user('other', 'student')
        self.classroom = Classroom.objects.create(code='C1', name='能力班', term='2026 秋季')
        ClassStaff.objects.create(
            classroom=self.classroom,
            user=self.teacher,
            role='teacher',
            can_edit=True,
            can_view_grades=True,
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
            coursework=self.work, function_name='func301', title='合并并截取', points=10, order=1
        )
        CourseworkRubric.objects.create(
            coursework=self.work,
            markdown='# 评分标准',
            knowledge_points=[{'name': '列表切片', 'detail': '', 'tasks': ['func301']}],
            dimensions=[],
            source='rule',
        )
        self.code = 'def func301(nums):\n    return nums[1:]\n'
        self.entry = CourseworkSubmission.objects.create(
            coursework=self.work,
            student=self.student,
            sequence=1,
            source_path=save_private(self.code, '.py'),
            source_hash=hashlib.sha256(self.code.encode()).hexdigest(),
            status='done',
        )
        CourseworkQuestionResult.objects.create(
            submission=self.entry,
            function_name='func301',
            title='合并并截取',
            order=1,
            points=10,
            score=3,
            passed_cases=3,
            total_cases=4,
            verdict='WA',
        )
        self.report = QualityReport.objects.create(
            submission=self.entry,
            source_sha256=self.entry.source_hash,
            payload={
                'tasks': [
                    {
                        'task_id': 'func301',
                        'points': [{'label': '列表切片', 'ok': False, 'judged': True}],
                        'issues': [
                            {
                                'line': '2',
                                'message': '切片边界未处理空列表',
                                'advice': '先判断长度',
                                'severity': 'error',
                            }
                        ],
                    }
                ]
            },
        )

    def test_collect_tasks_reads_report_and_code(self):
        tasks = capability_service.collect_tasks(self.student)
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task['task_id'], 'func301')
        self.assertEqual(task['labels'], ['列表切片'])
        self.assertAlmostEqual(task['rate'], 0.3)
        self.assertEqual(task['bloom'], {'apply': 1.0})
        self.assertEqual(task['thinking'], {'algorithm': 1.0})
        self.assertIn('def func301', task['code'])
        self.assertEqual(task['issues'][0]['message'], '切片边界未处理空列表')

    def test_view_model_builds_rule_profile(self):
        context = capability_service.view_model(self.student)
        self.assertTrue(context['ready'])
        self.assertFalse(context['refreshing'])
        self.assertEqual(context['source'], 'rule')
        bloom = {row['key']: row for row in context['bloom']}
        self.assertEqual(bloom['apply']['score'], 30.0)
        self.assertEqual(bloom['apply']['coverage_percent'], 100.0)
        self.assertFalse(bloom['create']['covered'])
        thinking = {row['key']: row for row in context['thinking']}
        self.assertEqual(thinking['algorithm']['score'], 30.0)
        self.assertTrue(thinking['algorithm']['evidence'])
        self.assertEqual(len(context['radar']['axes']), 6)
        self.assertEqual(context['code_facts']['files'], 1)
        self.assertTrue(context['summary'])

    def test_profile_rebuilds_when_score_changes(self):
        first = capability_service.view_model(self.student)
        self.assertEqual(first['bloom'][2]['score'], 30.0)
        question = self.entry.questions.get()
        question.score = 10
        question.save(update_fields=['score'])
        second = capability_service.view_model(self.student)
        self.assertEqual(second['bloom'][2]['score'], 100.0)

    def test_refresh_uses_llm_diagnosis(self):
        UserLLMConfig.objects.create(
            user=self.student,
            provider='deepseek',
            base_url='https://api.deepseek.com',
            model='deepseek-chat',
            api_key='sk-test',
        )
        text = json.dumps(
            {
                'summary': ['切片边界需要加强'],
                'observations': [
                    {
                        'dimension': 'thinking.algorithm',
                        'task_id': 'func301',
                        'line': 2,
                        'quote': 'return nums[1:]',
                        'comment': '未判断空列表',
                        'advice': '先判断长度再切片',
                    }
                ],
                'suggestion': '补两组空列表与单元素用例',
            },
            ensure_ascii=False,
        )
        with mock.patch.object(capability_service, 'chat', return_value=text):
            profile = capability_service._refresh(self.student)
        self.assertEqual(profile.source, 'llm')
        self.assertEqual(profile.model, 'deepseek-chat')
        self.assertEqual(profile.payload['meta']['diagnosis'], 'llm')
        self.assertEqual(profile.payload['summary'], ['切片边界需要加强'])
        self.assertEqual(profile.payload['observations'][0]['line'], 2)

    def test_refresh_falls_back_when_llm_invalid(self):
        UserLLMConfig.objects.create(
            user=self.student,
            provider='deepseek',
            base_url='https://api.deepseek.com',
            model='deepseek-chat',
            api_key='sk-test',
        )
        with mock.patch.object(capability_service, 'chat', return_value='不是 JSON'):
            profile = capability_service._refresh(self.student)
        self.assertEqual(profile.source, 'rule')
        self.assertEqual(profile.model, '')
        self.assertTrue(profile.payload['summary'])

    def test_no_report_returns_empty_state(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('practice'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '综合能力分析')
        self.assertContains(response, '完成一次机器批阅作业后')

    def test_practice_page_renders_capability_module(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('practice'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('综合能力分析', body)
        self.assertIn('布鲁姆认知水平', body)
        self.assertIn('计算思维水平', body)
        self.assertIn('规则诊断（未使用大模型）', body)
        self.assertIn('覆盖 100% 分值', body)
        self.assertIn('data-radar', body)
        # 来源做成标题旁的状态徽标，任务数/更新时间放在底部信息条
        self.assertIn('capability-source', body)
        self.assertIn('capability-foot-stats', body)
        # 训练题智能体改为区块标题，弱项达成率带进度条
        self.assertIn('agent-intro', body)
        self.assertIn('rate-cell', body)
        self.assertTrue(StudentCapabilityProfile.objects.filter(student=self.student).exists())
        # 综合能力卡片位于知识点画像之前
        self.assertLess(body.index('综合能力分析'), body.index('知识点画像'))
