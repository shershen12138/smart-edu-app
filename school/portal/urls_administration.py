from django.urls import path

from . import administration_views as views

urlpatterns = [
    path('archives/', views.archives, name='archives'),
    path('teachers/', views.people, {'kind': 'teacher'}, name='teachers'),
    path('students/', views.people, {'kind': 'student'}, name='students'),
    path('accounts/<str:kind>/new/', views.person_edit, name='person_new'),
    path('accounts/<str:kind>/<int:pk>/', views.person_edit, name='person_edit'),
    path('accounts/<str:kind>/<int:pk>/delete/', views.person_delete, name='person_delete'),
    path('teachers/<int:pk>/grants/', views.teacher_grants, name='teacher_grants'),
    path('students/batch/', views.students_batch, name='students_batch'),
    path('students/import/', views.students_import, name='students_import'),
    path('students/template/', views.students_template, name='students_template'),
    path('classes/', views.classes, name='classes'),
    path('classes/new/', views.class_edit, name='class_new'),
    path('classes/<int:pk>/', views.class_detail, name='class_detail'),
    path('classes/<int:pk>/edit/', views.class_edit, name='class_edit'),
    path('classes/<int:pk>/delete/', views.class_delete, name='class_delete'),
    path('dictionaries/', views.dictionaries, name='dictionaries'),
    path('dictionaries/new/', views.dictionary_edit, name='dictionary_new'),
    path('dictionaries/<int:pk>/', views.dictionary_items, name='dictionary_items'),
    path('dictionaries/<int:pk>/edit/', views.dictionary_edit, name='dictionary_edit'),
    path('dictionaries/<int:pk>/delete/', views.dictionary_delete, name='dictionary_delete'),
    path(
        'dictionaries/<int:pk>/items/new/',
        views.dictionary_item_edit,
        name='dictionary_item_new',
    ),
    path(
        'dictionaries/<int:pk>/items/<int:item_id>/',
        views.dictionary_item_edit,
        name='dictionary_item_edit',
    ),
    path(
        'dictionaries/<int:pk>/items/<int:item_id>/delete/',
        views.dictionary_delete,
        name='dictionary_item_delete',
    ),
]
