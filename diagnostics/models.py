from django.db import models

from core.models import Parcel


class SensorReading(models.Model):
    """Une mesure capteur ponctuelle. Position en (ligne, col) de la grille OU en lat/lon."""

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="mesures")
    date_mesure = models.DateField()
    ligne = models.PositiveIntegerField(null=True, blank=True)
    col = models.PositiveIntegerField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    ce_ds_m = models.FloatField("CE (dS/m)")
    ph = models.FloatField("pH")
    cd_mg_kg = models.FloatField("Cd (mg/kg)")
    pb_mg_kg = models.FloatField("Pb (mg/kg)")

    class Meta:
        ordering = ["parcel", "date_mesure", "ligne", "col"]

    def __str__(self):
        return f"{self.parcel.parcelle_id} {self.date_mesure} ({self.ligne},{self.col})"


class LandProfile(models.Model):
    """Sortie du bloc 1 : le contrat LandProfile (voir fixtures/land_profile.sample.json).
    Le JSON complet est stocké tel quel dans `data` ; c'est l'entrée des blocs 2, 3 et 4."""

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="profils")
    date_mesure = models.DateField()
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_mesure", "-created_at"]
        get_latest_by = "created_at"

    def __str__(self):
        return f"LandProfile {self.parcel.parcelle_id} {self.date_mesure}"
