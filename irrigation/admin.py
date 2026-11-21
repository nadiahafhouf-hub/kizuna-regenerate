from django.contrib import admin

from .models import IrrigationPlan, ValveEvent, IrrigationSettings

admin.site.register(IrrigationPlan)
admin.site.register(ValveEvent)


@admin.register(IrrigationSettings)
class IrrigationSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):   # une seule ligne de parametres
        return not IrrigationSettings.objects.exists()
