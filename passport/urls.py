from django.urls import path

from . import views

app_name = "passport"
urlpatterns = [
    path("", views.index, name="index"),
    path("pdf/", views.pdf, name="pdf"),
]
