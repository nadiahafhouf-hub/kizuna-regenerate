"""Pipeline du bloc 1 : mesures → grille 10 m → IDW → couleur → zones → traitement.

Squelette à compléter sur la branche bloc-1. Les signatures sont fixées pour que les
autres blocs puissent s'appuyer dessus ; en attendant, utilisez contract.load_sample().
"""
from .couleur import couleur_case  # noqa: F401  (seule source de vérité pour la couleur)


def construire_grille(parcel):
    """Renvoie la liste des (ligne, col) de la parcelle selon taille_case_m."""
    return [(l, c) for l in range(parcel.nb_lignes) for c in range(parcel.nb_colonnes)]


def interpoler_idw(mesures, ligne, col, puissance=2):
    """Interpolation IDW des 4 paramètres (CE, pH, Cd, Pb) au centre de la case."""
    raise NotImplementedError("bloc-1")


def regrouper_zones(cases, max_zones=3):
    """Regroupe les cases en 1 à 3 zones (par couleur, puis par contiguïté)."""
    raise NotImplementedError("bloc-1")


def construire_land_profile(parcel, mesures, date_mesure):
    """Assemble le dict LandProfile conforme au contrat (fixtures/land_profile.sample.json).
    Le traitement de chaque zone vient de services.traitement.traitement_zone()."""
    raise NotImplementedError("bloc-1")
