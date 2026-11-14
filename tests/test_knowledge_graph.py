# -*- coding: utf-8 -*-
"""提高覆盖率的补充测试：知识图谱模块（school/portal/knowledge_graph.py）。

覆盖：真实数据加载与校验、放射布局坐标计算、校验失败分支。
"""
import math

from django.test import TestCase

from school.portal import knowledge_graph


def make_data(nodes_spec, edges_spec, node_count=None, edge_count=None):
    nodes = [{'id': nid, 'name': name, 'level': level, 'category': cat, 'summary': ''}
             for nid, name, level, cat in nodes_spec]
    edges = [{'source': s, 'target': t, 'type': kind} for s, t, kind in edges_spec]
    return {
        'meta': {
            'nodeCount': len(nodes) if node_count is None else node_count,
            'edgeCount': len(edges) if edge_count is None else edge_count,
        },
        'nodes': nodes,
        'edges': edges,
    }


NODES = [
    ('py', 'Python', 1, 'root'),
    ('m1', '基础语法', 2, 'syntax'),
    ('m2', '数据结构', 2, 'data'),
    ('p1', '变量与赋值', 3, 'syntax'),
    ('s1', '多重赋值', 4, 'syntax'),
]


class ValidateTests(TestCase):
    """图谱数据校验的各失败分支。"""

    EDGES = [
        ('py', 'm1', 'contains'),
        ('py', 'm2', 'contains'),
        ('m1', 'p1', 'contains'),
        ('p1', 's1', 'contains'),
    ]

    def test_valid_data_passes(self):
        data = make_data(NODES, self.EDGES)
        knowledge_graph._validate(data)  # 不抛错即通过

    def test_duplicate_node_id(self):
        nodes = NODES + [('m1', '重复节点', 2, 'data')]
        with self.assertRaisesRegex(ValueError, '重复节点'):
            knowledge_graph._validate(make_data(nodes, self.EDGES))

    def test_node_count_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'nodeCount'):
            knowledge_graph._validate(make_data(NODES, self.EDGES, node_count=99))

    def test_edge_count_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'edgeCount'):
            knowledge_graph._validate(make_data(NODES, self.EDGES, edge_count=99))

    def test_unknown_edge_type(self):
        edges = self.EDGES + [('m1', 'm2', '兄弟关系')]
        with self.assertRaisesRegex(ValueError, '未知关系类型'):
            knowledge_graph._validate(make_data(NODES, edges))

    def test_dangling_edge_reference(self):
        edges = self.EDGES + [('m1', 'ghost', 'contains')]
        with self.assertRaisesRegex(ValueError, '悬空引用'):
            knowledge_graph._validate(make_data(NODES, edges))


class LayoutTests(TestCase):
    """放射布局：根在原点，模块按角度均分，坐标落在对应半径上。"""

    EDGES = [
        ('py', 'm1', 'contains'),
        ('py', 'm2', 'contains'),
        ('m1', 'p1', 'contains'),
        ('p1', 's1', 'contains'),
    ]

    def test_layout_positions(self):
        data = make_data(NODES, self.EDGES)
        knowledge_graph._layout(data['nodes'], data['edges'])
        by_id = {node['id']: node for node in data['nodes']}

        root = by_id['py']
        self.assertEqual((root['x'], root['y']), (0.0, 0.0))

        # 2 个模块：-90° 与 -90°+180°，半径 R1
        m1 = by_id['m1']
        expected_angle = -90.0
        self.assertAlmostEqual(
            m1['x'], round(knowledge_graph.R1 * math.cos(math.radians(expected_angle)), 1)
        )
        m2 = by_id['m2']
        self.assertAlmostEqual(
            m2['x'], round(knowledge_graph.R1 * math.cos(math.radians(expected_angle + 180.0)), 1)
        )

        # 三层节点半径 R2、四层半径 R3
        p1 = by_id['p1']
        self.assertAlmostEqual(math.hypot(p1['x'], p1['y']), knowledge_graph.R2, places=1)
        s1 = by_id['s1']
        self.assertAlmostEqual(math.hypot(s1['x'], s1['y']), knowledge_graph.R3, places=1)

    def test_layout_single_child_no_spread_error(self):
        """单子节点时 offset = -spread/2，角度仍在模块扇区 ±spread/2 范围内。"""
        data = make_data(NODES, self.EDGES)
        knowledge_graph._layout(data['nodes'], data['edges'])
        by_id = {node['id']: node for node in data['nodes']}
        m1 = by_id['m1']
        p1 = by_id['p1']
        module_angle = math.degrees(math.atan2(m1['y'], m1['x']))
        point_angle = math.degrees(math.atan2(p1['y'], p1['x']))
        diff = abs((point_angle - module_angle + 180) % 360 - 180)
        self.assertLessEqual(diff, 4.1)  # spread = min(52, 1*8) = 8，offset = -4


class BuildGraphTests(TestCase):
    """真实数据文件端到端构建。"""

    @classmethod
    def setUpTestData(cls):
        cls.graph = knowledge_graph.build_graph()

    def test_structure(self):
        for key in ('meta', 'nodes', 'edges', 'relationLabels', 'relationShort', 'modules'):
            self.assertIn(key, self.graph)
        self.assertEqual(
            self.graph['relationLabels'], knowledge_graph.RELATION_LABELS,
        )
        self.assertGreater(len(self.graph['nodes']), 0)
        self.assertGreater(len(self.graph['edges']), 0)
        self.assertEqual(
            self.graph['meta']['nodeCount'], len(self.graph['nodes']),
        )

    def test_every_node_has_coordinates(self):
        for node in self.graph['nodes']:
            self.assertIn('x', node)
            self.assertIn('y', node)
            self.assertIsInstance(node['x'], float)
            self.assertIsInstance(node['y'], float)

    def test_root_at_origin_and_module_radius(self):
        roots = [node for node in self.graph['nodes'] if node['level'] == 1]
        self.assertEqual(len(roots), 1)
        self.assertEqual((roots[0]['x'], roots[0]['y']), (0.0, 0.0))
        for node in self.graph['nodes']:
            if node['level'] == 2:
                self.assertAlmostEqual(
                    math.hypot(node['x'], node['y']), knowledge_graph.R1, places=1
                )

    def test_edge_types_all_known(self):
        allowed = knowledge_graph.ALLOWED_TYPES
        self.assertTrue(self.graph['edges'])
        for edge in self.graph['edges']:
            self.assertIn(edge['type'], allowed)

    def test_modules_list_level2_points(self):
        self.assertTrue(self.graph['modules'])
        module = self.graph['modules'][0]
        self.assertIn('points', module)
        self.assertTrue(all(isinstance(point, str) for point in module['points']))
