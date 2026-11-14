"""学生端知识图谱页面。"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import knowledge_graph
from .access import require_role
from .common_views import page


@login_required
@require_http_methods(['GET'])
def knowledge_map(request):
    require_role(request.user, 'student')
    graph = knowledge_graph.build_graph()
    return page(
        request,
        'knowledge_map',
        '知识图谱',
        graph_data=graph,
        graph_modules=graph['modules'],
        hub_total=sum(1 for node in graph['nodes'] if node['level'] == 2),
        point_total=sum(1 for node in graph['nodes'] if node['level'] >= 3),
        edge_total=len(graph['edges']),
        back_url=reverse('dashboard'),
    )
