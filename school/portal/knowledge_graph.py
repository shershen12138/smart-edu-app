"""Python 课程知识图谱：加载 JSON 数据、校验、计算放射布局。

数据文件 school/portal/data/python_graph.json 与视图解耦：
组件只消费 {nodes, edges}，替换学科时只需换 JSON 文件。
知识结构整理自《Python学习手册（第4版）》与《Python语言程序设计》
两本教材的目录，粒度为一个考点或一节课。

放射布局在服务端一次算好：
- 第 1 层根节点在原点
- 第 2 层大知识点均匀分布在半径 R1 的圆上
- 第 3 层知识点分布在各自模块扇区、半径 R2 的弧上
- 第 4 层子知识点聚在父节点角度附近、半径 R3 的弧上
前端默认用坐标直接渲染（layout: none），可切换力导向微调。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

DATA_FILE = Path(__file__).parent / 'data' / 'python_graph.json'

R1 = 250.0  # 大知识点圆半径
R2 = 460.0  # 知识点圆半径
R3 = 640.0  # 子知识点圆半径

ALLOWED_TYPES = {'contains', 'prerequisite', 'applied_in', 'contrast', 'cause'}

RELATION_LABELS = {
    'contains': '包含',
    'prerequisite': '前置依赖',
    'applied_in': '应用',
    'contrast': '易混淆对比',
    'cause': '因果推导',
}

RELATION_SHORT = {
    'contains': '',
    'prerequisite': '先学',
    'applied_in': '应用',
    'contrast': '易混',
    'cause': '推导',
}


def _load_raw() -> dict:
    with DATA_FILE.open(encoding='utf-8') as fp:
        return json.load(fp)


def _validate(data: dict) -> None:
    ids = [node['id'] for node in data['nodes']]
    if len(ids) != len(set(ids)):
        raise ValueError('知识图谱存在重复节点 id')
    if data['meta']['nodeCount'] != len(ids):
        raise ValueError('meta.nodeCount 与实际节点数不一致')
    if data['meta']['edgeCount'] != len(data['edges']):
        raise ValueError('meta.edgeCount 与实际边数不一致')
    id_set = set(ids)
    for edge in data['edges']:
        if edge['type'] not in ALLOWED_TYPES:
            raise ValueError(f'未知关系类型：{edge["type"]}')
        if edge['source'] not in id_set or edge['target'] not in id_set:
            raise ValueError(f'边存在悬空引用：{edge["source"]} → {edge["target"]}')


def _layout(nodes: list[dict], edges: list[dict]) -> None:
    """为每个节点写入放射布局坐标 x / y（服务端算好，前端免三角函数）。"""
    modules = [node for node in nodes if node['level'] == 2]
    children_map: dict[str, list[str]] = {node['id']: [] for node in nodes}
    for edge in edges:
        if edge['type'] == 'contains':
            children_map.setdefault(edge['source'], []).append(edge['target'])

    root = next(node for node in nodes if node['level'] == 1)
    root['x'] = 0.0
    root['y'] = 0.0

    count = len(modules)
    for index, module in enumerate(modules):
        angle = -90.0 + index * 360.0 / count
        rad = math.radians(angle)
        module['x'] = round(R1 * math.cos(rad), 1)
        module['y'] = round(R1 * math.sin(rad), 1)

        points = [node for node in nodes if node['level'] == 3 and node['category'] == module['category']]
        spread = min(52.0, len(points) * 8.0)
        for point_index, point in enumerate(points):
            offset = -spread / 2 + (spread * point_index / max(len(points) - 1, 1))
            point_angle = angle + offset
            point_rad = math.radians(point_angle)
            point['x'] = round(R2 * math.cos(point_rad), 1)
            point['y'] = round(R2 * math.sin(point_rad), 1)

            subs = [node for node in nodes if node['level'] == 4 and node['id'] in children_map[point['id']]]
            sub_spread = 7.0
            for sub_index, sub in enumerate(subs):
                sub_angle = point_angle + (sub_index - (len(subs) - 1) / 2) * sub_spread
                sub_rad = math.radians(sub_angle)
                sub['x'] = round(R3 * math.cos(sub_rad), 1)
                sub['y'] = round(R3 * math.sin(sub_rad), 1)


def build_graph() -> dict:
    """返回带放射布局坐标与模块索引的完整图数据。"""
    data = _load_raw()
    _validate(data)
    _layout(data['nodes'], data['edges'])

    modules = []
    for node in data['nodes']:
        if node['level'] != 2:
            continue
        points = [
            child['name']
            for child in data['nodes']
            if child['level'] == 3 and child['category'] == node['category']
        ]
        modules.append(
            {
                'id': node['id'],
                'name': node['name'],
                'summary': node['summary'],
                'points': points,
            }
        )

    return {
        'meta': data['meta'],
        'nodes': data['nodes'],
        'edges': data['edges'],
        'relationLabels': RELATION_LABELS,
        'relationShort': RELATION_SHORT,
        'modules': modules,
    }
