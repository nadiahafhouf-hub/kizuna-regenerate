from django.db import models

from core.models import Parcel


class IrrigationPlan(models.Model):
    """Bloc 3 : planning 7 jours proposé par l'agent, validé par l'agriculteur."""

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Proposé par l'agent"
        VALIDE = "VALIDE", "Validé par l'agriculteur"
        AUTO = "AUTO", "Mode automatique"
        ARRETE = "ARRETE", "Arrêté"

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="plans_irrigation")
    zone_id = models.CharField(max_length=8, blank=True)
    culture = models.CharField(max_length=80)
    date_debut = models.DateField()
    # Liste de 7 jours : [{"date", "et0_mm", "kc", "besoin_mm", "volume_l",
    #                      "heure_irrigation", "lessivage"}, ...]
    planning = models.JSONField(default=list)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    valide_le = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.parcel.parcelle_id} {self.culture} {self.date_debut} [{self.statut}]"


class ValveEvent(models.Model):
    """Journal de la vanne simulée et de la pompe solaire."""

    class Action(models.TextChoices):
        POMPAGE_RESERVOIR = "POMPAGE_RESERVOIR", "Pompage vers réservoir (midi, solaire)"
        OUVERTURE = "OUVERTURE", "Ouverture vanne (irrigation)"
        FERMETURE = "FERMETURE", "Fermeture vanne"

    class Energie(models.TextChoices):
        SOLAIRE = "SOLAIRE", "Panneau solaire"
        RESERVOIR = "RESERVOIR", "Gravité depuis réservoir"

    plan = models.ForeignKey(IrrigationPlan, on_delete=models.CASCADE, related_name="evenements")
    horodatage = models.DateTimeField()
    action = models.CharField(max_length=20, choices=Action.choices)
    volume_l = models.FloatField(default=0)
    energie = models.CharField(max_length=10, choices=Energie.choices, default=Energie.SOLAIRE)

    class Meta:
        ordering = ["horodatage"]

    def __str__(self):
        return f"{self.horodatage:%Y-%m-%d %H:%M} {self.action} {self.volume_l:.0f} L"
