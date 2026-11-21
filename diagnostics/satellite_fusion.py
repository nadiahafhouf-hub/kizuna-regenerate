"""Bloc 1 — fusion capteurs + satellite, sans changer le contrat LandProfile.

Principe : les capteurs donnent la vérité au sol ; le satellite (diagnostics.satellite) éclaire
l'espace entre les capteurs. Trois apports, tous TRAÇABLES dans le LandProfile :

1. Fusion de la salinité (CE) — « régression + IDW des résidus » : CE = a + b·indice satellite,
   puis l'IDW corrige l'écart aux points mesurés. ADOPTÉE SEULEMENT si la validation croisée
   (leave-one-out) fait mieux que l'IDW seul d'au moins 10 % ; sinon l'IDW est conservé et le
   résultat du test est quand même enregistré. Le Cd et le Pb ne sont JAMAIS estimés par satellite.
2. Observations par zone (règles documentées, indicatives) : stress hydrique, sol nu, sel de
   surface, couvert végétal → interprétation et traitement plus précis.
3. Points de contrôle : une case non mesurée dont la vigueur diffère fortement du reste de sa
   zone voit sa confiance baisser, et un point de mesure y est proposé.

Champs AJOUTÉS (facultatifs) : profile["satellite"], profile["fusion_ce"],
profile["points_controle"], cases[].satellite, zones[].observations.
"""
import numpy as np

from .couleur import couleur_case
from .idw import _xy, idw_valeur, niveau_confiance

# Seuils indicatifs (littérature télédétection agricole ; à recaler localement)
NDVI_VEGETATION = 0.30   # au-dessus : couvert végétal
NDVI_SOL_NU = 0.20       # en dessous : sol nu ou quasi nu
NDMI_STRESS_FORT = 0.0   # végétation : NDMI < 0 → stress hydrique fort
NDMI_STRESS_MODERE = 0.10
CE_SALIN = 6.0           # dS/m (seuil ORANGE du projet)
GAIN_MIN_FUSION = 0.10   # la fusion doit réduire l'erreur d'au moins 10 %
COVARIABLES = ("ndmi", "si", "ndvi")


def _par_case(sat):
    return {(c["ligne"], c["col"]): c for c in sat.get("cases", [])}


def _ajuster(x, y):
    """Droite y = a + b·x robuste : si x est (quasi) constant, b = 0 (moyenne)."""
    if np.ptp(x) < 1e-6:
        return 0.0, float(np.mean(y))
    try:
        b, a = np.polyfit(x, y, 1)
        return float(b), float(a)
    except (np.linalg.LinAlgError, ValueError):
        return 0.0, float(np.mean(y))


def _loocv_fusion(xy, ce, x, puissance):
    """RMSE leave-one-out : IDW seul vs régression linéaire + IDW des résidus."""
    n = len(ce)
    e_idw, e_fus = [], []
    for i in range(n):
        k = np.arange(n) != i
        e_idw.append(idw_valeur(xy[k], ce[k], *xy[i], puissance) - ce[i])
        b, a = _ajuster(x[k], ce[k])
        res = ce[k] - (a + b * x[k])
        e_fus.append(a + b * x[i] + idw_valeur(xy[k], res, *xy[i], puissance) - ce[i])
    rm = lambda e: float(np.sqrt(np.mean(np.square(e))))  # noqa: E731
    return rm(e_idw), rm(e_fus)


def fusion_ce(profile, sat):
    """Teste la fusion CE ↔ satellite ; modifie les cases interpolées seulement si elle est meilleure."""
    taille = profile["taille_case_m"]
    pix = _par_case(sat)
    puissance = (profile.get("interpolation") or {}).get("puissance", 2.0)
    mesurees = [c for c in profile["cases"] if c["source"] == "capteur"]
    rapport = {"n_points": len(mesurees), "adoptee": False, "raison": None}
    if len(mesurees) < 5:
        rapport["raison"] = "trop_peu_de_points"
        return rapport
    meilleur = None
    for cov in COVARIABLES:
        pts = [(c, pix.get((c["ligne"], c["col"]), {}).get(cov)) for c in mesurees]
        pts = [(c, v) for c, v in pts if v is not None]
        if len(pts) < 5:
            continue
        x = np.array([v for _, v in pts])
        if np.ptp(x) < 1e-3:
            continue  # aucun contraste satellite entre les points
        ce = np.array([c["CE_dS_m"] for c, _ in pts])
        xy = np.array([_xy(c["ligne"], c["col"], taille) for c, _ in pts], dtype=float)
        r = float(np.corrcoef(x, ce)[0, 1]) if np.std(ce) > 0 else 0.0
        rmse_idw, rmse_fus = _loocv_fusion(xy, ce, x, puissance)
        cand = {"covariable": cov, "correlation": round(r, 2), "rmse_idw": round(rmse_idw, 2),
                "rmse_fusion": round(rmse_fus, 2),
                "gain_pct": round(100 * (rmse_idw - rmse_fus) / rmse_idw, 1) if rmse_idw > 0 else 0.0,
                "_x": x, "_ce": ce, "_xy": xy}
        if meilleur is None or cand["rmse_fusion"] < meilleur["rmse_fusion"]:
            meilleur = cand
    if meilleur is None:
        rapport["raison"] = "pas_de_contraste_satellite"
        return rapport
    rapport.update({k: v for k, v in meilleur.items() if not k.startswith("_")})
    if meilleur["gain_pct"] < 100 * GAIN_MIN_FUSION or abs(meilleur["correlation"]) < 0.5:
        rapport["raison"] = "pas_meilleure_que_idw"
        return rapport

    # adoptée : on recalcule la CE des cases NON mesurées
    x, ce, xy = meilleur["_x"], meilleur["_ce"], meilleur["_xy"]
    b, a = _ajuster(x, ce)
    res = ce - (a + b * x)
    cov = meilleur["covariable"]
    modifiees = 0
    for c in profile["cases"]:
        v = pix.get((c["ligne"], c["col"]), {}).get(cov)
        if c["source"] == "capteur" or v is None:
            continue
        cx, cy = _xy(c["ligne"], c["col"], taille)
        c["CE_dS_m"] = round(max(0.1, float(a + b * v + idw_valeur(xy, res, cx, cy, puissance))), 2)
        c["source_ce"] = "idw+satellite"
        modifiees += 1
    rapport.update({"adoptee": True, "raison": "meilleure_que_idw", "cases_modifiees": modifiees,
                    "pente": round(float(b), 3), "ordonnee": round(float(a), 3)})
    return rapport


