"""题目分析智能体（rubric_agent）的单元测试：全部外部调用都 mock。"""

import io
import json
import urllib.error
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from school.course_models import Coursework, CourseworkItem, CourseworkRubric
from school.models import Classroom, User, UserRole
from school.portal import rubric_agent


def full_markdown():
    return '## 一、作业考察的知识点\n\n## 二、5 分制量表\n\n## 三、主能力（雷达图维度）\n'


def valid_llm_payload(markdown=None):
    """构造一次合法的大模型返回。"""
    return json.dumps(
        {
            'knowledge_points': [
                {'name': '列表切片', 'detail': '掌握 1 起始计数', 'tasks': ['func301']},
            ],
            'dimensions': [
                {
                    'key': 'syntax',
                    'weight': 50,
                    'five': '完全正确',
                    'four': '小错',
                    'three': '部分正确',
                    'two': '多数错误',
                    'one': '未实现',
                },
                {'key': 'logic', 'weight': 50},
                {'key': 'boundary', 'weight': 0},
                {'key': 'knowledge', 'weight': 0},
                {'key': 'readability', 'weight': 0},
                {'key': 'structure', 'weight': 0},
            ],
            'abilities': [
                {
                    'label': f'能力{index}',
                    'detail': '说明',
                    'dimension': key,
                    'points': ['列表切片'],
                }
                for index, key in enumerate(
                    ['syntax', 'logic', 'boundary', 'knowledge', 'structure', 'readability']
                )
            ],
            'markdown': full_markdown() if markdown is None else markdown,
        },
        ensure_ascii=False,
    )


