from django import template

register = template.Library()


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
