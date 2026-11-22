from django.urls import path

from . import views

app_name = "energy"
urlpatterns = [
    path("", views.index, name="index"),
    path("clean/", views.nettoye, name="clean"),
    path("alerts/read/", views.alertes_lues, name="alerts_read"),
]
