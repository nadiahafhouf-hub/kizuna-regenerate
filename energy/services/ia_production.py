"""IA 1 — « Combien les panneaux DEVRAIENT-ils produire s'ils étaient propres ? »

Entraîné et testé sur de VRAIES données : NREL PVDAQ système 4 (1 kWc, mesures horaires).
- Entrées : rayonnement dans le plan des panneaux (W/m²) et température de l'air (°C), comme ce que
  fournissent Open-Meteo (global_tilted_irradiance) ou un capteur ESP32 bon marché.
- Sortie : puissance AC pour 1 kWc installé (W/kWc) → multipliée par la puissance de l'installation.
- Modèle : gradient boosting (scikit-learn), comparé à la formule physique classique « PVWatts »
  (P = kWc · G/1000 · (1 + γ (T_cellule − 25)) · rendement système), dont le rendement est ajusté.
- Validation honnête : entraînement sur 2010-2012, test sur 2013 (année jamais vue).

Sur l'installation de l'agriculteur, le modèle est ensuite CALIBRÉ sur ses premiers jours propres
(rapport médian mesuré / attendu) : il apprend les particularités du site (ombre, onduleur…).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings

MODELE = Path(settings.BASE_DIR) / "energy" / "ml_models" / "production.joblib"
METRIQUES = Path(settings.BASE_DIR) / "fixtures" / "energy" / "ia1_metriques.json"
FEATURES = ["poa_w_m2", "t_air_c", "hauteur_soleil"]
SITE_NREL = {"lat": 39.74, "lon": -105.18, "utc": -7}   # Golden, Colorado (heure locale standard)


def hauteur_soleil(index, lat, lon, utc_offset_h):
    """Hauteur du soleil (degrés) au milieu de chaque heure locale (formule NOAA simplifiée)."""
    t = pd.DatetimeIndex(index) + pd.Timedelta(minutes=30) - pd.Timedelta(hours=utc_offset_h)
    j = t.dayofyear.values
    h = t.hour.values + t.minute.values / 60
    g = 2 * np.pi / 365 * (j - 1 + (h - 12) / 24)
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    eq = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g) - 0.014615 * np.cos(2 * g)
                   - 0.040849 * np.sin(2 * g))
    angle_h = np.radians((h * 60 + eq + 4 * lon) / 4 - 180)
    la = np.radians(lat)
    sin_el = np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(angle_h)
    return np.degrees(np.arcsin(np.clip(sin_el, -1, 1)))
GAMMA = -0.004   # coefficient de température du silicium cristallin (/°C)
NOCT = 45


def nettoyer(df):
    """Heures de jour fiables : retire nuit, capteurs aberrants, neige / pannes (puissance anormalement basse)."""
    d = df.dropna(subset=["ac_power_w", "poa_w_m2", "t_air_c"]).copy()
    d["hauteur_soleil"] = hauteur_soleil(d.index, **{k: SITE_NREL[k] for k in ("lat", "lon")}, utc_offset_h=SITE_NREL["utc"])
    d = d[(d.t_air_c > -40) & (d.t_air_c < 55) & (d.poa_w_m2 > 50) & (d.poa_w_m2 < 1400) & (d.ac_power_w > 0)]
    ratio = d.ac_power_w / d.poa_w_m2
    med = ratio.rolling(24 * 7, min_periods=10, center=True).median()
    return d[ratio > 0.5 * med]   # neige sur les modules, coupure réseau…


def pvwatts(poa, t_air, rendement):
    t_cell = t_air + poa / 800 * (NOCT - 20)
    return 1000 * poa / 1000 * (1 + GAMMA * (t_cell - 25)) * rendement


def _scores(y, p, index):
    err = p - y
    jour_vrai = pd.Series(y, index=index).resample("1D").sum()
    jour_pred = pd.Series(p, index=index).resample("1D").sum()
    ok = jour_vrai > 500   # journées avec une production significative (Wh/kWc)
    return {
        "r2": round(float(1 - np.sum(err ** 2) / np.sum((y - y.mean()) ** 2)), 3),
        "mae_w_par_kwc": round(float(np.mean(np.abs(err))), 1),
        "nrmse_pct": round(float(100 * np.sqrt(np.mean(err ** 2)) / y.mean()), 1),
        "erreur_energie_jour_pct": round(float(100 * np.median(np.abs(jour_pred[ok] - jour_vrai[ok]) / jour_vrai[ok])), 1),
    }


def entrainer(df):
    from sklearn.ensemble import HistGradientBoostingRegressor
    d = nettoyer(df)
    train, test = d[d.index.year.isin([2010, 2011, 2012])], d[d.index.year == 2013]
    modele = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, random_state=0)
    modele.fit(train[FEATURES], train.ac_power_w)
    p_ml = modele.predict(test[FEATURES])
    # formule physique : rendement système ajusté sur 2010 (sinon comparaison injuste)
    base = pvwatts(train.poa_w_m2.values, train.t_air_c.values, 1.0)
    rendement = float(np.median(train.ac_power_w.values / base))
    p_phys = pvwatts(test.poa_w_m2.values, test.t_air_c.values, rendement)
    res = {
        "donnees": {"source": "NREL PVDAQ, système 4 (1 kWc, Golden CO), données réelles horaires",
                    "heures_entrainement_2010_2012": int(len(train)), "heures_test_2013": int(len(test))},
        "modele_ia": _scores(test.ac_power_w.values, p_ml, test.index),
        "formule_physique_pvwatts": {**_scores(test.ac_power_w.values, p_phys, test.index),
                                     "rendement_systeme_ajuste": round(rendement, 3)},
    }
    import joblib
    MODELE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modele": modele, "features": FEATURES, "rendement_pvwatts": rendement}, MODELE)
    METRIQUES.parent.mkdir(parents=True, exist_ok=True)
    METRIQUES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


_CACHE = {}


def attendu_w_par_kwc(poa, t_air, hauteur):
    """Production attendue (W/kWc) d'un module PROPRE. Repli sur la formule physique si pas de modèle."""
    poa, t_air, hauteur = (np.asarray(x, dtype=float) for x in (poa, t_air, hauteur))
    if "m" not in _CACHE:
        import joblib
        _CACHE["m"] = joblib.load(MODELE) if MODELE.exists() else None
    b = _CACHE["m"]
    if b is None:
        return np.where(poa > 0, pvwatts(poa, t_air, 0.85), 0.0)
    out = np.zeros_like(poa)
    jour = poa > 20
    if jour.any():
        out[jour] = np.maximum(0, b["modele"].predict(pd.DataFrame(
            {"poa_w_m2": poa[jour], "t_air_c": t_air[jour], "hauteur_soleil": hauteur[jour]})))
    return out
