"""静态资源回归：加载遮罩的选择器必须只命中全局遮罩。

历史问题：上传页的表单本身带 ``data-loading``（自定义提示文案），
如果 JS 用 ``[data-loading]`` 取遮罩，会先选中表单，首屏 load 时把表单
设为 hidden，表现就是“上传窗口空白”。
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class LoadingOverlaySelectorTests(SimpleTestCase):
    def test_portal_js_targets_overlay_by_class(self):
        source = (Path(settings.BASE_DIR) / 'static' / 'portal.js').read_text(
            encoding='utf-8'
        )
        self.assertIn("document.querySelector('.loading-overlay')", source)
        self.assertNotIn("document.querySelector('[data-loading]')", source)
