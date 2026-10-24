"""题库规格：每道题考什么、按什么语义规则检查。

题目要求来自 `exercise requirements/03-列表/.../03-列表习题说明.docx`
与 `func_info_list.txt`；知识点标签与 static_analysis.KNOWLEDGE_DETECTORS 对应。
扩展新课程时，新增一个 COURSE_SPECS 条目即可，分析与评分流程不改。
"""

from __future__ import annotations

from .models import TaskSpec

POINT_LABELS: dict[str, str] = {
    "list_concat": "列表合并（+ / extend）",
    "slice_bounds": "切片与 1 起始计数换算",
    "slice_reverse": "切片反转 [::-1]",
    "len": "len() 求长度",
    "index_arith": "下标算术（// 取中间位置）",
    "floor_div": "整除 //",
    "compare": "比较运算与 ==",
    "if_else": "if / else 分支",
    "elif_chain": "if / elif / else 多分支",
    "loop": "for 遍历",
    "while_loop": "while 循环",
    "nested_loop": "双重循环",
    "negative_index": "负索引",
    "list_mutation": "列表增删（insert / del / append）",
    "del_or_rebuild": "删除元素或重建列表",
    "comprehension": "列表推导式",
    "type_check": "type() / isinstance 类型判断",
    "helper_function": "自定义辅助函数",
    "counter": "计数器累加",
    "nested_list": "二维列表",
    "sort_key": "sort(key=...) 自定义排序",
    "lambda": "lambda 表达式",
    "range_loop": "range() 区间",
    "int_str_convert": "str() / int() 数位拆分",
    "list_build": "列表拼接构建",
    "reverse": "reverse() / reversed() 反转",
    "builtin_max": "max() / min() 内置聚合",
    "double_loop": "二维遍历",
    "append_row": "按行 append 子列表",
    "linear_scan": "线性扫描定位",
    "insert": "insert() 插入",
    "modulo": "取余 %",
    "sort_builtin": "sorted() / list.sort() 排序",
    "str_method": "字符串方法（upper / split / isdigit 等）",
    "str_join": "字符串拼接（+ / join）",
    "dict_access": "字典按键取值",
    "dict_update": "字典按键赋值",
    "set_op": "集合 set 运算",
    "recursion": "递归调用",
    "try_except": "try / except 异常处理",
    "file_open": "open() 文件读写",
    "class_def": "class 类与对象",
    "enumerate_zip": "enumerate() / zip() 遍历",
    "loop_control": "break / continue 循环控制",
    "basic_def": "函数定义与返回值",
}

# 反向索引：评分标准里使用的中文知识点名若与题库标签同名，可据此还原出检测标签，
# 从而判断学生在代码里是否真的用到了该知识点；自定义名称无法还原，只展示不判定。
LABEL_TO_POINT: dict[str, str] = {label: tag for tag, label in POINT_LABELS.items()}

LIST_TASKS: tuple[TaskSpec, ...] = (
    TaskSpec(
        "func301",
        "合并两个列表，截取第 8~15 个元素（1 起始计数）",
        ("list_concat", "slice_bounds"),
    ),
    TaskSpec(
        "func302",
        "求中位数，偶数个元素时取中间两数的较小者",
        ("len", "index_arith", "if_else", "floor_div"),
    ),
    TaskSpec(
        "func303",
        "判断列表是否为回文，返回 1 或 0",
        ("slice_reverse", "compare", "if_else"),
    ),
    TaskSpec(
        "func304",
        "去重并保持元素原始先后顺序",
        ("loop", "del_or_rebuild"),
    ),
    TaskSpec(
        "func305",
        "删除列表中非整数元素，保持保留元素顺序",
        ("comprehension", "type_check"),
    ),
    TaskSpec(
        "func306",
        "统计可表示为列表中另外两个质数之和的质数个数",
        ("helper_function", "nested_loop", "counter"),
    ),
    TaskSpec(
        "func307",
        "连续重复 2 次以上的元素局部累加合并",
        ("while_loop", "negative_index", "list_mutation"),
    ),
    TaskSpec(
        "func308",
        "比较奇偶个数，按 1/2/3 返回码返回",
        ("loop", "counter", "elif_chain"),
    ),
    TaskSpec(
        "func309",
        "按总分降序、总分相同学号升序，返回最高分（含并列）",
        ("nested_list", "sort_key", "lambda"),
    ),
    TaskSpec(
        "func310",
        "返回 N 以内（含 N）的全部质数，增序",
        ("range_loop", "comprehension", "helper_function"),
    ),
    TaskSpec(
        "func311",
        "把每个元素替换为从低位到高位的各位数字",
        ("int_str_convert", "list_build", "reverse"),
    ),
    TaskSpec(
        "func312",
        "反复合并相邻和最大的两数为平均值，直到只剩两个",
        ("while_loop", "builtin_max", "list_build"),
    ),
    TaskSpec(
        "func313",
        "N×N 矩阵转置（二维列表表示）",
        ("nested_list", "double_loop", "append_row"),
    ),
    TaskSpec(
        "func314",
        "按各位数字平均值的升序排序，相同则数值降序",
        ("sort_key", "lambda", "helper_function"),
    ),
    TaskSpec(
        "func315",
        "把新整数插入有序列表，仍保持增序",
        ("linear_scan", "insert", "compare"),
    ),
)

BRANCH_TASKS: tuple[TaskSpec, ...] = (
    TaskSpec(
        "func401",
        "判断整数是奇数还是偶数",
        ("if_else", "modulo", "compare"),
    ),
    TaskSpec(
        "func402",
        "判断能否被 3 整除，输入不在 0~100 时返回错误提示",
        ("if_else", "compare", "modulo"),
    ),
    TaskSpec(
        "func403",
        "求位数、逐位数字与逆序结果",
        ("int_str_convert", "len", "comprehension", "slice_reverse"),
    ),
    TaskSpec(
        "func404",
        "比较两个正整数并返回较大值",
        ("if_else", "compare"),
    ),
    TaskSpec(
        "func405",
        "三个整数按从小到大输出",
        ("sort_builtin",),
    ),
    TaskSpec(
        "func406",
        "按用户信息列表校验用户名和密码",
        ("if_else", "compare"),
    ),
    TaskSpec(
        "func407",
        "按买 3 送 1、买 5 送 2 计算最多瓶数",
        ("while_loop", "floor_div", "elif_chain", "counter"),
    ),
    TaskSpec(
        "func408",
        "按存款区间计算一年后的本息和",
        ("if_else", "elif_chain", "compare"),
    ),
    TaskSpec(
        "func409",
        "判断能否构成三角形并计算面积与周长",
        ("if_else", "compare"),
    ),
    TaskSpec(
        "func410",
        "判断等边、直角或一般三角形",
        ("if_else", "elif_chain", "compare"),
    ),
    TaskSpec(
        "func411",
        "判断坐标点是否在圆内",
        ("if_else", "compare"),
    ),
)

COURSE_SPECS: dict[str, tuple[TaskSpec, ...]] = {
    "03-列表": LIST_TASKS,
    "04-分支结构": BRANCH_TASKS,
}


def specs_for(course: str) -> tuple[TaskSpec, ...]:
    try:
        return COURSE_SPECS[course]
    except KeyError as exc:  # pragma: no cover - 配置期错误
        raise KeyError(f"课程 {course} 尚未配置题目规格") from exc
