from django.contrib import admin

from .models import LandProfile, SensorReading

admin.site.register(SensorReading)
admin.site.register(LandProfile)
