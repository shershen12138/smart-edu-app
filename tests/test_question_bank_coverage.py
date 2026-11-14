# -*- coding: utf-8 -*-
"""提高覆盖率的补充测试：question_bank 纯函数与题库选题链路。

被测：school/portal/question_bank.py（解析、打包、选题、反查）
数据源：`data/` 下的《Python题库.md》与《Python教学Tag库_v1.0.md》（只读，不改文件）。
"""
from unittest import mock

from django.test import TestCase

from school.portal import question_bank
from tools.taglib import loader as taglib


class PackValueTests(TestCase):
    """pack_value 全类型分支与非法类型。"""

    def test_float_and_complex(self):
        self.assertEqual(question_bank.pack_value(1.5), {'type': 'float', 'value': 1.5})
        self.assertEqual(
            question_bank.pack_value(1 + 2j), {'type': 'complex', 'real': 1.0, 'imag': 2.0}
        )

    def test_tuple_set_dict(self):
        self.assertEqual(
            question_bank.pack_value((1, 2)),
            {'type': 'tuple', 'items': [{'type': 'int', 'value': 1}, {'type': 'int', 'value': 2}]},
        )
        packed = question_bank.pack_value({'b', 'a'})
        self.assertEqual(packed['type'], 'set')
        items = [item['value'] for item in packed['items']]
        self.assertEqual(items, ['a', 'b'])  # set 打包后按 JSON 排序，保证确定性

        packed_dict = question_bank.pack_value({'k': [1]})
        self.assertEqual(packed_dict['type'], 'dict')
        self.assertEqual(packed_dict['items'][0][0]['value'], 'k')

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            question_bank.pack_value(object())


class ParseHelpersTests(TestCase):
    """解析辅助函数的边界行为。"""

    def test_code_block_missing(self):
        self.assertEqual(question_bank._code_block('no block here'), '')

    def test_parse_signature_edge_cases(self):
        self.assertEqual(question_bank._parse_signature('def solve():'), ('solve', 0))
        # 带默认值与 *args 之后的参数都计入
        self.assertEqual(question_bank._parse_signature('def solve(a=1, *, b):'), ('solve', 2))
        self.assertEqual(
            question_bank._parse_signature('def solve(nums, extra=None):'), ('solve', 2)
        )

    def test_expected_packed_invalid_literal(self):
        with self.assertRaises(ValueError):
            question_bank._expected_packed('not-a-literal')

    def test_parse_cases_skips_invalid_rows(self):
        lines = [
            '| 1 | `[1, 2]` | `[1, 2]` |',        # 有效
            '| 2 | `x` | `not-a-literal` |',       # 期望值非法 → 跳过
            '| 3 |  | `1` |',                      # 参数为空 → 跳过
            '不是表格行',                            # 不匹配行正则 → 跳过
            '| 4 | `[3]` | `2` |',                 # 有效
        ]
        cases = question_bank._parse_cases(lines)
        self.assertEqual(len(cases), 2)
        self.assertTrue(cases[0]['is_sample'])
        self.assertFalse(cases[1]['is_sample'])

    def test_parse_question_invalid_header(self):
        self.assertIsNone(question_bank._parse_question(['不是标题行']))

    def test_parse_question_missing_statement_or_tags(self):
        # 题号不带括号（与真实题库格式一致）
        header = '### 1、题目标题：Q9-01 测试（★☆☆｜10 分）'
        body = ['**2、题目描述', '求和', '**3、考点标签', '- `列表/切片`', '**4、作答与用例',
                '**4.1 函数框架', '```python', 'def solve(nums):', '```', '**4.2 标准答案',
                '```python', 'def solve(nums):', '    return []', '```', '**4.3 测试用例',
                '| 1 | `[1]` | `[]` |']
        # 缺题面：2 节内容为空
        self.assertIsNone(question_bank._parse_question([header, '**3、考点标签', '- `列表/切片`']))
        # 缺考点标签
        self.assertIsNone(question_bank._parse_question([header, '**2、题目描述', '求和']))
        # 完整题面可解析
        parsed = question_bank._parse_question([header] + body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['code'], 'Q9-01')
        self.assertEqual(parsed['difficulty'], '基础')


