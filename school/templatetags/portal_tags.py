from django import template

register = template.Library()


@register.filter
def mask_student_no(value):
    """学号脱敏：保留前 2 位与后 2 位（8.1.4.8 个人信息保护）。"""
    text = str(value or '')
    if len(text) <= 4:
        return text
    return f'{text[:2]}{"*" * (len(text) - 4)}{text[-2:]}'


@register.filter
def mask_email(value):
    """邮箱脱敏：只保留首字母与域名。"""
    text = str(value or '')
    if '@' not in text:
        return text
    name, _, domain = text.partition('@')
    if len(name) <= 1:
        return f'*@{domain}'
    return f'{name[0]}{"*" * (len(name) - 1)}@{domain}'


@register.filter
def verdict_label(value):
    return {
        'AC': '通过',
        'WA': '结果不符',
        'CE': '语法错误',
        'RE': '运行错误 / 函数缺失',
        'TLE': '运行超时',
        'MLE': '内存超限',
        'OLE': '输出超限',
        'PENDING': '等待批阅',
        'WAITING': '待接入批阅',
        'MANUAL_PENDING': '待教师批阅',
        'MANUAL': '教师已批阅',
        'ERROR': '批阅服务异常',
    }.get(value, value)