class RubricAgentTestCase(TestCase):
    def setUp(self):
        teacher = User.objects.create_user(
            username='t', password='SafePassword_2026', full_name='教师', must_change_password=False
        )
        UserRole.objects.create(user=teacher, role='teacher')
        self.classroom = Classroom.objects.create(
            code='RM', name='智能体班', course_name='Python', term='2026'
        )
        self.work = Coursework.objects.create(
            classroom=self.classroom,
            owner=teacher,
            title='列表作业',
            description='实现 func301',
            grading_mode='automatic',
            opens_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        CourseworkItem.objects.create(
            coursework=self.work, function_name='func301', title='合并两个列表', points=100
        )


class StatusAndContextTests(RubricAgentTestCase):
    def test_status_configured_and_unconfigured(self):
        self.assertIn('未配置', rubric_agent.llm_status())
        with override_settings(
            LLM_BASE_URL='https://example.com/v1',
            LLM_API_KEY='sk-test',
            LLM_MODEL='test-model',
        ):
            self.assertIn('test-model', rubric_agent.llm_status())
            self.assertTrue(rubric_agent.llm_configured())

    def test_coursework_context_shape(self):
        context = rubric_agent.coursework_context(self.work)
        self.assertEqual(context['title'], '列表作业')
        self.assertEqual(context['items'][0]['function'], 'func301')
        self.assertEqual(context['items'][0]['points'], 100)

    def test_build_messages_contains_schema_and_dimensions(self):
        messages = rubric_agent.build_messages(rubric_agent.coursework_context(self.work))
        self.assertEqual(messages[0]['role'], 'system')
        self.assertIn('JSON', messages[1]['content'])
        self.assertIn('syntax', messages[1]['content'])
        self.assertIn('func301', messages[1]['content'])


class ChatTests(RubricAgentTestCase):
    def test_not_configured_raises(self):
        with self.assertRaises(rubric_agent.LLMNotConfigured):
            rubric_agent.chat([{'role': 'user', 'content': 'x'}])

    def _configured(self):
        return override_settings(
            LLM_BASE_URL='https://example.com/v1',
            LLM_API_KEY='sk-test',
            LLM_MODEL='test-model',
            LLM_TIMEOUT=5,
        )

    def test_success_returns_content(self):
        response = io.BytesIO(
            json.dumps({'choices': [{'message': {'content': '你好'}}]}).encode()
        )
        with self._configured(), mock.patch(
            'urllib.request.urlopen', return_value=response
        ) as urlopen:
            self.assertEqual(rubric_agent.chat([{'role': 'user', 'content': 'x'}]), '你好')
        request = urlopen.call_args.args[0]
        self.assertIn('Authorization', request.headers)
        self.assertTrue(request.full_url.endswith('/chat/completions'))

    def test_base_url_may_include_path(self):
        response = io.BytesIO(
            json.dumps({'choices': [{'message': {'content': 'ok'}}]}).encode()
        )
        with override_settings(
            LLM_BASE_URL='https://example.com/v1/chat/completions',
            LLM_API_KEY='k',
            LLM_MODEL='m',
            LLM_TIMEOUT=5,
        ), mock.patch('urllib.request.urlopen', return_value=response):
            self.assertEqual(
                rubric_agent.chat([{'role': 'user', 'content': 'x'}]), 'ok'
            )

    def test_http_error_wrapped(self):
        error = urllib.error.HTTPError(
            'https://example.com', 502, 'Bad Gateway', {}, io.BytesIO(b'upstream down')
        )
        with self._configured(), mock.patch(
            'urllib.request.urlopen', side_effect=error
        ):
            with self.assertRaisesMessage(rubric_agent.LLMError, 'HTTP 502'):
                rubric_agent.chat([{'role': 'user', 'content': 'x'}])

    def test_connection_error_wrapped(self):
        with self._configured(), mock.patch(
            'urllib.request.urlopen', side_effect=urllib.error.URLError('refused')
        ):
            with self.assertRaisesMessage(rubric_agent.LLMError, '无法连接'):
                rubric_agent.chat([{'role': 'user', 'content': 'x'}])

    def test_unexpected_payload_format(self):
        response = io.BytesIO(b'{"error": "no choices"}')
        with self._configured(), mock.patch(
            'urllib.request.urlopen', return_value=response
        ):
            with self.assertRaisesMessage(rubric_agent.LLMError, '返回格式'):
                rubric_agent.chat([{'role': 'user', 'content': 'x'}])


class ExtractJsonTests(TestCase):
    def test_fenced_block(self):
        text = '前置说明```json\n{"a": 1}\n```\n后置'
        self.assertEqual(rubric_agent._extract_json(text), '{"a": 1}')

    def test_plain_object(self):
        self.assertEqual(rubric_agent._extract_json('x {"a": 1} y'), '{"a": 1}')

    def test_missing_raises(self):
        with self.assertRaisesMessage(rubric_agent.RubricParseError, '没有找到 JSON'):
            rubric_agent._extract_json('没有对象')


class NormalizeDimensionsTests(TestCase):
    def base_dimension(self, key='syntax', **kwargs):
        return {'key': key, 'weight': 10, **kwargs}

    def test_non_list_raises(self):
        with self.assertRaisesMessage(rubric_agent.RubricParseError, '数组'):
            rubric_agent.normalize_dimensions({'key': 'syntax'})

    def test_fewer_than_five_raises(self):
        raw = [self.base_dimension(key=k) for k in ['syntax', 'logic', 'boundary', 'readability']]
        with self.assertRaisesMessage(rubric_agent.RubricParseError, '至少需要 5 个'):
            rubric_agent.normalize_dimensions(raw)

    def test_unknown_and_duplicate_keys_dropped(self):
        raw = [
            self.base_dimension(key='syntax'),
            self.base_dimension(key='syntax'),
            self.base_dimension(key='unknown'),
            self.base_dimension(key='logic'),
            self.base_dimension(key='boundary'),
            self.base_dimension(key='knowledge'),
            self.base_dimension(key='readability'),
        ]
        result = rubric_agent.normalize_dimensions(raw)
        self.assertEqual([item['key'] for item in result][:2], ['syntax', 'logic'])
        self.assertEqual(len(result), 5)

    def test_non_positive_weight_uses_default(self):
        raw = [self.base_dimension(key=k, weight=0) for k in rubric_agent.DIMENSION_POOL]
        result = rubric_agent.normalize_dimensions(raw)
        self.assertEqual(len(result), 6)
        for item in result:
            self.assertEqual(item['weight'], rubric_agent.DEFAULT_WEIGHTS[item['key']])

    def test_missing_levels_use_table_text(self):
        raw = [self.base_dimension(key=k) for k in rubric_agent.DIMENSION_POOL]
        result = rubric_agent.normalize_dimensions(raw)
        for item in result:
            self.assertEqual(len(item['levels']), 5)

    def test_weights_normalized_to_100(self):
        raw = [self.base_dimension(key=k, weight=25) for k in rubric_agent.DIMENSION_POOL]
        result = rubric_agent.normalize_dimensions(raw)
        total = sum(item['weight'] for item in result)
        # 各项按比例换算后四舍五入到 1 位小数，总和允许 ±0.5 的舍入误差
        self.assertAlmostEqual(total, 100.0, delta=0.5)

    def test_caps_at_six(self):
        keys = list(rubric_agent.DIMENSION_POOL) + ['extra']
        raw = [self.base_dimension(key=key) for key in keys if key in rubric_agent.DIMENSION_POOL]
        result = rubric_agent.normalize_dimensions(raw)
        self.assertEqual(len(result), 6)

    def test_non_dict_items_skipped(self):
        raw = [None, 'x', *[]]
        raw = [None, 'x'] + [self.base_dimension(key=k) for k in list(rubric_agent.DIMENSION_POOL)[:5]]
        result = rubric_agent.normalize_dimensions(raw)
        self.assertEqual(len(result), 5)


class NormalizePointsTests(TestCase):
    def test_non_list_returns_empty(self):
        self.assertEqual(rubric_agent.normalize_points('x'), [])

    def test_filters_invalid_entries(self):
        result = rubric_agent.normalize_points(
            [
                {'name': '列表切片', 'detail': 'd', 'tasks': ['func301', ' ', 'func302']},
                {'name': '  '},
                'not-a-dict',
                {},
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['tasks'], ['func301', 'func302'])

    def test_caps_at_twenty(self):
        result = rubric_agent.normalize_points(
            [{'name': f'点{i}'} for i in range(25)]
        )
        self.assertEqual(len(result), 20)


class AbilitiesTests(TestCase):
    def points(self):
        return [
            {'name': '列表切片', 'detail': '切片语法'},
            {'name': 'for 循环遍历', 'detail': '迭代'},
            {'name': '字符串格式化', 'detail': 'f-string'},
            {'name': '集合去重', 'detail': 'set'},
            {'name': '排序函数', 'detail': 'sorted'},
            {'name': '函数参数', 'detail': 'def'},
        ]

    def test_rule_abilities_covers_six_axes(self):
        abilities = rubric_agent.rule_abilities(self.points())
        self.assertEqual(len(abilities), 6)
        dimensions = {ability['dimension'] for ability in abilities}
        self.assertEqual(len(dimensions), 6)

    def test_normalize_abilities_non_list_falls_back(self):
        result = rubric_agent.normalize_abilities(None, self.points())
        self.assertEqual(len(result), 6)

    def test_normalize_abilities_fewer_than_six_falls_back(self):
        raw = [
            {'label': '切片', 'detail': 'd', 'dimension': 'syntax', 'points': ['列表切片']}
        ]
        result = rubric_agent.normalize_abilities(raw, self.points())
        self.assertEqual(len(result), 6)

    def test_normalize_abilities_accepts_six(self):
        keys = ['syntax', 'logic', 'boundary', 'knowledge', 'structure', 'readability']
        raw = [
            {'label': f'能力{i}', 'detail': 'd', 'dimension': key, 'points': ['a', '', 'b']}
            for i, key in enumerate(keys)
        ]
        result = rubric_agent.normalize_abilities(raw, self.points())
        self.assertEqual(len(result), 6)
        self.assertEqual(result[0]['points'], ['a', 'b'])

    def test_normalize_abilities_duplicate_dimensions_skipped(self):
        keys = ['syntax', 'syntax', 'logic', 'boundary', 'knowledge', 'structure', 'readability']
        raw = [
            {'label': f'能力{i}', 'detail': 'd', 'dimension': key, 'points': []}
            for i, key in enumerate(keys)
        ]
        result = rubric_agent.normalize_abilities(raw, self.points())
        self.assertEqual(len(result), 6)


class ParseResponseTests(TestCase):
    def context(self):
        return {
            'title': '列表作业',
            'grading_mode': '机器批阅',
            'items': [{'function': 'func301', 'title': '合并', 'points': 100}],
        }

    def test_valid_payload_passthrough(self):
        result = rubric_agent.parse_response(valid_llm_payload(), self.context())
        self.assertEqual(result['points'][0]['name'], '列表切片')
        self.assertEqual(len(result['dimensions']), 6)
        self.assertIn('5 分制量表', result['markdown'])

    def test_missing_sections_rerendered(self):
        payload = json.loads(valid_llm_payload())
        payload['markdown'] = '随便写点'
        result = rubric_agent.parse_response(json.dumps(payload, ensure_ascii=False), self.context())
        self.assertIn('5 分制量表', result['markdown'])

    def test_no_points_rejected(self):
        payload = json.loads(valid_llm_payload())
        payload['knowledge_points'] = []
        with self.assertRaisesMessage(rubric_agent.RubricParseError, '没有给出任何知识点'):
            rubric_agent.parse_response(json.dumps(payload), self.context())

    def test_no_json_rejected(self):
        with self.assertRaises(rubric_agent.RubricParseError):
            rubric_agent.parse_response('完全不是 JSON', self.context())


class ReferenceAnalysisTests(RubricAgentTestCase):
    def test_reference_code_empty_without_package(self):
        self.assertEqual(rubric_agent._reference_code(self.work), '')

    def test_reference_functions_syntax_error(self):
        self.assertEqual(rubric_agent._reference_functions('def broken(:\n'), {})
        self.assertEqual(rubric_agent._reference_functions(''), {})

    def test_reference_point_tags_detects_modulo(self):
        functions = rubric_agent._reference_functions(
            'def func401(x):\n    return x % 2 == 0\n'
        )
        tags = rubric_agent._reference_point_tags(functions, 'func401')
        self.assertIn('modulo', tags)
        self.assertEqual(rubric_agent._reference_point_tags(functions, 'ghost'), [])

    def test_rule_based_uses_course_spec(self):
        context = rubric_agent.coursework_context(self.work)
        result = rubric_agent.rule_based(context)
        names = {point['name'] for point in result['points']}
        self.assertIn('列表合并（+ / extend）', names)
        self.assertIn('切片与 1 起始计数换算', names)
        self.assertEqual(len(result['dimensions']), 6)
        self.assertIn('# 列表作业 · 评分标准', result['markdown'])

    def test_rule_based_infers_from_reference(self):
        context = {
            'title': '自命题',
            'grading_mode': '机器批阅',
            'items': [
                {'function': 'func801', 'title': '判断奇偶', 'points': 10},
            ],
        }
        reference = 'def func801(x):\n    return x % 2 == 0\n'
        result = rubric_agent.rule_based(context, reference_code=reference)
        names = {point['name'] for point in result['points']}
        self.assertIn('取余 %', names)

    def test_rule_based_falls_back_to_generic(self):
        context = {
            'title': '自命题',
            'grading_mode': '机器批阅',
            'items': [{'function': 'func802', 'title': '自命题题', 'points': 10}],
        }
        result = rubric_agent.rule_based(context, reference_code='')
        self.assertEqual(result['points'][0]['name'], '通用程序设计')


class EnsureHeadingTests(RubricAgentTestCase):
    def test_keeps_existing_h1(self):
        text = '# 已有标题\n正文'
        self.assertEqual(rubric_agent.ensure_heading(text, {'title': 'x', 'items': []}), text + '\n')

    def test_prepends_heading(self):
        result = rubric_agent.ensure_heading(
            '## 一、作业考察的知识点',
            {'title': '列表作业', 'items': [1], 'grading_mode': '机器批阅'},
        )
        self.assertTrue(result.startswith('# 列表作业 · 评分标准'))
        self.assertIn('题量：1 题', result)


class GenerateForTests(RubricAgentTestCase):
    def test_existing_rubric_reused_without_force(self):
        CourseworkRubric.objects.create(coursework=self.work, markdown='# 旧标准')
        rubric = rubric_agent.generate_for(self.work, force=False)
        self.assertEqual(rubric.pk, CourseworkRubric.objects.get(coursework=self.work).pk)

    def test_empty_items_rejected(self):
        CourseworkItem.objects.all().delete()
        with self.assertRaisesMessage(rubric_agent.RubricParseError, '还没有题目清单'):
            rubric_agent.generate_for(self.work)

    def test_offline_generates_rule_rubric(self):
        rubric = rubric_agent.generate_for(self.work, offline=True)
        self.assertEqual(rubric.source, 'rule')
        self.assertEqual(rubric.model, '')
        self.assertIn('列表合并', rubric.markdown)
        self.assertEqual(len(rubric.dimensions), 6)

    def test_unconfigured_llm_raises_without_offline(self):
        with self.assertRaises(rubric_agent.LLMNotConfigured):
            rubric_agent.generate_for(self.work)

    def test_llm_path_saves_model_and_markdown(self):
        with override_settings(
            LLM_BASE_URL='https://example.com/v1',
            LLM_API_KEY='k',
            LLM_MODEL='test-model',
        ), mock.patch.object(
            rubric_agent, 'chat', return_value=valid_llm_payload()
        ) as chat_mock:
            rubric = rubric_agent.generate_for(self.work)
        chat_mock.assert_called_once()
        self.assertEqual(rubric.source, 'llm')
        self.assertEqual(rubric.model, 'test-model')
        # 知识点来自结构化字段，markdown 保留模型输出并补了一级标题
        self.assertEqual(rubric.knowledge_points[0]['name'], '列表切片')
        self.assertTrue(rubric.markdown.startswith('# 列表作业'))


class GenerateAbilitiesTests(RubricAgentTestCase):
    def _rubric(self, points=None, dimensions=None):
        return CourseworkRubric.objects.create(
            coursework=self.work,
            markdown='# 评分标准',
            knowledge_points=points if points is not None else [{'name': '列表切片'}],
            dimensions=dimensions if dimensions is not None else [],
        )

    def test_requires_rubric(self):
        with self.assertRaisesMessage(rubric_agent.RubricParseError, '还没有评分标准'):
            rubric_agent.generate_abilities(self.work)

    def test_requires_points(self):
        self._rubric(points=[])
        with self.assertRaisesMessage(rubric_agent.RubricParseError, '没有知识点'):
            rubric_agent.generate_abilities(self.work)

    def test_offline_uses_rules(self):
        self._rubric()
        abilities = rubric_agent.generate_abilities(self.work, offline=True)
        self.assertEqual(len(abilities), 6)
        self.work.refresh_from_db()
        self.assertEqual(self.work.rubric.abilities, abilities)

    def test_llm_path_uses_allowed_dimensions(self):
        dimensions = [{'key': key} for key in list(rubric_agent.DIMENSION_POOL)[:3]]
        self._rubric(dimensions=dimensions)
        keys = list(rubric_agent.DIMENSION_POOL)
        payload = json.dumps(
            {
                'abilities': [
                    {'label': f'能力{i}', 'detail': 'd', 'dimension': key, 'points': []}
                    for i, key in enumerate(keys)
                ]
            },
            ensure_ascii=False,
        )
        with override_settings(
            LLM_BASE_URL='https://example.com/v1',
            LLM_API_KEY='k',
            LLM_MODEL='m',
        ), mock.patch.object(rubric_agent, 'chat', return_value=payload) as chat_mock:
            abilities = rubric_agent.generate_abilities(self.work)
        chat_mock.assert_called_once()
        self.assertEqual(len(abilities), 6)
        self.assertTrue(all(a['dimension'] in keys for a in abilities))

    def test_llm_invalid_response_raises(self):
        # generate_abilities 不吞解析错误：无 JSON 时直接抛给调用方
        self._rubric()
        with override_settings(
            LLM_BASE_URL='https://example.com/v1',
            LLM_API_KEY='k',
            LLM_MODEL='m',
        ), mock.patch.object(rubric_agent, 'chat', return_value='不是 JSON'):
            with self.assertRaises(rubric_agent.RubricParseError):
                rubric_agent.generate_abilities(self.work)

    def test_build_ability_messages_lists_dimensions(self):
        messages = rubric_agent.build_ability_messages(
            {'title': '作业'}, [{'name': '列表切片'}], ['syntax', 'logic']
        )
        self.assertIn('syntax、logic', messages[1]['content'])


class RegenerationTests(RubricAgentTestCase):
    def test_regenerate_job_survives_failure(self):
        with mock.patch.object(
            rubric_agent,
            'generate_for',
            side_effect=RuntimeError('生成失败'),
        ):
            rubric_agent._regenerate_coursework_job(self.work.pk)  # 不应抛出

    def test_regenerate_job_success(self):
        with mock.patch.object(
            rubric_agent, 'generate_for'
        ) as generate, mock.patch(
            'school.portal.rubric_agent.close_old_connections'
        ) as close_old:
            rubric_agent._regenerate_coursework_job(self.work.pk)
        generate.assert_called_once()
        close_old.assert_called_once()

    def test_schedule_registers_on_commit(self):
        registered = []
        with mock.patch('django.db.transaction.on_commit', side_effect=registered.append):
            rubric_agent.schedule_regeneration(1)
        self.assertEqual(len(registered), 1)
