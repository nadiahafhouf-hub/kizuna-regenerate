"""Bloc 1 — modèle IA « Cd à partir d'un relevé XRF ».

Problème : un XRF portable mesure bien Pb, Zn, Cu, Ni, Cr, Mn, Fe… mais mal le cadmium
(limite de détection proche des seuils 1–3 mg/kg). Le labo (ICP) est fiable mais coûteux.
Modèle : à partir des éléments XRF + classe de pH + texture + occupation du sol, estimer la
probabilité que Cd ≥ 1 mg/kg (seuil ORANGE). Usage : trier les points → n'envoyer au labo
que ceux à risque.

Données d'entraînement : LUCAS Heavy Metals 2009 (ESDAC/JRC, ~21 700 sols européens,
sans coordonnées). « < LOD » = sous la limite de détection → Cd < 1.
Le fichier brut n'est PAS versionné ; le modèle entraîné (.joblib) non plus ;
les métriques (fixtures/bloc1/modele_cd_metriques.json) le sont.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings

MODELE = Path(settings.BASE_DIR) / "diagnostics" / "ml_models" / "cd_xrf.joblib"
METRIQUES = Path(settings.BASE_DIR) / "fixtures" / "bloc1" / "modele_cd_metriques.json"

METAUX_XRF = ["Pb_mg_kg", "Zn_mg_kg", "Cu_mg_kg", "Ni_mg_kg", "Cr_mg_kg", "Mn_mg_kg", "Fe_mg_kg", "Co_mg_kg"]
NUM = METAUX_XRF + ["pH", "OC"]
CAT = ["texture", "occupation"]
MEDITERRANEE = {"ES", "IT", "EL", "PT", "CY", "MT", "HR", "SI"}
SEUIL_CD = 1.0


def _num(s):
    """'< LOD' → 0 (sous la limite), sinon nombre."""
    s = s.astype(str).str.strip()
    out = pd.to_numeric(s, errors="coerce")
    out[s.str.startswith("<")] = 0.0
    return out


def _milieu(classe):
    """'7.5-8' → 7.75 ; '0-50' → 25."""
    try:
        a, b = str(classe).split("-")
        return (float(a) + float(b)) / 2
    except ValueError:
        return np.nan


def charger_lucas(xlsx):
    df = pd.read_excel(xlsx, sheet_name="2009")
    out = pd.DataFrame({m: _num(df[m]) for m in METAUX_XRF})
    out["pH"] = df["pH_Class"].map(_milieu)
    out["OC"] = df["OC_Class"].map(_milieu)
    out["texture"] = df["USDA Texture"].fillna("inconnue").astype("category")
    out["occupation"] = df["LC0_Desc_2009"].fillna("inconnue").astype("category")
    out["cd"] = _num(df["Cd_mg_kg"])
    out["pays"] = df["NUTS_0"]
    return out.dropna(subset=["cd"])


def _modele():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                          categorical_features="from_dtype",
                                          class_weight="balanced", random_state=0)


def _evaluer(y, p):
    """AUC, AP, et le tri pour le labo : seuil qui garde 90 % des sols à risque."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    y = np.asarray(y)
    seuil = float(np.quantile(p[y == 1], 0.10))  # 90 % des positifs au-dessus
    envoyes = p >= seuil
    return {
        "n": int(len(y)), "positifs": int(y.sum()), "taux_positifs_pct": round(100 * y.mean(), 1),
        "auc": round(float(roc_auc_score(y, p)), 3),
        "precision_moyenne": round(float(average_precision_score(y, p)), 3),
        "tri_labo": {
            "rappel_vise_pct": 90,
            "seuil_probabilite": round(seuil, 3),
            "echantillons_envoyes_au_labo_pct": round(100 * envoyes.mean(), 1),
            "analyses_economisees_pct": round(100 * (1 - envoyes.mean()), 1),
            "precision_des_envoyes_pct": round(100 * y[envoyes].mean(), 1),
        },
    }


def entrainer(xlsx):
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import train_test_split

    df = charger_lucas(xlsx)
    X, y = df[NUM + CAT], (df["cd"] >= SEUIL_CD).astype(int)

    # 1) découpage aléatoire stratifié 80/20
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=0)
    m = _modele().fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    res = {"aleatoire_80_20": _evaluer(yte, p)}

    imp = permutation_importance(m, Xte, yte, scoring="roc_auc", n_repeats=4, random_state=0)
    res["importance"] = sorted(({"variable": c, "baisse_auc": round(float(v), 4)}
                                for c, v in zip(NUM + CAT, imp.importances_mean)),
                               key=lambda r: -r["baisse_auc"])

    # 2) test géographique : entraîné hors Méditerranée, testé sur les pays méditerranéens
    med = df["pays"].isin(MEDITERRANEE)
    m2 = _modele().fit(X[~med], y[~med])
    res["test_mediterranee"] = _evaluer(y[med], m2.predict_proba(X[med])[:, 1])
    res["test_mediterranee"]["pays"] = sorted(MEDITERRANEE & set(df["pays"]))

    # 3) référence naïve : seulement le plomb (le meilleur élément seul)
    from sklearn.metrics import roc_auc_score
    res["reference_plomb_seul_auc"] = round(float(roc_auc_score(yte, Xte["Pb_mg_kg"].fillna(0))), 3)

    # modèle final sur toutes les données
    final = _modele().fit(X, y)
    import joblib
    MODELE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modele": final, "num": NUM, "cat": CAT,
                 "categories": {c: list(X[c].cat.categories) for c in CAT},
                 "seuil_tri": res["aleatoire_80_20"]["tri_labo"]["seuil_probabilite"]}, MODELE)
    res["donnees"] = {"source": "LUCAS Heavy Metals 2009 (ESDAC/JRC)", "echantillons": int(len(df)),
                      "cible": f"Cd >= {SEUIL_CD} mg/kg", "variables": NUM + CAT}
    return res


def predire_risque_cd(releve):
    """Probabilité Cd ≥ 1 mg/kg pour un relevé {Pb_mg_kg, Zn_mg_kg, …, pH, texture, occupation}.
    Renvoie None si le modèle n'a pas été entraîné (python manage.py bloc1_train_cd …)."""
    if not MODELE.exists():
        return None
    import joblib
    b = joblib.load(MODELE)
    row = {c: [releve.get(c, np.nan)] for c in b["num"]}
    for c in b["cat"]:
        row[c] = pd.Categorical([releve.get(c, "inconnue")], categories=b["categories"][c])
    p = float(b["modele"].predict_proba(pd.DataFrame(row))[0, 1])
    return {"probabilite": round(p, 3), "envoyer_au_labo": p >= b["seuil_tri"], "seuil": b["seuil_tri"]}
