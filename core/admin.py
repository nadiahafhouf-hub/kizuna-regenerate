from django.contrib import admin

from .models import Parcel, PollutionSource


@admin.register(Parcel)
class ParcelAdmin(admin.ModelAdmin):
    list_display = ("parcelle_id", "nom", "region", "largeur_m", "longueur_m", "taille_case_m")
    search_fields = ("parcelle_id", "nom", "agriculteur")


@admin.register(PollutionSource)
class PollutionSourceAdmin(admin.ModelAdmin):
    list_display = ("nom", "type_source", "region", "rayon_influence_km", "actif")
    list_filter = ("type_source", "actif")
