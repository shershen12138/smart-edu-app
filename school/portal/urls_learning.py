from django.urls import path

from . import learning_views as views

urlpatterns = [
    path('work/<int:pk>/', views.work_detail, name='work'),
    path('work/<int:pk>/file/<str:kind>/', views.work_file, name='work_file'),
    path('entries/<int:pk>/', views.entry_detail, name='entry'),
    path('entries/<int:pk>/source/', views.entry_detail, {'download': True}, name='entry_source'),
    path('entries/<int:pk>/retry/', views.entry_retry, name='entry_retry'),
]
