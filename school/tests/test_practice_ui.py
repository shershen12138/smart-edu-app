"""弱项练习页面结构：弱项列表限高滚动，已掌握知识点收起为一行并可展开。

这些是纯展示约束，用模板/CSS 源码回归即可覆盖，
真正的页面渲染在 ``school.tests.test_capability`` 里验证。
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _read(*parts) -> str:
    return (Path(settings.BASE_DIR).joinpath(*parts)).read_text(encoding='utf-8')


class PracticePageMarkupTests(SimpleTestCase):
    def setUp(self):
        self.html = _read('templates', 'portal', 'practice.html')
        self.css = _read('static', 'app.css')

    def test_weak_table_is_height_limited_and_scrollable(self):
        self.assertIn('table-card weak-scroll', self.html)
        self.assertIn('.weak-scroll', self.css)
        # 表头 + 三行的固定高度，超出后上下滚动
        self.assertIn('max-height: 206px', self.css)
        self.assertIn('overflow-y: auto', self.css)
        # 滚动时表头吸顶，列名不会跟着滚走
        self.assertIn('position: sticky', self.css)

    def test_mastered_points_collapse_into_one_line(self):
        self.assertIn('mastered-details', self.html)
        self.assertIn('<details class="mastered-details">', self.html)
        # 收起时最多显示 5 个知识点，其余用 +N 表示
        self.assertIn('|slice:":5"', self.html)
        self.assertIn('mastered-more', self.html)
        self.assertIn('mastered-caret', self.html)
        # 展开后显示全部
        self.assertIn('mastered-row', self.html)

    def test_collapsed_and_expanded_states_are_styled(self):
        self.assertIn('.mastered-details[open] .mastered-preview', self.css)
        self.assertIn('.mastered-details[open] .mastered-caret', self.css)

    def test_plan_uses_two_column_card_grid(self):
        """训练计划按知识点分组，题目用两列卡片铺满，窄屏回落单列。"""
        self.assertNotIn('plan-table', self.html)
        self.assertIn('plan-group', self.html)
        self.assertIn('class="plan-grid"', self.html)
        self.assertIn('class="plan-card-main"', self.html)
        # 卡片含标题、难度标签与“开始练习”入口
        self.assertIn('plan-card-title', self.html)
        self.assertIn('{{ problem.difficulty }}', self.html)
        self.assertIn('开始练习', self.html)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))', self.css)
        self.assertIn('.plan-card', self.css)
        self.assertIn('@media (max-width: 720px)', self.css)
