"""Pipeline du bloc 1 : mesures → grille 10 m → IDW → couleur → zones → traitement → LandProfile.

Entrée minimale : dimensions de la parcelle (rectangle), origine GPS (coin nord-ouest),
mesures des points de relevé. Sortie : dict conforme au contrat
(fixtures/land_profile.sample.json), avec des champs EN PLUS (compatibles) :
cases[].confiance / niveau_confiance, et un bloc « interpolation » (puissance, validation).
"""
from services.traitement import culture_alimentaire_autorisee, traitement_zone

from .couleur import COULEURS, couleur_case
from .idw import interpoler_grille
from .sampling import nb_lignes_colonnes

ORDRE = {c: i for i, c in enumerate(COULEURS)}  # ROUGE, ORANGE, VERT


def construire_grille(parcel):
    """Liste des (ligne, col) de la parcelle selon taille_case_m."""
    return [(l, c) for l in range(parcel.nb_lignes) for c in range(parcel.nb_colonnes)]


def regrouper_zones(cases, taille_m=10, max_zones=3):
    """1 à 3 zones : une par couleur présente (ROUGE → Z1, ORANGE, VERT).
    Le traitement utilise les valeurs les plus défavorables de la zone."""
    zones = []
    for couleur in sorted({c["couleur"] for c in cases}, key=ORDRE.get)[:max_zones]:
        cs = [c for c in cases if c["couleur"] == couleur]
        ph_extreme = max((c["pH"] for c in cs), key=lambda p: abs(p - 7.0))
        zones.append({
            "id": f"Z{len(zones) + 1}",
            "couleur": couleur,
            "cases": [[c["ligne"], c["col"]] for c in cs],
            "surface_m2": len(cs) * taille_m * taille_m,
            "culture_alimentaire_autorisee": culture_alimentaire_autorisee(couleur),
            "traitement": traitement_zone(couleur, max(c["CE_dS_m"] for c in cs), ph_extreme,
                                          max(c["Cd_mg_kg"] for c in cs), max(c["Pb_mg_kg"] for c in cs)),
        })
    return zones


def construire_land_profile(parcelle_id, largeur_m, longueur_m, origine_lat, origine_lon,
                            mesures, date_mesure, region="Gabes", texture_sol="", taille_m=10):
    """Assemble le LandProfile. `mesures` : [{ligne, col, CE_dS_m, pH, Cd_mg_kg, Pb_mg_kg}, …]."""
    nl, nc = nb_lignes_colonnes(largeur_m, longueur_m, taille_m)
    cases, info = interpoler_grille(mesures, nl, nc, taille_m)
    for c in cases:
        c["couleur"] = couleur_case(c["CE_dS_m"], c["pH"], c["Cd_mg_kg"], c["Pb_mg_kg"])
    # ordre des clés du contrat
    cases = [{"ligne": c["ligne"], "col": c["col"], "couleur": c["couleur"], "source": c["source"],
              "CE_dS_m": c["CE_dS_m"], "pH": c["pH"], "Cd_mg_kg": c["Cd_mg_kg"], "Pb_mg_kg": c["Pb_mg_kg"],
              "confiance": c["confiance"], "niveau_confiance": c["niveau_confiance"]} for c in cases]
    return {
        "parcelle_id": parcelle_id,
        "date_mesure": str(date_mesure),
        "region": region,
        "origine": {"lat": origine_lat, "lon": origine_lon, "point": "coin_nord_ouest"},
        "largeur_m": largeur_m,
        "longueur_m": longueur_m,
        "taille_case_m": taille_m,
        "texture_sol": texture_sol,
        "cases": cases,
        "zones": regrouper_zones(cases, taille_m),
        "interpolation": info,
    }


def interpoler_idw(mesures, ligne, col, puissance=2, taille_m=10):
    """Compatibilité avec l'ancienne signature : valeurs IDW des 4 paramètres pour une case."""
    import numpy as np

    from .idw import PARAMS, _xy, idw_valeur
    xy = np.array([_xy(m["ligne"], m["col"], taille_m) for m in mesures], dtype=float)
    x, y = _xy(ligne, col, taille_m)
    return {p: idw_valeur(xy, np.array([float(m[p]) for m in mesures]), x, y, puissance) for p in PARAMS}
