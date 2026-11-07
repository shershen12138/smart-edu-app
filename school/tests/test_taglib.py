"""Tag 库加载器与知识点归一的测试。"""

from django.test import TestCase

from tools.taglib import loader


class TaglibLoaderTests(TestCase):
    def test_tag_library_parsed(self):
        """词表解析出全部单元与模块（目录表声明 15 个单元 / 77 个模块）。"""
        modules = loader.tag_modules()
        units = {module[0].split()[0] for module in modules}
        self.assertEqual(len(units), 15)
        self.assertEqual(len(modules), 77)
        self.assertGreater(len(loader.tag_names()), 800)

    def test_normalize_tag(self):
        """自由文本知识点名归一到词表标准名。"""
        self.assertEqual(loader.normalize_tag('算术运算符'), '算术运算符')
        # 包含匹配：名字里完整包含的最长 tag
        self.assertEqual(loader.normalize_tag('列表切片与反转'), '列表切片')
        self.assertIsNone(loader.normalize_tag('量子计算'))
        self.assertIsNone(loader.normalize_tag(''))

    def test_qbank_by_tag(self):
        """题库打标文件可按 tag 反查题目，主要考点排在前面。"""
        questions = loader.questions_for_tag('算术运算符')
        self.assertTrue(questions)
        self.assertEqual(questions[0]['qid'], 'Q1-01')
        self.assertEqual(questions[0]['role'], 'primary')

    def test_top_tags_weights_sum_to_one(self):
        """考察重点权重归一化，且覆盖题数多的 tag 更主要。"""
        tag_tasks = {
            'while 循环': ['func501', 'func509'],
            '列表切片': ['func301'],
        }
        weights = {'func501': 10, 'func509': 10, 'func301': 10}
        top = loader.top_tags(tag_tasks, weights, limit=6)
        self.assertEqual([tag for tag, _share in top], ['while 循环', '列表切片'])
        self.assertAlmostEqual(sum(share for _tag, share in top), 1.0, places=2)
