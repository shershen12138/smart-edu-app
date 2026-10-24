from django.urls import path

from . import rubric_views
from . import teaching_views as views
from .downloads import submissions_download

urlpatterns = [
    path(
        'work/<int:pk>/submissions.zip',
        submissions_download,
        name='work_submissions_download',
    ),
    path(
        'classes/<int:class_id>/students/<int:student_id>/',
        views.student_results,
        name='student_results',
    ),
    path('work/', views.works, name='works'),
    path('work/new/', views.work_edit, name='work_new'),
    path('work/<int:pk>/edit/', views.work_edit, name='work_edit'),
    path('work/<int:pk>/rubric/', rubric_views.work_rubric, name='work_rubric'),
    path(
        'work/<int:pk>/rubric.md',
        rubric_views.work_rubric_download,
        name='work_rubric_download',
    ),
    path('work/<int:pk>/package-file/', views.work_package_file, name='work_package_file'),
    path('work/<int:pk>/package-retry/', views.work_package_retry, name='work_package_retry'),
    path('work/<int:pk>/delete/', views.work_delete, name='work_delete'),
    path('results/', views.results, name='results'),
    path('work/<int:pk>/results/', views.work_results, name='work_results'),
    path('work/<int:pk>/export/', views.work_results, {'export': True}, name='work_export'),
]
