"""SQL 注入纵深防御：识别 GET 查询串中的注入特征（8.1.4.4 入侵防范）。

业务查询全部走 Django ORM 参数绑定，这一层不承担“防注入”的主要职责，只在应用入口
把明显异常的请求拦下来并留痕：

- 高置信度特征（引号配平的恒真条件、堆叠语句、延时函数等）直接返回 400 并写审计；
- 低置信度特征（`UNION SELECT`、`information_schema`）只记日志，避免误伤教学场景，
  教师在题库或知识库中检索 SQL 关键字属于正常用法；
- 表单、JSON 与文件上传内容不参与判断，学生提交的代码和课程内容不会被当成攻击载荷。
"""

import logging
import re

from django.conf import settings
from django.http import HttpResponseBadRequest

logger = logging.getLogger(__name__)

HIGH = 'high'
LOW = 'low'

# (规则名, 置信度, 正则)
RULES = (
    (
        'quote_tautology',
        HIGH,
        re.compile(
            r"""['"`]\s*(?:or|and)\s+['"`]?\w+['"`]?\s*(?:=|<>|!=|<|>|like)\s*['"`]?\w+""",
            re.I,
        ),
    ),
    ('quote_comment', HIGH, re.compile(r"""['"`]\s*(?:--|#|/\*)""")),
    (
        'stacked_statement',
        HIGH,
        re.compile(r';\s*(?:drop|delete|update|insert|alter|truncate|create|grant)\b', re.I),
    ),
    (
        'time_delay',
        HIGH,
        re.compile(r'\b(?:sleep|benchmark|pg_sleep)\s*\(|\bwaitfor\s+delay\b', re.I),
    ),
    ('union_select', LOW, re.compile(r'\bunion\b[\s(]*(?:all[\s(]*)?select\b', re.I)),
    (
        'metadata_probe',
        LOW,
        re.compile(r'\binformation_schema\b|\bsysobjects\b|\bpg_catalog\b', re.I),
    ),
    (
        'file_access',
        LOW,
        re.compile(r'\binto\s+(?:out|dump)file\b|\bload_file\s*\(', re.I),
    ),
)


def scan(values):
    """返回命中的 [(参数名, 规则名, 置信度)]，同一参数只保留优先命中（顺序即优先级）。"""
    hits = []
    for name, value in values:
        text = str(value)
        for rule, severity, pattern in RULES:
            if pattern.search(text):
                hits.append((name, rule, severity))
                break
    return hits


class SqlInjectionGuardMiddleware:
    """拦截带 SQL 注入特征的 GET 请求；高风险写审计，低风险只记日志。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, 'SQL_GUARD_ENABLED', True):
            hits = scan(
                (name, value) for name, values in request.GET.lists() for value in values
            )
            if hits:
                blocked = [hit for hit in hits if hit[2] == HIGH]
                self._record(request, hits, blocked=bool(blocked))
                if blocked:
                    return HttpResponseBadRequest(
                        '请求参数包含疑似 SQL 注入内容，已被安全策略拦截。'
                    )
        return self.get_response(request)

    def _record(self, request, hits, blocked):
        """只记录参数名与规则名，不落原始输入，避免日志里出现口令或个人信息。"""
        params = sorted({name for name, _, _ in hits})[:10]
        rules = sorted({rule for _, rule, _ in hits})
        logger.warning(
            'SQL 注入特征 path=%s params=%s rules=%s blocked=%s ip=%s',
            request.path,
            params,
            rules,
            blocked,
            request.META.get('REMOTE_ADDR'),
        )
        user = getattr(request, 'user', None)
        if blocked and user is not None and user.is_authenticated:
            from school.services import audit

            audit(
                user,
                'security.sql_injection_blocked',
                request.path[:160],
                {'params': params, 'rules': rules},
                request=request,
                result='failure',
            )
