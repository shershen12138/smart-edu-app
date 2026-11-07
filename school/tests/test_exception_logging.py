"""异常日志基础设施测试：school/tools 的 ERROR 级日志落盘到轮转文件。"""

import logging
import logging.handlers
import uuid

from django.conf import settings
from django.test import TestCase


def _file_handlers(logger_name):
    logger = logging.getLogger(logger_name)
    return [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]


class ExceptionFileHandlerTests(TestCase):
    def test_school_logger_writes_to_rotating_file(self):
        handlers = _file_handlers('school')
        self.assertEqual(len(handlers), 1)
        handler = handlers[0]
        self.assertTrue(str(handler.baseFilename).endswith('exception.log'))
        self.assertEqual(handler.level, logging.ERROR)
        self.assertEqual(handler.maxBytes, 10 * 1024 * 1024)
        self.assertEqual(handler.backupCount, 5)

    def test_tools_logger_writes_to_rotating_file(self):
        self.assertEqual(len(_file_handlers('tools')), 1)

    def test_exception_reaches_log_file(self):
        marker = f'exception-log-test-{uuid.uuid4().hex}'
        try:
            raise RuntimeError(marker)
        except RuntimeError:
            logging.getLogger('school.tests.exception').exception('模拟异常 %s', marker)
        with open(settings.LOGGING['handlers']['exception_file']['filename'], encoding='utf-8') as fh:
            content = fh.read()
        self.assertIn(marker, content)

    def test_info_level_does_not_reach_file(self):
        handler = _file_handlers('school')[0]
        self.assertGreater(handler.level, logging.INFO)
