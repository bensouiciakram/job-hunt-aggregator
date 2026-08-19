from django.urls import path

from . import views

urlpatterns = [
    path('sources/', views.sources, name='sources'),
    path('sources/<int:pk>/test-fetch/', views.test_fetch, name='test-fetch'),
    path('listings/', views.listings, name='listings'),
]