from django.contrib import admin

from .models import (IrrigationEvent, IrrigationPlan, IrrigationSettings, SoilMoistureReading, ValveEvent,
                     ValveState)

admin.site.register(IrrigationPlan)
admin.site.register(ValveEvent)


@admin.register(IrrigationSettings)
class IrrigationSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):   # une seule ligne de parametres
        return not IrrigationSettings.objects.exists()


@admin.register(IrrigationEvent)
class IrrigationEventAdmin(admin.ModelAdmin):
    list_display = ("plan", "date", "heure", "zone_id", "type", "volume_l", "statut", "raison")
    list_filter = ("type", "statut", "zone_id")


admin.site.register(ValveState)
admin.site.register(SoilMoistureReading)
