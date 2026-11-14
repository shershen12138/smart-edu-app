from django.urls import path

from . import knowledge_views, practice_views, quality_views
from . import learning_views as views

urlpatterns = [
    path('knowledge/', knowledge_views.knowledge_map, name='knowledge_map'),
    path('practice/', practice_views.practice_home, name='practice'),
    path(
        'practice/problem/<int:pk>/',
        practice_views.practice_problem,
        name='practice_problem',
    ),
    path(
        'practice/problem/<int:pk>/submit/',
        practice_views.practice_submit,
        name='practice_submit',
    ),
    path('practice/result/<int:pk>/', practice_views.practice_result, name='practice_result'),
    path('work/<int:pk>/', views.work_detail, name='work'),
    path('work/<int:pk>/file/<str:kind>/', views.work_file, name='work_file'),
    path('entries/<int:pk>/', views.entry_detail, name='entry'),
    path('entries/<int:pk>/source/', views.entry_detail, {'download': True}, name='entry_source'),
    path('entries/<int:pk>/retry/', views.entry_retry, name='entry_retry'),
    path('entries/<int:pk>/quality/', quality_views.quality_report, name='quality_report'),
    path('entries/<int:pk>/quality/radar.png', quality_views.quality_radar, name='quality_radar'),
    path(
        'entries/<int:pk>/quality/report.md',
        quality_views.quality_markdown,
        name='quality_markdown',
    ),
]
