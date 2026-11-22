"""Volet photovoltaïque. Les parcelles sont référencées par leur identifiant (GAB-001, KZ-002…) :
ça marche aussi pour les parcelles de démo, qui ne sont pas en base."""
from django.db import models


class ConfigSolaire(models.Model):
    """Paramètres saisis par l'agriculteur pour dimensionner son installation."""
    parcelle_id = models.CharField(max_length=32, unique=True)
    profondeur_m = models.FloatField(default=40.0, help_text="profondeur de pompage (niveau de l'eau dans le puits)")
    panneau_wc = models.PositiveIntegerField(default=450)
    plantes = models.JSONField(default=dict, blank=True, help_text="{zone_id: nombre de plantes} (vide = bloc 2)")
    modifie_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Config solaire {self.parcelle_id}"


class Nettoyage(models.Model):
    parcelle_id = models.CharField(max_length=32, db_index=True)
    date = models.DateField()
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]


class MesurePV(models.Model):
    """Mesure envoyée par l'ESP32 (capteur de courant/tension INA226 + rayonnement facultatif)."""
    parcelle_id = models.CharField(max_length=32, db_index=True)
    horodatage = models.DateTimeField()
    puissance_w = models.FloatField()
    poa_w_m2 = models.FloatField(null=True, blank=True)
    t_air_c = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["horodatage"]
        unique_together = [("parcelle_id", "horodatage")]


class Alerte(models.Model):
    class Type(models.TextChoices):
        NETTOYER = "NETTOYER", "Nettoyer les panneaux"
        PREVOIR = "PREVOIR", "Nettoyage à prévoir"
        TECHNICIEN = "TECHNICIEN", "Panne probable : technicien"

    class Niveau(models.TextChoices):
        INFO = "INFO", "Info"
        ATTENTION = "ATTENTION", "Attention"
        ALERTE = "ALERTE", "Alerte"

    parcelle_id = models.CharField(max_length=32, db_index=True)
    type = models.CharField(max_length=12, choices=Type.choices)
    niveau = models.CharField(max_length=10, choices=Niveau.choices)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    lue = models.BooleanField(default=False)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.parcelle_id} {self.type} {self.cree_le:%Y-%m-%d}"
