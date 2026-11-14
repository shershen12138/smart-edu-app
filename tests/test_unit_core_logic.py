# -*- coding: utf-8 -*-
"""任务 1：核心逻辑单元测试（无 DB、无 LLM、无 Docker 依赖）。

被测核心逻辑：
- school/portal/knowledge_profile.py —— 弱项画像统计（纯数据计算）
- school/portal/practice_agent.py    —— 练习题目解析与结果格式化
- school/portal/question_bank.py     —— 题库用例清洗与返回值打包
"""
import json

from django.test import TestCase

from school.portal import knowledge_profile, practice_agent, question_bank


class WeakKeywordsTests(TestCase):
    """弱项名称拆分成题库检索关键词（knowledge_profile.weak_keywords）。"""

    def test_plain_name_single_token(self):
        self.assertEqual(knowledge_profile.weak_keywords('列表切片'), ['列表切片'])

    def test_split_on_separators_and_lower(self):
        self.assertEqual(
            knowledge_profile.weak_keywords('For 循环/遍历'),
            ['for', '循环', '遍历'],
        )

    def test_stopwords_removed(self):
        """独立成词的停用词（被分隔符隔开）会被过滤。"""
        self.assertEqual(knowledge_profile.weak_keywords('列表切片 相关'), ['列表切片'])
        self.assertEqual(knowledge_profile.weak_keywords('切片 练习 应用'), ['切片'])

    def test_strip_connector_chars_at_token_edges(self):
        """连接词仅在 token 边缘去除，不会在词中间拆分。"""
        self.assertEqual(knowledge_profile.weak_keywords('和的遍历'), ['遍历'])
        self.assertEqual(knowledge_profile.weak_keywords('切片与遍历'), ['切片与遍历'])

    def test_empty_name(self):
        self.assertEqual(knowledge_profile.weak_keywords(''), [])


class WeakPointsTests(TestCase):
    """画像 dict → 弱项/掌握知识点划分（knowledge_profile.weak_points 等）。"""

    PROFILE = {
        '列表切片': {'earned': 40.0, 'total': 100, 'attempts': 1},
        '字典操作': {'earned': 90.0, 'total': 100, 'attempts': 2},
        '未作答': {'earned': 0.0, 'total': 0, 'attempts': 0},
    }

    def test_weak_points_sorted_by_rate(self):
        weak = knowledge_profile.weak_points(self.PROFILE)
        self.assertEqual([p['name'] for p in weak], ['列表切片'])
        self.assertAlmostEqual(weak[0]['rate'], 0.4)

    def test_mastered_points_excluded_from_weak(self):
        mastered = knowledge_profile.mastered_points(self.PROFILE)
        self.assertEqual([p['name'] for p in mastered], ['字典操作'])
        self.assertNotIn(
            '字典操作', [p['name'] for p in knowledge_profile.weak_points(self.PROFILE)]
        )

    def test_zero_attempts_never_weak(self):
        self.assertEqual(knowledge_profile.weak_points({'未作答': self.PROFILE['未作答']}), [])

    def test_empty_profile(self):
        self.assertEqual(knowledge_profile.weak_points({}), [])
        self.assertEqual(knowledge_profile.mastered_points({}), [])

    def test_threshold_boundary_split(self):
        profile = {
            '刚好及格': {'earned': 60.0, 'total': 100, 'attempts': 1},
            '差一点': {'earned': 59.9, 'total': 100, 'attempts': 1},
        }
        self.assertEqual([p['name'] for p in knowledge_profile.mastered_points(profile)], ['刚好及格'])
        self.assertEqual([p['name'] for p in knowledge_profile.weak_points(profile)], ['差一点'])


class WeakThresholdTests(TestCase):
    """弱项阈值配置解析与钳制（knowledge_profile.weak_threshold）。"""

    def test_default_value(self):
        self.assertEqual(knowledge_profile.weak_threshold(), 0.6)

    def test_configured_value_used(self):
        with self.settings(PRACTICE_WEAK_THRESHOLD='0.75'):
            self.assertEqual(knowledge_profile.weak_threshold(), 0.75)

    def test_invalid_value_falls_back(self):
        with self.settings(PRACTICE_WEAK_THRESHOLD='not-a-number'):
            self.assertEqual(knowledge_profile.weak_threshold(), 0.6)
        with self.settings(PRACTICE_WEAK_THRESHOLD=None):
            self.assertEqual(knowledge_profile.weak_threshold(), 0.6)

    def test_value_clamped_into_unit_interval(self):
        with self.settings(PRACTICE_WEAK_THRESHOLD=1.5):
            self.assertEqual(knowledge_profile.weak_threshold(), 1.0)
        with self.settings(PRACTICE_WEAK_THRESHOLD=-0.2):
            self.assertEqual(knowledge_profile.weak_threshold(), 0.0)


class FormatValueTests(TestCase):
    """函数式题返回值还原（practice_agent.format_value）。"""

    def test_packed_list(self):
        packed = '{"type": "list", "items": [{"type": "int", "value": 1}]}'
        self.assertEqual(practice_agent.format_value(packed), '[1]')

    def test_plain_text_passthrough(self):
        self.assertEqual(practice_agent.format_value('plain output'), 'plain output')

    def test_empty_string(self):
        self.assertEqual(practice_agent.format_value(''), '')

    def test_invalid_json_passthrough(self):
        self.assertEqual(practice_agent.format_value('{not json'), '{not json')

    def test_scalar_types(self):
        self.assertEqual(practice_agent.format_value('{"type": "none"}'), 'None')
        self.assertEqual(practice_agent.format_value('{"type": "bool", "value": true}'), 'True')
        self.assertEqual(practice_agent.format_value('{"type": "int", "value": 42}'), '42')
        self.assertEqual(practice_agent.format_value('{"type": "str", "value": "hi"}'), "'hi'")

    def test_nested_tuple(self):
        packed = '{"type": "tuple", "items": [{"type": "int", "value": 1}, {"type": "str", "value": "a"}]}'
        self.assertEqual(practice_agent.format_value(packed), "(1, 'a')")


