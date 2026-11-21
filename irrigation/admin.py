from django.contrib import admin

from .models import IrrigationPlan, ValveEvent

admin.site.register(IrrigationPlan)
admin.site.register(ValveEvent)
