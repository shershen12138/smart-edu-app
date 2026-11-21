"""数据库账户权限与慢查询日志的只读检查（8.1.4.3 安全审计、8.1.4.4 入侵防范）。

纯函数集中在这里，便于不依赖 MySQL 直接测试；命令行为由
`manage.py db_security_check` 负责。
"""

import re

from school.sql_guard import RULES

# 应用账号不应持有的全局高危权限
GLOBAL_RISK_PRIVILEGES = {
    'ALL PRIVILEGES': '应用账号不应拥有全局管理权限',
    'FILE': '可读写数据库服务器上的文件',
    'PROCESS': '可查看所有连接与会话内容',
    'SUPER': '可绕过连接数与只读限制',
    'SHUTDOWN': '可关闭数据库实例',
    'CREATE USER': '可创建或修改数据库账号',
    'RELOAD': '可刷新日志与权限缓存',
    'REPLICATION SLAVE': '可读取主库变更数据',
    'REPLICATION CLIENT': '可查看主从与二进制日志状态',
    'GRANT OPTION': '可把自身权限转授给其他账号',
}

_GRANT_RE = re.compile(
    r'^GRANT\s+(?P<privileges>.+?)\s+ON\s+(?P<scope>\S+)\s+TO\s+', re.I | re.S
)
_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'")
_MAX_FINDINGS = 50


def parse_grants(rows):
    """把 `SHOW GRANTS` 的文本行解析为 [(权限列表, 作用域)]，跳过角色授予语句。"""
    grants = []
    for row in rows:
        text = str(row or '').strip()
        match = _GRANT_RE.match(text)
        if not match:
            continue
        privileges = [
            item.strip().upper()
            for item in match.group('privileges').split(',')
            if item.strip()
        ]
        # SHOW GRANTS 把转授权写在语句结尾：... TO `u`@`%` WITH GRANT OPTION
        if 'WITH GRANT OPTION' in text.upper():
            privileges.append('GRANT OPTION')
        if privileges:
            grants.append((privileges, match.group('scope')))
    return grants


def privilege_findings(grants):
    """返回高危权限列表，每项为 {privilege, scope, reason}；同一权限只报一次。"""
    findings = []
    seen = set()
    for privileges, scope in grants:
        candidates = list(privileges)
        if 'GRANT OPTION' in privileges:
            key = ('GRANT OPTION', scope)
            if key not in seen:
                seen.add(key)
                findings.append(
                    {
                        'privilege': 'GRANT OPTION',
                        'scope': scope,
                        'reason': GLOBAL_RISK_PRIVILEGES['GRANT OPTION'],
                    }
                )
        if scope != '*.*':
            continue
        for privilege in candidates:
            reason = GLOBAL_RISK_PRIVILEGES.get(privilege)
            key = (privilege, scope)
            if reason and key not in seen:
                seen.add(key)
                findings.append({'privilege': privilege, 'scope': scope, 'reason': reason})
    return findings


def sanitize_statement(sql, limit=160):
    """把语句中的字符串常量替换为 ?，避免巡检输出里带出姓名、口令等业务数据。"""
    return _LITERAL_RE.sub("'?'", str(sql)).strip()[:limit]


def scan_statements(lines):
    """扫描慢查询日志文本行，返回 [{rule, severity, statement}]，最多 50 条。"""
    findings = []
    for line in lines:
        text = str(line or '').strip()
        if not text:
            continue
        for rule, severity, pattern in RULES:
            if pattern.search(text):
                findings.append(
                    {
                        'rule': rule,
                        'severity': severity,
                        'statement': sanitize_statement(text),
                    }
                )
                break
        if len(findings) >= _MAX_FINDINGS:
            break
    return findings
