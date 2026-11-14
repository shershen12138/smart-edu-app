from django.urls import path

from . import common_views as views
from . import llm_views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('llm-config/', llm_views.llm_config, name='llm_config'),
    path('llm-config/clear/', llm_views.llm_config_clear, name='llm_config_clear'),
]
