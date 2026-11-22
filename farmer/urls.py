from django.urls import path

from . import views

app_name = "farmer"
urlpatterns = [
    path("", views.home, name="home"),
    path("<str:pid>/water/", views.water, name="water"),
    path("<str:pid>/soil/", views.soil, name="soil"),
    path("<str:pid>/plants/", views.plants, name="plants"),
    path("<str:pid>/sun/", views.sun, name="sun"),
    path("<str:pid>/certificate/", views.certificate, name="certificate"),
]