class ParsePracticeTests(TestCase):
    """大模型输出 → 训练题结构（practice_agent.parse_practice）。"""

    def _question(self, **overrides):
        question = {
            'knowledge_point': '列表切片',
            'title': '区间裁剪',
            'statement': '输出切片结果',
            'difficulty': '基础',
            'template_code': 'def main():\n    ...',
            'reference_code': 'print("ok")',
            'explanation': '思路',
            'test_cases': [
                {'input': '1 2 3 4 5', 'output': '2 3 4', 'is_sample': True},
            ],
        }
        question.update(overrides)
        return question

    def _payload(self, **overrides):
        return {'questions': [self._question(**overrides)]}

    def _dump(self, payload):
        return json.dumps(payload, ensure_ascii=False)

    def test_valid_fenced_json_parsed(self):
        text = '```json\n' + self._dump(self._payload()) + '\n```'
        questions = practice_agent.parse_practice(text, ['列表切片'])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['title'], '区间裁剪')
        self.assertEqual(questions[0]['cases'][0]['input'], '1 2 3 4 5')

    def test_bare_json_parsed(self):
        questions = practice_agent.parse_practice(self._dump(self._payload()), ['列表切片'])
        self.assertEqual(len(questions), 1)

    def test_question_off_weak_point_dropped(self):
        """偏离弱项的题被丢弃，其余有效题保留。"""
        payload = {
            'questions': [self._question(knowledge_point='字典操作'), self._question(title='有效题')]
        }
        questions = practice_agent.parse_practice(self._dump(payload), ['列表切片'])
        self.assertEqual([q['title'] for q in questions], ['有效题'])

    def test_missing_fields_dropped(self):
        for field in ('title', 'statement'):
            broken = self._question()
            broken.pop(field)
            questions = practice_agent.parse_practice(
                self._dump({'questions': [broken, self._question(title='ok')]}),
                ['列表切片'],
            )
            self.assertEqual([q['title'] for q in questions], ['ok'], f'缺少 {field} 的题应被丢弃')

    def test_question_without_cases_dropped(self):
        payload = {
            'questions': [self._question(test_cases=[]), self._question(title='有效题')]
        }
        questions = practice_agent.parse_practice(self._dump(payload), ['列表切片'])
        self.assertEqual([q['title'] for q in questions], ['有效题'])

    def test_invalid_difficulty_defaults_advanced(self):
        payload = self._payload(difficulty='地狱')
        questions = practice_agent.parse_practice(self._dump(payload), ['列表切片'])
        self.assertEqual(questions[0]['difficulty'], '进阶')

    def test_null_text_fields_treated_as_missing(self):
        """回归：JSON null 的 title/statement 不得变成字面量 'None' 混过校验。"""
        questions = practice_agent.parse_practice(
            self._dump({
                'questions': [
                    self._question(title=None, statement=None),
                    self._question(title='有效题'),
                ]
            }),
            ['列表切片'],
        )
        self.assertEqual([q['title'] for q in questions], ['有效题'])
        with self.assertRaises(practice_agent.PracticeParseError):
            practice_agent.parse_practice(
                self._dump({'questions': [self._question(knowledge_point=None)]}),
                ['列表切片'],
            )

    def test_at_most_two_questions_per_point(self):
        payload = {'questions': [self._question(title=f'题{i}') for i in range(5)]}
        questions = practice_agent.parse_practice(self._dump(payload), ['列表切片'])
        self.assertEqual(len(questions), practice_agent.MAX_QUESTIONS_PER_POINT)

    def test_garbage_text_raises(self):
        with self.assertRaises(practice_agent.PracticeParseError):
            practice_agent.parse_practice('这不是 JSON', ['列表切片'])

    def test_no_usable_question_raises(self):
        payload = self._payload(knowledge_point='字典操作')
        with self.assertRaises(practice_agent.PracticeParseError):
            practice_agent.parse_practice(self._dump(payload), ['列表切片'])


class QuestionBankHelpersTests(TestCase):
    """题库用例清洗与返回值打包（question_bank）。"""

    def test_clean_cell_strips_backticks_and_restores_newlines(self):
        self.assertEqual(question_bank._clean_cell('  `hello`  '), 'hello')
        self.assertEqual(question_bank._clean_cell('a<br>b'), 'a\nb')
        self.assertEqual(question_bank._clean_cell("'a'"), "'a'")

    def test_parse_signature(self):
        self.assertEqual(question_bank._parse_signature('def solve(nums):'), ('solve', 1))
        self.assertEqual(question_bank._parse_signature('def solve(a, b):'), ('solve', 2))
        self.assertEqual(question_bank._parse_signature('not a def'), ('', 1))

    def test_pack_value_scalars_and_containers(self):
        self.assertEqual(question_bank.pack_value(None), {'type': 'none'})
        self.assertEqual(question_bank.pack_value(True), {'type': 'bool', 'value': True})
        self.assertEqual(question_bank.pack_value(7), {'type': 'int', 'value': 7})
        self.assertEqual(
            question_bank.pack_value([1, 'a']),
            {'type': 'list', 'items': [{'type': 'int', 'value': 1}, {'type': 'str', 'value': 'a'}]},
        )

    def test_pack_tuple_roundtrip_through_format_value(self):
        packed = question_bank._expected_packed('(1, 2, 3)')
        self.assertEqual(practice_agent.format_value(packed), '(1, 2, 3)')
