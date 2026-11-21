from django.db import models

from core.models import Parcel


class CropAssessment(models.Model):
    """Bloc 2 : réponse au pop-up « terre nue ou plantée » pour une zone de la parcelle."""

    class Etat(models.TextChoices):
        NUE = "NUE", "Terre nue"
        PLANTEE = "PLANTEE", "Terre plantée"

    class TypeIrrigation(models.TextChoices):
        GOUTTE_A_GOUTTE = "GOUTTE_A_GOUTTE", "Goutte-à-goutte"
        ASPERSION = "ASPERSION", "Aspersion"
        GRAVITAIRE = "GRAVITAIRE", "Gravitaire / submersion"
        AUCUNE = "AUCUNE", "Aucune (pluvial)"

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="evaluations")
    zone_id = models.CharField(max_length=8, blank=True)  # ex. Z1 (cf. LandProfile.zones)
    etat = models.CharField(max_length=10, choices=Etat.choices)
    # Terre plantée
    photo = models.ImageField(upload_to="advisor/photos/", null=True, blank=True)
    analyse_photo = models.JSONField(default=dict, blank=True)  # réponse JSON de Gemini Vision
    culture = models.CharField(max_length=80, blank=True)
    espacement_m = models.FloatField(null=True, blank=True)
    type_irrigation = models.CharField(max_length=20, choices=TypeIrrigation.choices, blank=True)
    score_optimalite = models.FloatField(null=True, blank=True)  # 0-100
    # Détail du score (compatibilité zone, tolérance CE, espacement, besoin en eau)
    # ou, pour une terre nue, la liste des cultures recommandées.
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.parcel.parcelle_id} {self.zone_id} {self.etat}"
