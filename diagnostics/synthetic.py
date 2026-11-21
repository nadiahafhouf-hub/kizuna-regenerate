"""Bloc 1 — générateur de parcelles réalistes (vérité terrain synthétique).

Sert à : (1) tester l'IDW contre une « vraie » carte connue ; (2) mesurer l'erreur selon
le nombre de points → justifier la règle du plan de capteurs ; (3) simuler les mesures
d'une parcelle pour la démo (bouton « Simulate readings »).

Hypothèses (sources) :
- Niveau de fond selon la distance à la source de pollution (ordres de grandeur publiés
  pour Gabès, cf. base RAG : < 1 km Cd > 10 mg/kg, 1–3 km 5–10, 3–8 km 2–5, > 8 km < 2 ;
  CE 2–18 dS/m ; Pb jusqu'à ~150 mg/kg) :
      Cd(d) = 0.3 + 14·e^(−d/3)     CE(d) = 2.5 + 13·e^(−d/4)     Pb(d) = 20 + 120·e^(−d/3)
- Vent dominant de nord-ouest : +35 % sous le vent, −20 % au vent.
- pH et texture de fond : tirés des points LUCAS méditerranéens calcaires
  (fixtures/bloc1/lucas_med_calcaire.csv ; repli : pH ~ N(8.05, 0.28)).
- Variabilité intra-parcelle : champ aléatoire spatialement corrélé (portée 10–30 m),
  multiplicatif pour Cd/Pb/CE (CV ≈ 35 %), additif pour le pH (σ ≈ 0.2), + 0 à 2 points chauds
  (dépôt de déchets, ancien canal).
"""
import csv
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from django.conf import settings

LUCAS_CSV = Path(settings.BASE_DIR) / "fixtures" / "bloc1" / "lucas_med_calcaire.csv"
VENT_VERS_DEG = 135  # vent de nord-ouest → souffle vers le sud-est


@lru_cache
def _lucas():
    if not LUCAS_CSV.exists():
        return []
    with open(LUCAS_CSV, encoding="utf-8") as f:
        return [{"pH": float(r["pH_in_H2O"]), "texture": r["texture"]} for r in csv.DictReader(f)]


def fond_selon_distance(distance_km, cap_source_vers_parcelle=None):
    """Niveaux de fond (avant variabilité locale) pour une parcelle à `distance_km` de la source."""
    d = max(0.05, distance_km)
    vent = 1.0
    if cap_source_vers_parcelle is not None:
        ecart = math.radians(cap_source_vers_parcelle - VENT_VERS_DEG)
        vent = 1.075 + 0.275 * math.cos(ecart)  # 1.35 sous le vent, 0.80 au vent
    return {
        "Cd_mg_kg": (0.3 + 14 * math.exp(-d / 3)) * vent,
        "CE_dS_m": 2.5 + 13 * math.exp(-d / 4),
        "Pb_mg_kg": (20 + 120 * math.exp(-d / 3)) * vent,
    }


def _champ_correle(rng, nl, nc, taille, portee_m):
    """Champ gaussien N(0,1) spatialement corrélé (bruit blanc lissé par un noyau gaussien)."""
    marge = int(math.ceil(2 * portee_m / taille)) + 1
    bruit = rng.standard_normal((nl + 2 * marge, nc + 2 * marge))
    s = portee_m / taille / 2
    k = np.arange(-marge, marge + 1)
    g = np.exp(-(k ** 2) / (2 * max(s, 0.3) ** 2))
    g /= g.sum()
    lisse = np.apply_along_axis(lambda v: np.convolve(v, g, mode="same"), 0, bruit)
    lisse = np.apply_along_axis(lambda v: np.convolve(v, g, mode="same"), 1, lisse)
    lisse = lisse[marge:marge + nl, marge:marge + nc]
    return (lisse - lisse.mean()) / (lisse.std() + 1e-9)


def generer_parcelle(nl, nc, taille=10, distance_km=2.0, cap=None, seed=None, portee_m=None,
                     cv=0.35, points_chauds=None):
    """Vérité terrain : dict param → tableau (nl × nc) des valeurs au centre de chaque case."""
    rng = np.random.default_rng(seed)
    fond = fond_selon_distance(distance_km, cap)
    lucas = _lucas()
    if lucas:
        bg = lucas[rng.integers(len(lucas))]
        ph0, texture = bg["pH"], bg["texture"]
    else:
        ph0, texture = float(rng.normal(8.05, 0.28)), "sablo-limoneux"
    portee = portee_m or float(rng.uniform(10, 30))
    s = math.sqrt(math.log(1 + cv ** 2))  # écart-type log pour un CV donné

    z_metal = _champ_correle(rng, nl, nc, taille, portee)
    z_sel = 0.6 * z_metal + 0.8 * _champ_correle(rng, nl, nc, taille, portee)  # sel en partie lié
    z_ph = _champ_correle(rng, nl, nc, taille, portee)

    cd = fond["Cd_mg_kg"] * np.exp(s * z_metal - s * s / 2)
    pb = fond["Pb_mg_kg"] * np.exp(0.8 * s * z_metal - (0.8 * s) ** 2 / 2)
    ce = fond["CE_dS_m"] * np.exp(s * z_sel - s * s / 2)
    ph = ph0 + 0.2 * z_ph

    # points chauds (dépôt local) : bosse gaussienne de rayon 5–15 m
    n_hot = rng.integers(0, 3) if points_chauds is None else points_chauds
    yy, xx = np.mgrid[0:nl, 0:nc]
    for _ in range(n_hot):
        l0, c0 = rng.uniform(0, nl), rng.uniform(0, nc)
        r = rng.uniform(5, 15) / taille
        bosse = np.exp(-((yy + 0.5 - l0) ** 2 + (xx + 0.5 - c0) ** 2) / (2 * r * r))
        amp = rng.uniform(0.8, 2.0)
        cd *= 1 + amp * bosse
        pb *= 1 + 0.6 * amp * bosse

    return {"Cd_mg_kg": cd, "Pb_mg_kg": pb, "CE_dS_m": ce, "pH": ph,
            "texture": texture, "portee_m": portee, "fond": fond}


def mesurer(verite, cases, rng=None, bruit_cd=0.15, bruit_ce=0.08, bruit_ph=0.1, bruit_pb=0.08):
    """Simule les relevés aux cases données (erreurs d'appareil : XRF ±15 % sur Cd, etc.)."""
    rng = rng or np.random.default_rng()
    out = []
    for (l, c) in cases:
        out.append({
            "ligne": l, "col": c,
            "Cd_mg_kg": round(max(0.05, verite["Cd_mg_kg"][l, c] * rng.normal(1, bruit_cd)), 2),
            "Pb_mg_kg": round(max(1.0, verite["Pb_mg_kg"][l, c] * rng.normal(1, bruit_pb)), 1),
            "CE_dS_m": round(max(0.1, verite["CE_dS_m"][l, c] * rng.normal(1, bruit_ce)), 2),
            "pH": round(float(verite["pH"][l, c] + rng.normal(0, bruit_ph)), 2),
        })
    return out
