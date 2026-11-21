from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("demo/", views.load_demo, name="load_demo"),
    path("chat/", views.chat, name="chat"),
]
