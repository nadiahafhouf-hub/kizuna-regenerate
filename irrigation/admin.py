from django.contrib import admin

from .models import DripNetworkPlan, IrrigationPlan, ValveEvent

admin.site.register(IrrigationPlan)
admin.site.register(ValveEvent)


@admin.register(DripNetworkPlan)
class DripNetworkPlanAdmin(admin.ModelAdmin):
    list_display = ("parcelle_id", "statut", "economie_pct", "created_at")
    list_filter = ("statut",)
