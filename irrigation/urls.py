from django.urls import path

from . import views

app_name = "irrigation"
urlpatterns = [
    path("", views.index, name="index"),
    path("approve/", views.approve, name="approve"),
    path("reset/", views.reset, name="reset"),
    # Réseau goutte-à-goutte optimal (image satellite automatique ou photo)
    path("network/", views.network_page, name="network"),
    path("network/preview/", views.network_preview, name="network_preview"),
    path("network/recompute/", views.network_recompute, name="network_recompute"),
    path("network/geojson/", views.network_geojson, name="network_geojson"),
    path("network/api/", views.network_api, name="network_api"),
]
