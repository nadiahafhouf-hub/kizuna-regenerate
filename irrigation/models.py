from django.db import models

from core.models import Parcel


class IrrigationPlan(models.Model):
    """Bloc 3 : planning 7 jours proposé par l'agent, validé par l'agriculteur."""

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Proposé par l'agent"
        VALIDE = "VALIDE", "Validé par l'agriculteur"
        AUTO = "AUTO", "Mode automatique"
        MANUEL = "MANUEL", "Repris en main par l'agriculteur"
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
    # Planning calculé (irrigation.services.planning) : jours, réservoir, totaux, paramètres
    quota_m3 = models.FloatField(null=True, blank=True)
    meteo = models.JSONField(default=dict, blank=True)          # gardée pour recalculer sans rappeler l'API
    volumes_forces = models.JSONField(default=dict, blank=True)  # {"Z3|2026-11-22": litres} modifiés à la main
    horloge = models.DateTimeField(null=True, blank=True)        # horloge simulée de la démo
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

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


class IrrigationEvent(models.Model):
    """Événement du planning : POMPAGE (nappe -> réservoir) ou ARROSAGE (réservoir -> zone), avec sa raison."""

    class Type(models.TextChoices):
        POMPAGE = "POMPAGE", "Pompage"
        ARROSAGE = "ARROSAGE", "Arrosage"

    class Statut(models.TextChoices):
        PREVU = "PREVU", "Prévu"
        FAIT = "FAIT", "Fait"
        ANNULE = "ANNULE", "Annulé"

    plan = models.ForeignKey(IrrigationPlan, on_delete=models.CASCADE, related_name="programme")
    zone_id = models.CharField(max_length=20)
    couleur = models.CharField(max_length=10, blank=True)
    date = models.DateField()
    heure = models.TimeField()
    type = models.CharField(max_length=10, choices=Type.choices)
    volume_l = models.IntegerField()
    volume_prevu_l = models.IntegerField(default=0)
    energie_kwh = models.FloatField(default=0)
    statut = models.CharField(max_length=8, choices=Statut.choices)
    raison = models.TextField(blank=True)
    ordre = models.IntegerField(default=0)
    traite_le = models.DateTimeField(null=True, blank=True)    # heure simulée du traitement

    class Meta:
        ordering = ["date", "heure", "ordre"]

    def __str__(self):
        return f"{self.date} {self.heure:%H:%M} {self.zone_id} {self.type} {self.volume_l} L [{self.statut}]"


class ValveState(models.Model):
    """État d'une vanne (une par zone)."""
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="vannes")
    zone_id = models.CharField(max_length=20)
    ouverte = models.BooleanField(default=False)
    derniere_action = models.CharField(max_length=200, blank=True)
    mise_a_jour = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("parcel", "zone_id")]
        ordering = ["zone_id"]

    def __str__(self):
        return f"{self.parcel.parcelle_id} V-{self.zone_id} {'ouverte' if self.ouverte else 'fermée'}"


class SoilMoistureReading(models.Model):
    """Capteur d'humidité du sol SIMULÉ, lu juste avant chaque arrosage."""
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="humidites")
    zone_id = models.CharField(max_length=20)
    humidite_pct = models.FloatField()
    horodatage = models.DateTimeField()
    simulee = models.BooleanField(default=True)

    class Meta:
        ordering = ["-horodatage"]


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
