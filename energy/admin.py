from django.contrib import admin

from .models import Alerte, ConfigSolaire, MesurePV, Nettoyage


@admin.register(Alerte)
class AlerteAdmin(admin.ModelAdmin):
    list_display = ("parcelle_id", "type", "niveau", "cree_le", "lue")
    list_filter = ("type", "niveau", "lue")


admin.site.register(ConfigSolaire)
admin.site.register(Nettoyage)
admin.site.register(MesurePV)
