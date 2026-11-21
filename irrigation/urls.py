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
    # Réseau goutte-à-goutte optimal (image satellite automatique ou photo)
    path("network/", views.network_page, name="network"),
    path("network/preview/", views.network_preview, name="network_preview"),
    path("network/recompute/", views.network_recompute, name="network_recompute"),
    path("network/geojson/", views.network_geojson, name="network_geojson"),
    path("network/api/", views.network_api, name="network_api"),
    path("network/card/", views.network_card, name="network_card"),  # page Crops, « Already planted »
]
