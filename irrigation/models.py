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


class IrrigationSettings(models.Model):
    """Parametres du systeme d'irrigation (une seule ligne, modifiable dans l'admin)."""
    puissance_pompe_kw = models.FloatField(default=0.75)
    debit_pompe_m3_h = models.FloatField(default=1.5)
    puissance_crete_kwc = models.FloatField(
        default=2.0, help_text="Avec 1,0 kWc x 0,8 la production max est 0,8 kW : la pompe de 0,75 kW "
                               "ne demarre que si le rayonnement >= 938 W/m2 (jamais en hiver).")
    ratio_performance = models.FloatField(default=0.8)
    capacite_reservoir_m3 = models.FloatField(default=5.0)
    niveau_initial_m3 = models.FloatField(default=2.5, help_text="eau dans le reservoir au debut de la semaine")
    quota_nappe_m3_semaine = models.FloatField(default=15.0)
    seuil_pluie_mm = models.FloatField(default=5.0, help_text="pluie prevue qui annule un arrosage")
    seuil_humidite_pct = models.FloatField(default=30.0, help_text="humidite du sol qui fait sauter un arrosage")
    heure_arrosage = models.PositiveSmallIntegerField(default=6)
    debit_goutte_m3_h = models.FloatField(default=3.0, help_text="debit par gravite quand une vanne est ouverte")
    rendement_submersion = models.FloatField(default=0.6, help_text="arrosage traditionnel (comparaison)")
    ce_eau_dS_m = models.FloatField(
        null=True, blank=True, verbose_name="CE de l'eau d'irrigation (dS/m)",
        help_text="Vide = valeur de la recommandation (LandProfile, sinon valeur typique de la region).")

    class Meta:
        verbose_name = verbose_name_plural = "Parametres d'irrigation"

    def __str__(self):
        return "Parametres d'irrigation"

    @classmethod
    def charger(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def en_dict(self):
        return {f.name: getattr(self, f.name) for f in self._meta.fields if f.name != "id"}
