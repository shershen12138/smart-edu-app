from django.urls import path

from . import learning_views as views
from . import quality_views

urlpatterns = [
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
