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


class DripNetworkPlan(models.Model):
    """Bloc 3 : réseau goutte-à-goutte optimal calculé par services.irrigation_engine à partir du
    LandProfile (zones, sol, pollution) et d'une vue du dessus : image satellite téléchargée
    automatiquement depuis l'origine GPS, ou photo envoyée par l'agriculteur."""

    class Statut(models.TextChoices):
        EN_COURS = "EN_COURS", "En cours"
        OK = "OK", "Terminé"
        ERREUR = "ERREUR", "Erreur"

    parcelle_id = models.CharField(max_length=32, db_index=True)  # ex. GAB-001 (comme les pages /p/<pid>/)
    land_profile = models.JSONField(help_text="LandProfile utilisé (copie figée)")
    photo = models.FileField(upload_to="irrigation/network/photos/%Y/%m/", blank=True, null=True,
                             help_text="Image satellite téléchargée (<parcelle_id>_satellite.png) ou photo envoyée")
    calage = models.JSONField(default=dict, blank=True,
                              help_text='{"mode":"satellite"|"coins"|"ortho", "coins_px":[NO,NE,SE,SO], ...}')
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.EN_COURS)
    message = models.TextField(blank=True)
    resultat = models.JSONField(null=True, blank=True)
    geojson = models.JSONField(null=True, blank=True)
    image_trace = models.FileField(upload_to="irrigation/network/results/%Y/%m/", blank=True, null=True,
                                   help_text="Réseau optimal tracé sur l'image d'origine")
    image_photo_analysee = models.FileField(upload_to="irrigation/network/results/%Y/%m/", blank=True, null=True)
    image_plan = models.FileField(upload_to="irrigation/network/results/%Y/%m/", blank=True, null=True)
    rapport = models.FileField(upload_to="irrigation/network/results/%Y/%m/", blank=True, null=True)
    conso_actuelle_m3_an = models.FloatField(null=True, blank=True)
    conso_optimale_m3_an = models.FloatField(null=True, blank=True)
    economie_pct = models.FloatField(null=True, blank=True)
    heures_pompage_pointe = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.parcelle_id} réseau {self.created_at:%Y-%m-%d %H:%M} [{self.statut}]"

    @property
    def conseil(self):
        return (self.resultat or {}).get("conseil_simple", [])

    @property
    def source_image(self):
        return ((self.resultat or {}).get("photo") or {}).get("source_image")
