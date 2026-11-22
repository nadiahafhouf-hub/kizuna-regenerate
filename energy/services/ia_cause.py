"""IA 2 — « Pourquoi la production baisse ? » : poussière, panne, ou rien (météo).

Base : l'indice de performance journalier IP = énergie mesurée / énergie attendue (IA 1), calculé sur
les VRAIES journées NREL. Sur une installation saine, IP ≈ 1 avec le bruit réel (nuages, capteurs).
Sur ces vraies séries, on ajoute des défauts connus pour obtenir des exemples étiquetés :
  - POUSSIERE : baisse lente (0,15 à 1,2 %/jour), parfois après une tempête (marche de 3 à 10 %) ;
  - PANNE     : chute brutale et durable (8 à 50 %) : chaîne débranchée, onduleur, casse, ombre nouvelle ;
  - PROPRE    : rien d'ajouté.
Le classifieur (gradient boosting) lit la FORME de la série sur 21 jours.
Validation honnête : l'IA 1 est entraînée sans l'année prédite (validation croisée par année), puis
le classifieur est entraîné sur les fenêtres 2011-2012 et testé sur 2013.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings

MODELE = Path(settings.BASE_DIR) / "energy" / "ml_models" / "cause.joblib"
METRIQUES = Path(settings.BASE_DIR) / "fixtures" / "energy" / "ia2_metriques.json"
CLASSES = ["PROPRE", "POUSSIERE", "PANNE"]
FENETRE = 21


def theil_sen(y):
    """Pente robuste (médiane des pentes entre toutes les paires)."""
    y = np.asarray(y, dtype=float)
    i, j = np.triu_indices(len(y), 1)
    return float(np.median((y[j] - y[i]) / (j - i))) if len(y) > 1 else 0.0


def caracteristiques(ip):
    """Forme d'une série d'IP (≈ 1 = normal) sur une fenêtre de jours."""
    ip = np.asarray(ip, dtype=float)
    n = len(ip)
    pente = theil_sen(ip)
    debut, fin = np.median(ip[:5]), np.median(ip[-5:])
    sauts = [np.median(ip[max(0, k - 3):k]) - np.median(ip[k:k + 3]) for k in range(3, n - 2)]
    saut = max(sauts) if sauts else 0.0
    x = np.arange(n)
    res = ip - np.polyval(np.polyfit(x, ip, 1), x)
    return {
        "pente_pct_jour": 100 * pente,
        "baisse_pct": 100 * (debut - fin),
        "saut_max_pct": 100 * saut,
        "bruit_pct": 100 * float(np.std(res)),
        "saut_sur_baisse": saut / (abs(debut - fin) + 0.01),
        "niveau_final": fin,
        "jours_sous_95": float(np.mean(ip < 0.95)),
    }


def indices_journaliers(df_horaire, w_par_kwc_attendu):
    """IP journalier = Σ mesuré / Σ attendu (journées assez ensoleillées seulement)."""
    d = pd.DataFrame({"mes": df_horaire.ac_power_w.values, "att": w_par_kwc_attendu}, index=df_horaire.index)
    j = d.resample("1D").sum()
    j = j[j.att > 1500]   # > 1,5 kWh/kWc attendus : journée exploitable
    return (j.mes / j.att).rename("ip")


def _injecter(ip, rng):
    n = len(ip)
    c = rng.choice(CLASSES, p=[0.4, 0.35, 0.25])
    f = np.ones(n)
    if c == "POUSSIERE":
        r = rng.uniform(0.0015, 0.012)
        s = rng.integers(0, 8)
        f[s:] = 1 - r * np.arange(1, n - s + 1)
        if rng.random() < 0.3:   # tempête de sable : marche + accumulation
            k = rng.integers(s, n - 3)
            f[k:] -= rng.uniform(0.03, 0.10)
    elif c == "PANNE":
        k = rng.integers(7, n - 3)
        f[k:] = 1 - rng.uniform(0.08, 0.5)
    return c, ip * f, f


def generer(ip_series, n_fenetres, seed):
    rng = np.random.default_rng(seed)
    v = ip_series.values
    X, y, pertes = [], [], []
    for _ in range(n_fenetres):
        s = rng.integers(0, len(v) - FENETRE)
        c, w, f = _injecter(v[s:s + FENETRE].copy(), rng)
        X.append(caracteristiques(w))
        y.append(c)
        pertes.append(1 - f)
    return pd.DataFrame(X), np.array(y), pertes


def _ip_validation_croisee(df):
    """IP journalier de chaque année avec une IA 1 entraînée SANS cette année."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    from .ia_production import FEATURES, nettoyer
    d = nettoyer(df)
    series = {}
    for an in (2011, 2012, 2013):
        m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, random_state=0)
        tr = d[d.index.year != an]
        m.fit(tr[FEATURES], tr.ac_power_w)
        te = d[d.index.year == an]
        series[an] = indices_journaliers(te, np.maximum(0, m.predict(te[FEATURES])))
    return series


