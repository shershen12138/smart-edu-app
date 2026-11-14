# -*- coding: utf-8 -*-
"""任务 2：等价类划分 + 边界值分析设计的测试用例。

选定输入字段：`_normalize_cases(raw)` 的输入 —— 训练题的评测用例列表
（模型生成的 test_cases，清洗后存库并参与机器批阅计分），
以及派生输入字段 `weak_threshold()` 的阈值配置。

设计依据见 tests/TEST_PLAN.md 中的等价类表与边界值表。
"""
from django.test import TestCase, override_settings

from school.portal import knowledge_profile, practice_agent


def case(input_text='1 2 3', output_text='2 3', is_sample=False):
    return {'input': input_text, 'output': output_text, 'is_sample': is_sample}


class NormalizeCasesEquivalenceClassTests(TestCase):
    """等价类划分：_normalize_cases 的输入域。"""

    EC_ID = 'EC'

    def test_ec1_valid_case_kept(self):
        """EC1 有效用例（input、output 均非空）：原样保留。"""
        result = practice_agent._normalize_cases([case()])
        self.assertEqual(result, [{'input': '1 2 3', 'output': '2 3', 'is_sample': False}])

    def test_ec2_missing_input_dropped(self):
        """EC2 缺少 input 的用例：整条丢弃。"""
        self.assertEqual(practice_agent._normalize_cases([{'output': '2 3'}]), [])

    def test_ec3_missing_output_dropped(self):
        """EC3 缺少 output 的用例：整条丢弃。"""
        self.assertEqual(practice_agent._normalize_cases([{'input': '1 2 3'}]), [])

    def test_ec4_non_dict_item_dropped(self):
        """EC4 列表内非 dict 元素（字符串/数字/None）：丢弃。"""
        self.assertEqual(practice_agent._normalize_cases(['text', 42, None]), [])

    def test_ec5_non_list_input_returns_empty(self):
        """EC5 输入不是列表（None/字符串/数字/dict）：返回空列表。"""
        for raw in (None, 'text', 123, {'input': 'x'}):
            self.assertEqual(practice_agent._normalize_cases(raw), [])

    def test_ec6_empty_list_returns_empty(self):
        """EC6 空列表：返回空列表。"""
        self.assertEqual(practice_agent._normalize_cases([]), [])

    def test_ec7_is_sample_truthiness_normalized(self):
        """EC7 is_sample 任意真值：统一归一为 bool。"""
        self.assertTrue(practice_agent._normalize_cases([case(is_sample=1)])[0]['is_sample'])
        self.assertTrue(practice_agent._normalize_cases([case(is_sample='yes')])[0]['is_sample'])
        self.assertFalse(practice_agent._normalize_cases([case(is_sample='')])[0]['is_sample'])

    def test_ec8_whitespace_only_input_dropped(self):
        """EC8 input/output 仅含空白字符：视为缺失，丢弃。"""
        self.assertEqual(practice_agent._normalize_cases([case(input_text='   ')]), [])
        self.assertEqual(practice_agent._normalize_cases([case(output_text='')]), [])

    def test_ec9_null_fields_treated_as_missing(self):
        """回归：JSON null 字段不得变成字面量 'None' 混入评测用例。"""
        self.assertEqual(
            practice_agent._normalize_cases([{'input': None, 'output': '2'}]), []
        )
        self.assertEqual(
            practice_agent._normalize_cases([{'input': '1', 'output': None}]), []
        )

    def test_valid_and_invalid_items_mixed(self):
        """混合输入：无效条目被跳过，有效条目保留且顺序不变。"""
        raw = [case(input_text=''), 'junk', case(), {'output': None}]
        result = practice_agent._normalize_cases(raw)
        self.assertEqual([item['input'] for item in result], ['1 2 3'])


class NormalizeCasesBoundaryValueTests(TestCase):
    """边界值分析：用例数量上限 MAX_CASES_PER_QUESTION = 5。"""

    LIMIT = practice_agent.MAX_CASES_PER_QUESTION

    def _cases(self, count):
        return [case(input_text=str(i)) for i in range(count)]

    def test_bva_below_limit_all_kept(self):
        """BVA1：0 条（下界外）与 1 条（下界）。"""
        self.assertEqual(len(practice_agent._normalize_cases(self._cases(0))), 0)
        self.assertEqual(len(practice_agent._normalize_cases(self._cases(1))), 1)

    def test_bva_at_limit_all_kept(self):
        """BVA2：恰好 5 条（上界）：全部保留。"""
        self.assertEqual(len(practice_agent._normalize_cases(self._cases(self.LIMIT))), self.LIMIT)

    def test_bva_above_limit_truncated(self):
        """BVA3：6 条（上界外）：只保留前 5 条。"""
        result = practice_agent._normalize_cases(self._cases(self.LIMIT + 1))
        self.assertEqual(len(result), self.LIMIT)
        self.assertEqual(result[-1]['input'], str(self.LIMIT - 1))


class WeakThresholdBoundaryValueTests(TestCase):
    """边界值分析：weak_threshold 钳制区间 [0, 1]（配置 PRACTICE_WEAK_THRESHOLD）。"""

    def test_bva_lower_boundary(self):
        for value, expected in ((-0.1, 0.0), (0.0, 0.0), (0.1, 0.1)):
            with self.settings(PRACTICE_WEAK_THRESHOLD=value):
                self.assertEqual(knowledge_profile.weak_threshold(), expected)

    def test_bva_upper_boundary(self):
        for value, expected in ((0.9, 0.9), (1.0, 1.0), (1.1, 1.0)):
            with self.settings(PRACTICE_WEAK_THRESHOLD=value):
                self.assertEqual(knowledge_profile.weak_threshold(), expected)

    def test_bva_inside_interval_unchanged(self):
        with self.settings(PRACTICE_WEAK_THRESHOLD=0.6):
            self.assertEqual(knowledge_profile.weak_threshold(), 0.6)

    def test_bva_non_finite_values_fall_back(self):
        """回归：NaN/inf 配置不参与大小比较，必须回落默认值，不能静默失效。"""
        for value in ('nan', 'inf', '-inf', float('nan'), float('inf')):
            with self.settings(PRACTICE_WEAK_THRESHOLD=value):
                self.assertEqual(knowledge_profile.weak_threshold(), 0.6)


class WeakKeywordsBoundaryValueTests(TestCase):
    """边界值分析：关键词长度下界（len(token) == 1 的 token 被丢弃）。"""

    def test_bva_single_char_token_dropped(self):
        """长度 1（下界外）：丢弃。"""
        self.assertEqual(knowledge_profile.weak_keywords('a 切片'), ['切片'])

    def test_bva_two_char_token_kept(self):
        """长度 2（下界）：保留。"""
        self.assertEqual(knowledge_profile.weak_keywords('ab 切片'), ['ab', '切片'])

    def test_bva_all_single_char_tokens(self):
        """全部 token 长度为 1：结果为空。"""
        self.assertEqual(knowledge_profile.weak_keywords('a b c'), [])
