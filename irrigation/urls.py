from django.urls import path

from . import views

app_name = "irrigation"
urlpatterns = [
    path("", views.index, name="index"),
    path("approve/", views.approve, name="approve"),
    path("reset/", views.reset, name="reset"),
]
