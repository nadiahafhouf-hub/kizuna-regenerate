"""Bloc 1 — interpolation IDW (inverse distance weighting) avec niveau de confiance.

- Une case qui contient un point de mesure garde la valeur mesurée (source « capteur »).
- Les autres cases reçoivent la moyenne des mesures pondérée par 1 / distance^p (source « idw »).
- Confiance d'une case interpolée : décroît avec la distance au point le plus proche,
  rapportée à l'espacement moyen des points (√(surface / n)).
- Validation croisée « leave-one-out » : on retire chaque point, on le prédit avec les
  autres → erreur moyenne ; sert à choisir la puissance p et à afficher la fiabilité.
"""
import math

import numpy as np

PARAMS = ("CE_dS_m", "pH", "Cd_mg_kg", "Pb_mg_kg")


def _xy(ligne, col, taille):
    return (col + 0.5) * taille, (ligne + 0.5) * taille


def idw_valeur(points_xy, valeurs, x, y, puissance=2.0):
    d = np.hypot(points_xy[:, 0] - x, points_xy[:, 1] - y)
    if np.any(d < 1e-9):
        return float(valeurs[np.argmin(d)])
    w = 1.0 / d ** puissance
    return float(np.sum(w * valeurs) / np.sum(w))


def loocv(mesures, param, taille=10, puissance=2.0):
    """Erreur absolue moyenne (MAE) et RMSE en validation croisée leave-one-out."""
    if len(mesures) < 3:
        return None
    xy = np.array([_xy(m["ligne"], m["col"], taille) for m in mesures], dtype=float)
    v = np.array([float(m[param]) for m in mesures])
    err = []
    for i in range(len(mesures)):
        keep = np.arange(len(mesures)) != i
        err.append(idw_valeur(xy[keep], v[keep], xy[i, 0], xy[i, 1], puissance) - v[i])
    err = np.array(err)
    return {"mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2)))}


def meilleure_puissance(mesures, param="Cd_mg_kg", taille=10, choix=(1.0, 1.5, 2.0, 3.0)):
    scores = {p: loocv(mesures, param, taille, p) for p in choix}
    scores = {p: s for p, s in scores.items() if s}
    if not scores:
        return 2.0
    return min(scores, key=lambda p: scores[p]["rmse"])


def niveau_confiance(score):
    return "HAUTE" if score >= 0.7 else "MOYENNE" if score >= 0.4 else "FAIBLE"


def interpoler_grille(mesures, nb_lignes, nb_colonnes, taille=10, puissance=None):
    """Renvoie une liste de cases {ligne, col, source, confiance, CE_dS_m, pH, Cd_mg_kg, Pb_mg_kg}.
    `mesures` : [{ligne, col, CE_dS_m, pH, Cd_mg_kg, Pb_mg_kg}, …] (plusieurs mesures sur la
    même case sont moyennées)."""
    if not mesures:
        raise ValueError("Aucune mesure : impossible d'interpoler.")
    # moyenne des mesures par case
    par_case = {}
    for m in mesures:
        par_case.setdefault((m["ligne"], m["col"]), []).append(m)
    pts = [{"ligne": l, "col": c, **{p: float(np.mean([float(x[p]) for x in ms])) for p in PARAMS}}
           for (l, c), ms in par_case.items()]

    if puissance is None:
        puissance = meilleure_puissance(pts, "Cd_mg_kg", taille)
    xy = np.array([_xy(p["ligne"], p["col"], taille) for p in pts], dtype=float)
    vals = {p: np.array([pt[p] for pt in pts]) for p in PARAMS}
    espacement = math.sqrt(nb_lignes * nb_colonnes * taille * taille / len(pts))

    cases = []
    for l in range(nb_lignes):
        for c in range(nb_colonnes):
            x, y = _xy(l, c, taille)
            dmin = float(np.min(np.hypot(xy[:, 0] - x, xy[:, 1] - y)))
            mesuree = (l, c) in par_case
            score = 1.0 if mesuree else max(0.0, min(1.0, 1 - dmin / (1.5 * espacement)))
            case = {"ligne": l, "col": c, "source": "capteur" if mesuree else "idw",
                    "confiance": round(score, 2), "niveau_confiance": niveau_confiance(score)}
            for p in PARAMS:
                v = idw_valeur(xy, vals[p], x, y, puissance)
                case[p] = round(v, 2) if p != "Pb_mg_kg" else round(v, 1)
            cases.append(case)
    validation = {p: loocv(pts, p, taille, puissance) for p in PARAMS}
    return cases, {"puissance": puissance, "nb_points": len(pts),
                   "espacement_m": round(espacement, 1), "validation_croisee": validation}
