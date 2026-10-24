import json


def result_text(value, depth=0):
    """Render the grader's typed JSON without executing source or deserializing code."""
    if depth > 12:
        return '…'
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value[:4000]
        if isinstance(parsed, dict) and 'type' in parsed:
            return result_text(parsed, depth + 1)
        return value[:4000]
    if not isinstance(value, dict):
        return repr(value)[:4000]
    kind = value.get('type')
    if kind == 'none':
        return 'None'
    if kind in ('bool', 'int', 'float', 'str'):
        return repr(value.get('value'))[:4000]
    if kind == 'complex':
        return f'({value.get("real")} + {value.get("imag")}j)'
    if kind in ('list', 'tuple', 'set'):
        items = value.get('items', [])
        body = ', '.join(result_text(item, depth + 1) for item in items[:100])
        if len(items) > 100:
            body += ', …'
        left, right = {'list': ('[', ']'), 'tuple': ('(', ')'), 'set': ('{', '}')}[kind]
        if kind == 'set' and not items:
            return 'set()'
        if kind == 'tuple' and len(items) == 1:
            body += ','
        return (left + body + right)[:4000]
    if kind == 'dict':
        pairs = value.get('items', [])
        return (
            '{'
            + ', '.join(
                result_text(key, depth + 1) + ': ' + result_text(item, depth + 1)
                for key, item in pairs[:100]
            )
            + (', …' if len(pairs) > 100 else '')
            + '}'
        )[:4000]
    return json.dumps(value, ensure_ascii=False)[:4000]
