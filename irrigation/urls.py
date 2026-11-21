from django.urls import path

from . import views

app_name = "irrigation"
urlpatterns = [
    path("", views.index, name="index"),
]
