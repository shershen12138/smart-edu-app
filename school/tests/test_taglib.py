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

    def test_thinking_abilities_declared(self):
        """题库 meta 声明计算思维四维，键与中文名一一对应。"""
        self.assertEqual(
            loader.thinking_abilities(),
            ('decomposition', 'pattern', 'abstraction', 'algorithm'),
        )
        self.assertEqual(loader.thinking_ability_label('algorithm'), '算法设计')
        self.assertEqual(loader.thinking_ability_label('未知'), '未知')

    def test_normalize_thinking_ability(self):
        """能力键与中文名都归一到标准键，未知值返回 None。"""
        self.assertEqual(loader.normalize_thinking_ability('算法设计'), 'algorithm')
        self.assertEqual(loader.normalize_thinking_ability('algorithm'), 'algorithm')
        self.assertIsNone(loader.normalize_thinking_ability('量子计算'))
        self.assertIsNone(loader.normalize_thinking_ability(''))

    def test_questions_for_ability(self):
        """按能力反查题目：主能力在前，且带判定依据。"""
        questions = loader.questions_for_ability('算法设计')
        self.assertTrue(questions)
        self.assertEqual(questions[0]['role'], 'primary')
        self.assertTrue(questions[0]['basis'])
        primary = loader.questions_for_ability('algorithm', primary_only=True)
        self.assertTrue(primary)
        self.assertTrue(all(item['role'] == 'primary' for item in primary))
        self.assertEqual(loader.questions_for_ability('量子计算'), ())

    def test_questions_for_abilities_union_and_intersection(self):
        """多能力组卷：默认取并集且去重，require_all 取交集。"""
        union = loader.questions_for_abilities(['算法设计', '抽象'])
        self.assertTrue(union)
        qids = [item['qid'] for item in union]
        self.assertEqual(len(qids), len(set(qids)))
        intersection = loader.questions_for_abilities(['算法设计', '抽象'], require_all=True)
        self.assertTrue(set(item['qid'] for item in intersection) <= set(qids))
        self.assertEqual(loader.questions_for_abilities([]), ())

    def test_every_question_has_ability(self):
        """44 题均有 1~2 个能力标注，且首项为主能力。"""
        questions = loader.qbank_questions()
        self.assertEqual(len(questions), 44)
        self.assertEqual(loader.thinking_abilities_for_question('未知题'), ())
        for question in questions:
            abilities = question.get('thinking_abilities') or []
            self.assertIn(len(abilities), (1, 2), question.get('qid'))
            self.assertTrue(question.get('thinking_basis'), question.get('qid'))
            self.assertTrue(loader.questions_for_ability(abilities[0], primary_only=True))
        entries = loader.thinking_abilities_for_question('Q1-01')
        self.assertEqual([label for _key, label, _basis in entries], ['抽象', '算法设计'])

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
