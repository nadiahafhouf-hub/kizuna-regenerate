from django.urls import path

from . import views

app_name = "diagnostics"
urlpatterns = [
    path("", views.index, name="index"),
    path("case/<int:ligne>/<int:col>/", views.case, name="case"),
    path("sensors/", views.sensors_list, name="sensors"),
    path("readings/new/", views.new_reading, name="new_reading"),
    path("plan/", views.plan, name="plan"),
    path("plan/simulate/", views.simulate, name="simulate"),
    path("campaign/", views.readings, name="readings"),
]
