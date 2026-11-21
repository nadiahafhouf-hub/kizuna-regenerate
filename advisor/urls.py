from django.urls import path

from . import views

app_name = "advisor"
urlpatterns = [
    path("", views.index, name="index"),
    path("mode/", views.set_mode, name="mode"),
    path("score/", views.score, name="score"),
]