def observations_zone(zone, cases_zone, pix):
    """Observations satellite d'une zone (codes traduits dans core/strings.py → satellite.obs)."""
    vals = [pix[(c["ligne"], c["col"])] for c in cases_zone
            if (c["ligne"], c["col"]) in pix and pix[(c["ligne"], c["col"])].get("valide")]
    if not vals:
        return [{"code": "pas_de_donnee", "niveau": "info", "valeurs": {}}]
    ndvi = float(np.mean([v["ndvi"] for v in vals]))
    ndmi = float(np.mean([v["ndmi"] for v in vals]))
    si = float(np.mean([v["si"] for v in vals]))
    part_veg = np.mean([v["ndvi"] >= NDVI_VEGETATION for v in vals])
    part_nue = np.mean([v["ndvi"] < NDVI_SOL_NU for v in vals])
    ce_max = max(c["CE_dS_m"] for c in cases_zone)
    valeurs = {"ndvi": round(ndvi, 2), "ndmi": round(ndmi, 2), "si": round(si, 3),
               "couvert_pct": round(100 * float(part_veg)), "sol_nu_pct": round(100 * float(part_nue))}
    obs = []
    if part_veg >= 0.5:
        if ndmi < NDMI_STRESS_FORT:
            obs.append({"code": "stress_hydrique_fort", "niveau": "alerte"})
        elif ndmi < NDMI_STRESS_MODERE:
            obs.append({"code": "stress_hydrique_modere", "niveau": "attention"})
        else:
            obs.append({"code": "vegetation_saine", "niveau": "info"})
        if zone["couleur"] in ("ROUGE", "ORANGE"):
            obs.append({"code": "couvert_utile", "niveau": "info"})
    elif part_nue >= 0.5:
        obs.append({"code": "sol_nu_a_couvrir" if zone["couleur"] != "VERT" else "sol_nu_pret",
                    "niveau": "attention" if zone["couleur"] != "VERT" else "info"})
        if ce_max >= CE_SALIN:
            obs.append({"code": "sel_surface_probable", "niveau": "attention"})
    else:
        obs.append({"code": "vegetation_clairsemee", "niveau": "attention"})
        if zone["couleur"] == "VERT":
            obs.append({"code": "vert_mais_faible", "niveau": "attention"})
    for o in obs:
        o["valeurs"] = valeurs
    return obs


def points_controle(profile, pix, max_points=3):
    """Cases non mesurées anormales (vigueur > 2 σ de leur zone) → confiance réduite + point proposé."""
    out = []
    for z in profile["zones"]:
        cz = [c for c in profile["cases"] if [c["ligne"], c["col"]] in z["cases"]]
        nd = [(c, pix.get((c["ligne"], c["col"]), {}).get("ndvi")) for c in cz]
        nd = [(c, v) for c, v in nd if v is not None]
        if len(nd) < 4:
            continue
        m, s = np.mean([v for _, v in nd]), np.std([v for _, v in nd])
        for c, v in nd:
            if c["source"] != "capteur" and s > 0 and abs(v - m) > 2 * s and abs(v - m) > 0.1:
                if "confiance" in c:
                    c["confiance"] = round(c["confiance"] * 0.6, 2)
                    c["niveau_confiance"] = niveau_confiance(c["confiance"])
                out.append({"ligne": c["ligne"], "col": c["col"], "zone": z["id"], "ndvi": v,
                            "ndvi_zone": round(float(m), 2)})
    return sorted(out, key=lambda p: -abs(p["ndvi"] - p["ndvi_zone"]))[:max_points]


def appliquer_satellite(profile, sat, fusion=True):
    """Ajoute la couche satellite au LandProfile (même contrat, champs en plus).
    `fusion=False` pour les profils de démo (valeurs de capteurs fictives : on n'y touche pas)."""
    from .pipeline import regrouper_zones

    pix = _par_case(sat)
    if fusion:
        profile["fusion_ce"] = fusion_ce(profile, sat)
        if profile["fusion_ce"]["adoptee"]:
            for c in profile["cases"]:
                c["couleur"] = couleur_case(c["CE_dS_m"], c["pH"], c["Cd_mg_kg"], c["Pb_mg_kg"])
            profile["zones"] = regrouper_zones(profile["cases"], profile["taille_case_m"])
    for c in profile["cases"]:
        p = pix.get((c["ligne"], c["col"]))
        if p:
            c["satellite"] = {k: p[k] for k in ("ndvi", "ndmi", "si", "scl", "valide")}
    for z in profile["zones"]:
        cz = [c for c in profile["cases"] if [c["ligne"], c["col"]] in z["cases"]]
        z["observations"] = observations_zone(z, cz, pix)
    profile["points_controle"] = points_controle(profile, pix)
    profile["satellite"] = sat
    return profile
