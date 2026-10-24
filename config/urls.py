from django.urls import include, path

from school import views as auth

urlpatterns = [
    path('login/', auth.login_view, name='login'),
    path('logout/', auth.logout_view, name='logout'),
    path('password/', auth.password_view, name='password'),
    path('health/', auth.health, name='health'),
    path('', include('school.portal.urls_common')),
    path('', include('school.portal.urls_administration')),
    path('', include('school.portal.urls_teaching')),
    path('', include('school.portal.urls_learning')),
]
