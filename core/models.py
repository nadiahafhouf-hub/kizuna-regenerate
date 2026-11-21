from django.db import models


class Parcel(models.Model):
    """Parcelle agricole. L'origine est un coin de la parcelle (par défaut nord-ouest) :
    les lignes de la grille avancent vers le sud, les colonnes vers l'est."""

    class PointOrigine(models.TextChoices):
        NORD_OUEST = "coin_nord_ouest", "Coin nord-ouest"
        NORD_EST = "coin_nord_est", "Coin nord-est"
        SUD_OUEST = "coin_sud_ouest", "Coin sud-ouest"
        SUD_EST = "coin_sud_est", "Coin sud-est"

    parcelle_id = models.CharField(max_length=32, unique=True)  # ex. GAB-001
    nom = models.CharField(max_length=120, blank=True)
    agriculteur = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=80, default="Gabes")
    origine_lat = models.FloatField()
    origine_lon = models.FloatField()
    origine_point = models.CharField(max_length=20, choices=PointOrigine.choices,
                                     default=PointOrigine.NORD_OUEST)
    largeur_m = models.PositiveIntegerField()
    longueur_m = models.PositiveIntegerField()
    taille_case_m = models.PositiveIntegerField(default=10)
    texture_sol = models.CharField(max_length=40, blank=True)  # ex. sablo-limoneux
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["parcelle_id"]

    def __str__(self):
        return f"{self.parcelle_id} {self.nom}".strip()

    @property
    def nb_lignes(self):
        return -(-self.longueur_m // self.taille_case_m)

    @property
    def nb_colonnes(self):
        return -(-self.largeur_m // self.taille_case_m)


class PollutionSource(models.Model):
    """Source de pollution configurable (usine, décharge, route...), pas seulement Gabès."""

    class TypeSource(models.TextChoices):
        INDUSTRIE = "INDUSTRIE", "Industrie"
        DECHARGE = "DECHARGE", "Décharge"
        ROUTE = "ROUTE", "Route / trafic"
        EAUX_USEES = "EAUX_USEES", "Eaux usées"
        AUTRE = "AUTRE", "Autre"

    nom = models.CharField(max_length=120)  # ex. Groupe Chimique Tunisien (GCT)
    type_source = models.CharField(max_length=20, choices=TypeSource.choices,
                                   default=TypeSource.INDUSTRIE)
    region = models.CharField(max_length=80, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    rayon_influence_km = models.FloatField(default=5.0)
    polluants = models.JSONField(default=list, blank=True)  # ex. ["Cd", "Pb", "F"]
    actif = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["region", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.region})" if self.region else self.nom
