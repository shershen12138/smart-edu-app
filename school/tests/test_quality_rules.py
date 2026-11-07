"""纯函数模块的单元测试：题库语义规则、考点解析、判题结果渲染。

覆盖 tools/code_quality_agent 的 rules/specs 与 school/portal 的 result_display，
全部不依赖数据库与 Docker，可独立快速运行。
"""

import ast
import textwrap
from unittest import mock

from django.test import TestCase

from school.portal.result_display import result_text
from tools.code_quality_agent import rules, specs


def fn_of(source: str) -> ast.FunctionDef:
    """把缩进对齐的函数源码解析成 FunctionDef 节点。"""
    tree = ast.parse(textwrap.dedent(source))
    return tree.body[0]


def messages(findings: list) -> list[str]:
    return [message for _line, message, _advice, _dim in findings]


class RuleFunc301Tests(TestCase):
    def test_wrong_bounds_flagged(self):
        fn = fn_of('def func301(a, b):\n    return (a + b)[8:15]\n')
        result = rules.func301_slice_bounds(fn, set())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 2)

    def test_wrong_shifted_bounds_flagged(self):
        fn = fn_of('def func301(a, b):\n    return (a + b)[7:16]\n')
        self.assertEqual(len(rules.func301_slice_bounds(fn, set())), 1)

    def test_correct_bounds_not_flagged(self):
        fn = fn_of('def func301(a, b):\n    return (a + b)[7:15]\n')
        self.assertEqual(rules.func301_slice_bounds(fn, set()), [])

    def test_dynamic_slice_not_flagged(self):
        fn = fn_of('def func301(a, b):\n    return (a + b)[n - 1 : n + 7]\n')
        self.assertEqual(rules.func301_slice_bounds(fn, set()), [])