class LoadBankTests(TestCase):
    """题库文档加载：真实文件、缓存、缺文件回退。"""

    def tearDown(self):
        question_bank.load_bank.cache_clear()

    def test_real_bank_parses(self):
        bank = question_bank.load_bank()
        self.assertGreater(len(bank), 0)
        question = bank[0]
        for key in ('code', 'title', 'statement', 'tags', 'template_code', 'reference_code',
                    'function_name', 'function_argc', 'cases', 'difficulty', 'points'):
            self.assertIn(key, question)
        self.assertTrue(question['function_name'])

    def test_load_bank_is_cached(self):
        first = question_bank.load_bank()
        second = question_bank.load_bank()
        self.assertIs(first, second)

    def test_missing_bank_returns_empty(self):
        question_bank.load_bank.cache_clear()
        with mock.patch.object(question_bank, 'bank_path', return_value=question_bank.bank_path().parent / '不存在.md'):
            self.assertEqual(question_bank.load_bank(), ())

    def test_bank_size_matches(self):
        self.assertEqual(question_bank.bank_size(), len(question_bank.load_bank()))


class MatchScoreTests(TestCase):
    """弱项关键词与题目标签的相关度打分。"""

    def test_segment_hit_sums_tokens(self):
        question = {'tags': ['列表/切片']}
        self.assertEqual(question_bank._match_score(question, ['列表', '切片']), 4)

    def test_reverse_containment(self):
        question = {'tags': ['列表/切片']}
        # 整体分段 '列表切片' ⊆ token '列表切片与反转'
        self.assertEqual(question_bank._match_score(question, ['列表切片与反转']), 4)

    def test_no_match_returns_zero(self):
        question = {'tags': ['列表/切片']}
        self.assertEqual(question_bank._match_score(question, ['字典', '集合']), 0)

    def test_short_segments_ignored(self):
        """分段长度 <2 被忽略，但去掉 '/' 的整体（'ab'，长度 2）仍参与匹配。"""
        question = {'tags': ['a/b']}
        self.assertEqual(question_bank._match_score(question, ['a']), 1)
        # token 不在任何分段与整体中 → 0 分
        self.assertEqual(question_bank._match_score({'tags': ['x/y']}, ['z']), 0)


class FindQuestionsTests(TestCase):
    """按 Tag 精确命中与关键词兜底的选题链路（使用真实题库与词表）。"""

    @classmethod
    def setUpTestData(cls):
        question_bank.load_bank.cache_clear()
        cls.bank = question_bank.load_bank()

    def test_tag_intersection_exists(self):
        """题库标签与词表标准名有交集（Tag 选题的前提）。"""
        names = taglib.tag_names()
        tagged = [tag for question in self.bank for tag in question['tags'] if tag in names]
        self.assertTrue(tagged)

    def _pick_tag(self):
        names = taglib.tag_names()
        return next(tag for question in self.bank for tag in question['tags'] if tag in names)

    def test_find_questions_by_tag_returns_bank_questions(self):
        tag = self._pick_tag()
        questions = question_bank.find_questions_by_tag(tag, limit=2)
        self.assertTrue(questions)
        self.assertLessEqual(len(questions), 2)
        codes = {question['code'] for question in questions}
        # 难度递增
        ranks = [question['difficulty_rank'] for question in questions]
        self.assertEqual(ranks, sorted(ranks))

    def test_find_questions_respects_exclude(self):
        tag = self._pick_tag()
        all_hits = question_bank.find_questions_by_tag(tag, limit=5)
        if len(all_hits) < 2:
            self.skipTest('该 Tag 命中题数不足 2')
        excluded = {all_hits[0]['code']}
        rest = question_bank.find_questions_by_tag(tag, limit=5, exclude=excluded)
        self.assertNotIn(all_hits[0]['code'], {question['code'] for question in rest})

    def test_find_questions_tag_path_priority(self):
        tag = self._pick_tag()
        questions = question_bank.find_questions(tag, limit=2)
        self.assertTrue(questions)
        self.assertLessEqual(len(questions), 2)

    def test_find_questions_keyword_fallback(self):
        """关键词路径：弱项名不在词表时按关键词模糊匹配（token 取自题库标签）。"""
        question = self.bank[0]
        token = next(
            tag.split('/')[-1] for tag in question['tags']
            if len(tag.split('/')[-1]) >= 2
        )
        fake_name = f'自定义{token}考点'
        questions = question_bank.find_questions(fake_name, limit=2)
        self.assertTrue(questions)
        self.assertTrue(all('code' in item for item in questions))

    def test_find_questions_empty_keywords(self):
        # 全部 token 长度为 1 → 无关键词 → 空列表
        self.assertEqual(question_bank.find_questions('a b', limit=2), [])

    def test_has_matches(self):
        tag = self._pick_tag()
        self.assertTrue(question_bank.has_matches([{'name': tag}]))
        self.assertFalse(question_bank.has_matches([{'name': '量子纠缠可视化调试'}]))
        self.assertFalse(question_bank.has_matches([]))