def entrainer(df):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import classification_report, confusion_matrix

    ip = _ip_validation_croisee(df)
    ip_train = pd.concat([ip[2011], ip[2012]])
    Xtr, ytr, _ = generer(ip_train, 6000, seed=1)
    Xte, yte, _ = generer(ip[2013], 2000, seed=2)
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0).fit(Xtr, ytr)
    pred = clf.predict(Xte)
    rep = classification_report(yte, pred, labels=CLASSES, output_dict=True, zero_division=0)
    cm = confusion_matrix(yte, pred, labels=CLASSES)
    res = {
        "donnees": {"base": "vraies journées NREL PVDAQ (IP journalier), défauts ajoutés connus",
                    "fenetres_entrainement_2011_2012": len(ytr), "fenetres_test_2013": len(yte),
                    "jours_reels": {str(k): int(len(v)) for k, v in ip.items()},
                    "bruit_reel_ip_pct": round(float(100 * ip[2013].std()), 2)},
        "exactitude_pct": round(100 * float(np.mean(pred == yte)), 1),
        "par_classe": {c: {"precision_pct": round(100 * rep[c]["precision"], 1), "rappel_pct": round(100 * rep[c]["recall"], 1)}
                       for c in CLASSES},
        "matrice_confusion": {"lignes_verite_colonnes_prediction": CLASSES, "valeurs": cm.tolist()},
        "fausses_alertes_pct": round(100 * float(np.mean(pred[yte == "PROPRE"] != "PROPRE")), 1),
    }
    import joblib
    MODELE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modele": clf, "colonnes": list(Xtr.columns), "ip_2013": ip[2013]}, MODELE)
    METRIQUES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


_CACHE = {}


def diagnostiquer(ip):
    """Classe la fenêtre la plus récente (≥ 10 jours) : {cause, probabilites, caracteristiques}."""
    ip = np.asarray(ip, dtype=float)[-FENETRE:]
    if len(ip) < 10:
        return None
    if "m" not in _CACHE:
        import joblib
        _CACHE["m"] = joblib.load(MODELE) if MODELE.exists() else None
    feats = caracteristiques(ip)
    b = _CACHE["m"]
    if b is None:   # repli : règles simples
        cause = "PANNE" if feats["saut_max_pct"] > 8 and feats["saut_sur_baisse"] > 0.7 else \
            "POUSSIERE" if feats["baisse_pct"] > 3 else "PROPRE"
        return {"cause": cause, "probabilites": None, "caracteristiques": feats}
    X = pd.DataFrame([feats])[b["colonnes"]]
    proba = b["modele"].predict_proba(X)[0]
    classes = list(b["modele"].classes_)
    return {"cause": str(classes[int(np.argmax(proba))]),
            "probabilites": {str(c): round(float(p), 3) for c, p in zip(classes, proba)},
            "caracteristiques": {k: round(float(v), 3) for k, v in feats.items()}}