class RuleFunc302Tests(TestCase):
    def test_plus_one_index_flagged(self):
        fn = fn_of('def func302(data):\n    return data[len(data) // 2 + 1]\n')
        result = rules.func302_median(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('越界', result[0][1])

    def test_returns_larger_middle_flagged(self):
        fn = fn_of(
            '''
            def func302(data):
                n = len(data)
                if data[n // 2] > data[n // 2 - 1]:
                    return data[n // 2]
                else:
                    return data[n // 2 - 1]
            '''
        )
        result = rules.func302_median(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('较大者', result[0][1])

    def test_correct_min_middle_not_flagged(self):
        fn = fn_of(
            '''
            def func302(data):
                n = len(data)
                if data[n // 2] < data[n // 2 - 1]:
                    return data[n // 2]
                else:
                    return data[n // 2 - 1]
            '''
        )
        self.assertEqual(rules.func302_median(fn, set()), [])

    def test_if_without_else_ignored(self):
        fn = fn_of(
            '''
            def func302(data):
                if data[0] > data[1]:
                    return data[0]
                return data[1]
            '''
        )
        self.assertEqual(rules.func302_median(fn, set()), [])


class RuleFunc303Tests(TestCase):
    def test_inverted_true_branch_flagged(self):
        fn = fn_of(
            '''
            def func303(items):
                if items == items[::-1]:
                    return 0
                else:
                    return 1
            '''
        )
        result = rules.func303_palindrome(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('应返回 1', result[0][1])

    def test_inverted_false_branch_flagged(self):
        fn = fn_of(
            '''
            def func303(items):
                if items[::-1] == items:
                    return len(items)
                else:
                    return 1
            '''
        )
        result = rules.func303_palindrome(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('应返回 0', result[0][1])

    def test_correct_semantics_not_flagged(self):
        fn = fn_of(
            '''
            def func303(items):
                if items == items[::-1]:
                    return 1
                else:
                    return 0
            '''
        )
        self.assertEqual(rules.func303_palindrome(fn, set()), [])

    def test_if_without_slice_reverse_ignored(self):
        fn = fn_of(
            '''
            def func303(items):
                if items[0] == 0:
                    return 0
                else:
                    return 1
            '''
        )
        self.assertEqual(rules.func303_palindrome(fn, set()), [])


class RuleFunc305Tests(TestCase):
    def test_type_str_equality_flagged(self):
        fn = fn_of('def func305(items):\n    return [x for x in items if type(x) == str]\n')
        result = rules.func305_int_filter(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('相反', result[0][1])

    def test_isinstance_str_flagged(self):
        fn = fn_of('def func305(items):\n    return [x for x in items if isinstance(x, str) == True]\n')
        self.assertEqual(len(rules.func305_int_filter(fn, set())), 1)

    def test_isinstance_int_not_flagged(self):
        fn = fn_of('def func305(items):\n    return [x for x in items if isinstance(x, int)]\n')
        self.assertEqual(rules.func305_int_filter(fn, set()), [])

    def test_type_int_not_flagged(self):
        fn = fn_of('def func305(items):\n    return [x for x in items if type(x) == int]\n')
        self.assertEqual(rules.func305_int_filter(fn, set()), [])

    def test_non_type_comparison_ignored(self):
        fn = fn_of('def func305(items):\n    return [x for x in items if x == 3]\n')
        self.assertEqual(rules.func305_int_filter(fn, set()), [])


class RuleFunc308Tests(TestCase):
    def test_gt_returning_3_flagged(self):
        fn = fn_of(
            '''
            def func308(text):
                even = text.count('a')
                odd = text.count('b')
                if even > odd:
                    return 3
                elif even < odd:
                    return 3
                return 1
            '''
        )
        result = rules.func308_return_codes(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('应返回 2', result[0][1])

    def test_lt_returning_2_flagged(self):
        fn = fn_of(
            '''
            def func308(text):
                even = text.count('a')
                odd = text.count('b')
                if even > odd:
                    return 2
                elif even < odd:
                    return 2
                return 1
            '''
        )
        result = rules.func308_return_codes(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('应返回 3', result[0][1])

    def test_eq_returning_wrong_code_flagged(self):
        fn = fn_of(
            '''
            def func308(text):
                even = text.count('a')
                odd = text.count('b')
                if even > odd:
                    return 2
                elif even < odd:
                    return 3
                elif even == odd:
                    return 4
                return 1
            '''
        )
        result = rules.func308_return_codes(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('应返回 1', result[0][1])

    def test_correct_codes_not_flagged(self):
        fn = fn_of(
            '''
            def func308(text):
                even = text.count('a')
                odd = text.count('b')
                if even > odd:
                    return 2
                elif even < odd:
                    return 3
                return 1
            '''
        )
        self.assertEqual(rules.func308_return_codes(fn, set()), [])


class RuleFunc309Tests(TestCase):
    def test_second_key_not_negated_flagged(self):
        fn = fn_of(
            '''
            def func309(rows):
                rows.sort(key=lambda row: (row[1], row[0]), reverse=True)
                return rows
            '''
        )
        result = rules.func309_sort_key(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('学号', result[0][1])

    def test_builtin_sorted_name_call_not_flagged(self):
        # 规则只针对方法调用 rows.sort(...)；内置 sorted(...) 是 Name 调用，不在检查范围
        fn = fn_of(
            '''
            def func309(rows):
                return sorted(rows, key=lambda row: (row[1], row[0]), reverse=True)
            '''
        )
        self.assertEqual(rules.func309_sort_key(fn, set()), [])

    def test_negated_second_key_not_flagged(self):
        fn = fn_of(
            '''
            def func309(rows):
                rows.sort(key=lambda row: (row[1], -row[0]), reverse=True)
                return rows
            '''
        )
        self.assertEqual(rules.func309_sort_key(fn, set()), [])

    def test_no_reverse_not_flagged(self):
        fn = fn_of(
            '''
            def func309(rows):
                rows.sort(key=lambda row: (row[1], row[0]))
                return rows
            '''
        )
        self.assertEqual(rules.func309_sort_key(fn, set()), [])

    def test_single_key_lambda_not_flagged(self):
        fn = fn_of(
            '''
            def func309(rows):
                rows.sort(key=lambda row: row[1], reverse=True)
                return rows
            '''
        )
        self.assertEqual(rules.func309_sort_key(fn, set()), [])


class RuleFunc310Tests(TestCase):
    def test_range_without_plus_one_flagged(self):
        fn = fn_of(
            '''
            def func310(n):
                return [x for x in range(2, n)]
            '''
        )
        result = rules.func310_prime_range(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('不包含', result[0][1])

    def test_range_minus_one_flagged(self):
        fn = fn_of(
            '''
            def func310(n):
                return [x for x in range(2, n - 1)]
            '''
        )
        self.assertEqual(len(rules.func310_prime_range(fn, set())), 1)

    def test_range_with_plus_one_not_flagged(self):
        fn = fn_of(
            '''
            def func310(n):
                return [x for x in range(2, n + 1)]
            '''
        )
        self.assertEqual(rules.func310_prime_range(fn, set()), [])

    def test_three_arg_range_ignored(self):
        fn = fn_of(
            '''
            def func310(n):
                return [x for x in range(2, n, 2)]
            '''
        )
        self.assertEqual(rules.func310_prime_range(fn, set()), [])


class RuleFunc311Tests(TestCase):
    def test_missing_reverse_flagged(self):
        fn = fn_of(
            '''
            def func311(nums):
                out = []
                for value in nums:
                    part = [int(ch) for ch in str(value)]
                    out.append(part)
                return out
            '''
        )
        result = rules.func311_digit_reverse(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('没有反转', result[0][1])

    def test_iterating_subscript_flagged(self):
        fn = fn_of(
            '''
            def func311(grid):
                out = []
                for i, row in enumerate(grid):
                    out.append([int(ch) for ch in grid[i]][::-1])
                return out
            '''
        )
        result = rules.func311_digit_reverse(fn, set())
        # 直接遍历下标元素（整数）会抛 TypeError；已带 [::-1] 不再报“未反转”
        self.assertEqual(len(result), 1)
        self.assertIn('TypeError', result[0][1])

    def test_with_reverse_not_flagged(self):
        fn = fn_of(
            '''
            def func311(nums):
                out = []
                for value in nums:
                    part = [int(ch) for ch in str(value)][::-1]
                    out.append(part)
                return out
            '''
        )
        self.assertEqual(rules.func311_digit_reverse(fn, set()), [])

    def test_reversed_call_counts_as_reverse(self):
        fn = fn_of(
            '''
            def func311(nums):
                out = []
                for value in nums:
                    out.append(list(reversed([int(ch) for ch in str(value)])))
                return out
            '''
        )
        self.assertEqual(rules.func311_digit_reverse(fn, set()), [])


class RuleFunc312Tests(TestCase):
    def test_true_division_flagged(self):
        fn = fn_of('def func312(a, b):\n    return (a + b) / 2\n')
        result = rules.func312_integer_average(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('//', result[0][2])

    def test_left_two_division_flagged(self):
        fn = fn_of('def func312(a, b):\n    return 2 / (a + b)\n')
        self.assertEqual(len(rules.func312_integer_average(fn, set())), 1)

    def test_floor_division_not_flagged(self):
        fn = fn_of('def func312(a, b):\n    return (a + b) // 2\n')
        self.assertEqual(rules.func312_integer_average(fn, set()), [])

    def test_other_divisor_not_flagged(self):
        fn = fn_of('def func312(a, b):\n    return (a + b) / 3\n')
        self.assertEqual(rules.func312_integer_average(fn, set()), [])


class RuleFunc313Tests(TestCase):
    def test_extend_flagged(self):
        fn = fn_of(
            '''
            def func313(matrix):
                result = []
                for row in matrix:
                    result.extend(row)
                return result
            '''
        )
        result = rules.func313_transpose(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('一维', result[0][1])

    def test_append_not_flagged(self):
        fn = fn_of(
            '''
            def func313(matrix):
                result = []
                for row in matrix:
                    result.append(row)
                return result
            '''
        )
        self.assertEqual(rules.func313_transpose(fn, set()), [])


class RuleFunc315Tests(TestCase):
    def test_gt_direction_flagged(self):
        fn = fn_of(
            '''
            def func315(num, a):
                for i in range(len(a)):
                    if num > a[i]:
                        a.insert(i, num)
                        return a
                return a
            '''
        )
        result = rules.func315_insert_direction(fn, set())
        self.assertEqual(len(result), 1)
        self.assertIn('方向相反', result[0][1])

    def test_gte_direction_flagged(self):
        fn = fn_of(
            '''
            def func315(num, a):
                for i in range(len(a)):
                    if num >= a[i]:
                        a.insert(i, num)
                        return a
                return a
            '''
        )
        self.assertEqual(len(rules.func315_insert_direction(fn, set())), 1)

    def test_lt_direction_not_flagged(self):
        fn = fn_of(
            '''
            def func315(num, a):
                for i in range(len(a)):
                    if num < a[i]:
                        a.insert(i, num)
                        return a
                return a
            '''
        )
        self.assertEqual(rules.func315_insert_direction(fn, set()), [])

    def test_subscript_on_left_ignored(self):
        fn = fn_of(
            '''
            def func315(num, a):
                for i in range(len(a)):
                    if a[i] > num:
                        a.insert(i, num)
                        return a
                return a
            '''
        )
        self.assertEqual(rules.func315_insert_direction(fn, set()), [])


class CommonRulesTests(TestCase):
    def test_pass_only_flagged(self):
        fn = fn_of('def f(nums):\n    pass\n')
        result = rules.common_rules(fn)
        self.assertEqual(len(result), 1)
        self.assertIn('尚未实现', result[0][1])

    def test_no_return_flagged(self):
        fn = fn_of('def f(nums):\n    print(nums)\n')
        result = rules.common_rules(fn)
        self.assertEqual(len(result), 1)
        self.assertIn('return', result[0][1])

    def test_return_none_still_flagged(self):
        fn = fn_of('def f(nums):\n    total = sum(nums)\n    return\n')
        self.assertEqual(len(rules.common_rules(fn)), 1)

    def test_proper_return_not_flagged(self):
        fn = fn_of('def f(nums):\n    return sum(nums)\n')
        self.assertEqual(rules.common_rules(fn), [])


class EvaluateTaskTests(TestCase):
    def test_dispatches_registered_rule(self):
        fn = fn_of('def func301(a, b):\n    return (a + b)[8:15]\n')
        result = rules.evaluate_task('func301', fn, set())
        self.assertEqual(len(result), 1)

    def test_unknown_task_returns_empty(self):
        fn = fn_of('def f(nums):\n    return nums\n')
        self.assertEqual(rules.evaluate_task('func999', fn, set()), [])

    def test_rule_exception_swallowed(self):
        fn = fn_of('def f(nums):\n    return nums\n')
        boom = mock.Mock(side_effect=RuntimeError('boom'))
        with mock.patch.dict(rules.RULES, {'funcX': (boom,)}):
            self.assertEqual(rules.evaluate_task('funcX', fn, set()), [])

    def test_rules_registry_covers_declared_functions(self):
        expected = {
            'func301', 'func302', 'func303', 'func305', 'func308', 'func309',
            'func310', 'func311', 'func312', 'func313', 'func315',
        }
        self.assertEqual(set(rules.RULES), expected)


class NormalizeTagsTests(TestCase):
    def test_keeps_registered_in_order_and_dedupes(self):
        result = specs.normalize_tags(['slice_bounds', 'lambda', 'slice_bounds'])
        self.assertEqual(result, ('slice_bounds', 'lambda'))

    def test_drops_unregistered(self):
        result = specs.normalize_tags(['不存在的标签', 'loop'])
        self.assertEqual(result, ('loop',))

    def test_respects_limit(self):
        tags = ['loop', 'lambda', 'modulo', 'compare', 'counter', 'len', 'slice_bounds']
        self.assertEqual(len(specs.normalize_tags(tags, limit=3)), 3)

    def test_non_string_input_coerced(self):
        self.assertEqual(specs.normalize_tags([123, 'loop']), ('loop',))


class SplitProblemTextTests(TestCase):
    def test_splits_by_function_names(self):
        text = '第一题描述 将代码写入函数func401 第二题描述 将代码写入函数func402 尾部要求'
        segments = specs.split_problem_text(text)
        self.assertEqual(list(segments), ['func401', 'func402'])
        self.assertIn('第一题描述', segments['func401'])
        self.assertIn('第二题描述', segments['func402'])

    def test_empty_text_returns_empty(self):
        self.assertEqual(specs.split_problem_text(''), {})


class InferFromTextTests(TestCase):
    def test_keyword_hits(self):
        tags = specs.infer_from_text('判断输入是否为质数，用循环反复试除')
        self.assertIn('modulo', tags)
        self.assertIn('loop', tags)

    def test_no_hit_returns_empty(self):
        self.assertEqual(specs.infer_from_text('描写春天的散文'), ())

    def test_empty_segment(self):
        self.assertEqual(specs.infer_from_text(''), ())


class InferFromReferenceTests(TestCase):
    def test_detects_points_from_reference(self):
        source = 'def func401(x):\n    if x % 2 == 0:\n        return True\n    return False\n'
        found = specs.infer_from_reference(source, ['func401'])
        self.assertIn('modulo', found['func401'])
        self.assertIn('compare', found['func401'])

    def test_empty_source_returns_empty(self):
        self.assertEqual(specs.infer_from_reference('', ['func401']), {})

    def test_unparsable_source_returns_empty(self):
        self.assertEqual(specs.infer_from_reference('def broken(:\n', ['func401']), {})

    def test_helper_functions_not_reported(self):
        source = (
            'def helper(x):\n    return x % 2\n'
            'def func401(x):\n    return helper(x) == 0\n'
        )
        found = specs.infer_from_reference(source, ['func401'])
        self.assertNotIn('helper', found)
        self.assertIn('func401', found)


class ResolveSpecsTests(TestCase):
    def test_course_spec_has_top_priority(self):
        result = specs.resolve_specs(
            [('func301', '自定义标题')],
            problem_text='func301 二进制转换',
            reference_source='def func301(a):\n    return sorted(a)\n',
            points_by_function={'func301': ('loop',)},
        )
        self.assertEqual(result[0].points, ('list_concat', 'slice_bounds'))
        self.assertEqual(result[0].title, '自定义标题')

    def test_confirmed_points_next(self):
        result = specs.resolve_specs(
            [('func501', '')], points_by_function={'func501': ['loop', '未知标签']}
        )
        self.assertEqual(result[0].points, ('loop',))

    def test_reference_inference_next(self):
        source = 'def func502(nums):\n    return sorted(nums)\n'
        result = specs.resolve_specs([('func502', '')], reference_source=source)
        self.assertIn('sort_builtin', result[0].points)

    def test_text_inference_next(self):
        # 题面包的写法是“描述 … 将代码写入函数func503”，描述在函数名之前
        result = specs.resolve_specs(
            [('func503', '')], problem_text='判断奇数还是偶数 将代码写入函数func503'
        )
        self.assertIn('modulo', result[0].points)

    def test_fallback_basic_def(self):
        result = specs.resolve_specs([('func504', '')])
        self.assertEqual(result[0].points, ('basic_def',))
        self.assertEqual(result[0].title, 'func504')

    def test_title_falls_back_to_spec_title(self):
        result = specs.resolve_specs([('func301', '')])
        self.assertEqual(result[0].title, '合并两个列表，截取第 8~15 个元素（1 起始计数）')


class ResultTextTests(TestCase):
    def test_plain_string_passthrough(self):
        self.assertEqual(result_text('普通输出'), '普通输出')

    def test_packed_json_string_renders(self):
        packed = '{"type": "int", "value": 42}'
        self.assertEqual(result_text(packed), '42')

    def test_json_without_type_key_passthrough(self):
        self.assertEqual(result_text('[1, 2]'), '[1, 2]')

    def test_invalid_json_passthrough(self):
        self.assertEqual(result_text('abc {'), 'abc {')

    def test_none_value(self):
        self.assertEqual(result_text({'type': 'none'}), 'None')

    def test_scalars(self):
        self.assertEqual(result_text({'type': 'int', 'value': 7}), '7')
        self.assertEqual(result_text({'type': 'float', 'value': 1.5}), '1.5')
        self.assertEqual(result_text({'type': 'bool', 'value': True}), 'True')
        self.assertEqual(result_text({'type': 'str', 'value': 'hi'}), "'hi'")

    def test_complex(self):
        self.assertEqual(result_text({'type': 'complex', 'real': 1, 'imag': 2}), '(1 + 2j)')

    def test_containers(self):
        self.assertEqual(result_text({'type': 'list', 'items': []}), '[]')
        packed = '{"type": "list", "items": [{"type": "int", "value": 1}]}'
        self.assertEqual(result_text(packed), '[1]')
        self.assertEqual(
            result_text({'type': 'tuple', 'items': [{'type': 'int', 'value': 1}]}), '(1,)'
        )
        self.assertEqual(
            result_text(
                {'type': 'tuple', 'items': [{'type': 'int', 'value': 1}, {'type': 'int', 'value': 2}]}
            ),
            '(1, 2)',
        )

    def test_empty_set(self):
        self.assertEqual(result_text({'type': 'set', 'items': []}), 'set()')

    def test_set_rendering(self):
        rendered = result_text(
            {'type': 'set', 'items': [{'type': 'int', 'value': 1}, {'type': 'int', 'value': 2}]}
        )
        self.assertTrue(rendered.startswith('{') and rendered.endswith('}'))

    def test_dict_rendering(self):
        rendered = result_text(
            {
                'type': 'dict',
                'items': [
                    [{'type': 'str', 'value': 'k'}, {'type': 'int', 'value': 1}],
                ],
            }
        )
        self.assertEqual(rendered, "{'k': 1}")

    def test_long_list_truncated_with_ellipsis(self):
        items = [{'type': 'int', 'value': i} for i in range(150)]
        rendered = result_text({'type': 'list', 'items': items})
        self.assertTrue(rendered.endswith('…]'))
        self.assertIn('99', rendered)
        self.assertNotIn('149', rendered)

    def test_long_dict_truncated(self):
        pairs = [
            [{'type': 'int', 'value': i}, {'type': 'int', 'value': i}] for i in range(150)
        ]
        rendered = result_text({'type': 'dict', 'items': pairs})
        self.assertIn('…', rendered)

    def test_non_dict_value_uses_repr(self):
        self.assertEqual(result_text(42), '42')

    def test_depth_limit(self):
        nested = {'type': 'int', 'value': 1}
        for _ in range(20):
            nested = {'type': 'list', 'items': [nested]}
        # 超过递归深度后内层渲染为 …，外层仍包着括号
        rendered = result_text(nested)
        self.assertTrue(rendered.startswith('[['))
        self.assertIn('…', rendered)

    def test_unknown_type_falls_back_to_json(self):
        rendered = result_text({'type': 'mystery', 'value': 1})
        self.assertIn('mystery', rendered)
