"""IA 3 — « Quand faudra-t-il nettoyer ? » : perte actuelle, vitesse d'encrassement, date conseillée.

1. Perte actuelle = 1 − IP récent (médiane des 3 derniers jours), l'IP étant recalé à 1 après le dernier
   nettoyage (ou une grosse pluie).
2. Vitesse = pente robuste (Theil-Sen) de l'IP depuis ce nettoyage.
3. Projection jour par jour sur l'horizon de prévision Open-Meteo :
     vitesse × (1 + poussière prévue / 200 µg/m³)   — les épisodes de poussière accélèrent l'encrassement ;
     pluie ≥ 5 mm  → nettoyage naturel partiel (70 % de la perte effacée).
4. Décision :
     perte ≥ seuil (5 %)            → NETTOYER (maintenant, ou juste APRÈS une tempête annoncée) ;
     pluie ≥ 5 mm annoncée          → ATTENDRE la pluie ;
     seuil atteint dans ≤ 7 jours   → PRÉVOIR le nettoyage à cette date.
5. Traduction pour l'agriculteur : énergie perdue → litres d'eau NON pompés par jour.
Validation (notebook) : sur des encrassements ajoutés aux vraies journées NREL 2013, on prédit à partir
des 10 premiers jours la date de dépassement du seuil et on la compare à la vraie.
"""
from datetime import date, timedelta

import numpy as np

from .ia_cause import theil_sen

SEUIL = 0.05
PLUIE_NETTOIE_MM = 5.0
PLUIE_EFFICACITE = 0.7
POUSSIERE_REF = 200.0
TEMPETE = 150.0   # µg/m³ de poussière : épisode qui salit fortement


def etat_encrassement(ip_depuis_nettoyage, reference=1.0):
    """`reference` = IP d'un panneau propre : 1 car l'IA 1 est calibrée sur l'installation juste après
    un nettoyage (prendre les premiers jours comme référence sous-estime la perte : ils sont déjà sales)."""
    ip = np.asarray(ip_depuis_nettoyage, dtype=float)
    if len(ip) < 3:
        return {"perte": 0.0, "vitesse_jour": 0.0, "jours": len(ip)}
    rel = ip / reference
    perte = float(max(0.0, 1 - np.median(rel[-3:])))
    vitesse = float(max(0.0, -theil_sen(rel))) if len(rel) >= 5 else 0.0
    return {"perte": perte, "vitesse_jour": vitesse, "jours": len(ip)}


def jours_avant_seuil(perte, vitesse, seuil=SEUIL, previsions=None, horizon=60):
    """Nombre de jours avant d'atteindre le seuil (None si jamais sur l'horizon)."""
    if perte >= seuil:
        return 0
    p = perte
    for k in range(1, horizon + 1):
        prev = (previsions or [])[k - 1] if previsions and k - 1 < len(previsions) else None
        v = vitesse * (1 + (prev["poussiere_max"] if prev else 0) / POUSSIERE_REF)
        p += v
        if prev and prev["pluie_mm"] >= PLUIE_NETTOIE_MM:
            p *= 1 - PLUIE_EFFICACITE
        if p >= seuil:
            return k
    return None


def recommander(ip_depuis_nettoyage, previsions=None, aujourd_hui=None, energie_attendue_kwh_jour=None,
                hauteur_m=55.0, rendement_pompe=0.45, seuil=SEUIL):
    """Décision complète pour l'interface et les alertes."""
    from .dimensionnement import G_RHO
    auj = aujourd_hui or date.today()
    e = etat_encrassement(ip_depuis_nettoyage)
    j = jours_avant_seuil(e["perte"], e["vitesse_jour"], seuil, previsions)
    prev = previsions or []
    pluie = next((p for p in prev if p["pluie_mm"] >= PLUIE_NETTOIE_MM), None)
    tempete = next((p for p in prev if p["poussiere_max"] >= TEMPETE), None)
    if e["perte"] >= seuil:
        if tempete:
            action, quand = "NETTOYER_APRES_TEMPETE", date.fromisoformat(tempete["date"]) + timedelta(days=1)
        elif pluie and (date.fromisoformat(pluie["date"]) - auj).days <= 2:
            action, quand = "ATTENDRE_PLUIE", date.fromisoformat(pluie["date"])
        else:
            action, quand = "NETTOYER", auj
    elif j is not None and j <= 7:
        action, quand = "PREVOIR", auj + timedelta(days=j)
    else:
        action, quand = "RIEN", (auj + timedelta(days=j)) if j is not None else None
    eau_l = None
    if energie_attendue_kwh_jour:
        kwh_perdus = e["perte"] * energie_attendue_kwh_jour
        eau_l = round(1000 * kwh_perdus * rendement_pompe / (G_RHO * hauteur_m))
    return {**{k: round(v, 4) if isinstance(v, float) else v for k, v in e.items()},
            "perte_pct": round(100 * e["perte"], 1), "vitesse_pct_jour": round(100 * e["vitesse_jour"], 2),
            "jours_avant_seuil": j, "seuil_pct": round(100 * seuil),
            "action": action, "date_conseillee": quand.isoformat() if quand else None,
            "tempete": tempete, "pluie": pluie, "eau_non_pompee_l_jour": eau_l}


def valider(ip_2013, n=500, seed=3):
    """Erreur (jours) sur la date de dépassement du seuil prédite à partir des 10 premiers jours."""
    rng = np.random.default_rng(seed)
    v = ip_2013.values
    erreurs = []
    for _ in range(n):
        s = rng.integers(0, len(v) - 40)
        r = rng.uniform(0.002, 0.01)
        f = 1 - r * np.arange(1, 41)
        serie = v[s:s + 40] * f
        vrai = int(np.argmax(f <= 1 - SEUIL)) + 1
        e = etat_encrassement(serie[:10])
        j = jours_avant_seuil(e["perte"], e["vitesse_jour"], horizon=80)
        if j is not None and vrai > 10:
            erreurs.append((10 + j) - vrai)
    err = np.abs(np.array(erreurs))
    return {"cas": len(erreurs), "erreur_mediane_jours": float(np.median(err)),
            "erreur_p80_jours": float(np.percentile(err, 80)), "biais_moyen_jours": round(float(np.mean(erreurs)), 1)}
