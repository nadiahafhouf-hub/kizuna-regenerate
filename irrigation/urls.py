from django.urls import path

from . import views

app_name = "irrigation"
urlpatterns = [
    path("", views.index, name="index"),
    path("approve/", views.approve, name="approve"),
    path("reset/", views.reset, name="reset"),
    path("plan.json", views.plan_json, name="plan_json"),
    path("passeport.json", views.passeport_json, name="passeport_json"),
    path("etat.json", views.etat_json, name="etat"),
    path("simuler/", views.simuler, name="simuler"),
    path("modifier/", views.modifier, name="modifier"),
    path("action/<str:nom>/", views.action, name="action"),
]
