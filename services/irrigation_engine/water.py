"""Besoins en eau (methode FAO-56), consommation actuelle estimee, consommation optimisee."""

import math
import numpy as np
from .crops import (
    CLIMATS,
    SYSTEMES,
    SOLS,
    JOURS_MOIS,
    ECE_SEUIL,
    ECE_MAX,
    RDI,
    get_crop,
)


def climat(cfg):
    c = cfg.get("climat", "tunisie_centre")
    if isinstance(c, str):
        return CLIMATS[c]
    return {
        "nom": c.get("nom", "Donnees utilisateur"),
        "et0": c["et0"],
        "pluie": c["pluie"],
    }


def pluie_efficace(p_mm_mois):
    """FAO/AGLW : Pe = 0.6P-10 (P<=70 mm) ; 0.8P-24 (P>70 mm)."""
    return max(0.0, 0.6 * p - 10) if (p := p_mm_mois) <= 70 else 0.8 * p - 24


def kr_couverture(gc):
    """Facteur de reduction pour l'irrigation localisee (moyenne Keller-Karmeli, Freeman-Garzoli, Decroix)."""
    gc = min(max(gc, 0.0), 1.0)
    return min(1.0, (1.34 * gc + (gc + 0.5 * (1 - gc)) + (0.1 + gc)) / 3)


def lessivage(cfg, crop_key, localise=True):
    """Fraction de lessivage (FAO-29) : localise LR = ECw/(2 ECe_max) ; sinon LR = ECw/(5 ECe_seuil - ECw)."""
    ecw = cfg.get("salinite_eau_dS_m")
    if not ecw:
        return 0.0
    if localise:
        lr = ecw / (2 * ECE_MAX.get(crop_key, 10.0))
    else:
        lr = ecw / max(5 * ECE_SEUIL.get(crop_key, 2.0) - ecw, 0.1)
    return min(lr, 0.35)


def besoins_zone(cfg, zone_info, design_zone, systeme, use_kr, area_m2, rdi=False):
    """Besoins mensuels bruts (m3/mois) d'une zone pour un systeme donne."""
    clim = climat(cfg)
    crop_key = zone_info["culture"]
    crop = get_crop(crop_key)
    eff = SYSTEMES[systeme]["efficience"]
    lr = (
        0.0
        if zone_info.get("lessivage_interdit")
        else lessivage(cfg, crop_key, SYSTEMES[systeme]["localise"])
    )
    facteur = zone_info.get("facteur_dose", 1.0)
    gc = design_zone.get("gc", 0.5)
    kr = (
        kr_couverture(gc)
        if use_kr and crop["type"] in ("arbre", "arbuste")
        else (0.9 if use_kr else 1.0)
    )
    out = []
    for m in range(12):
        kc = crop["kc"][m]
        if kc <= 0:
            out.append({"etc_mm_j": 0.0, "net_mm_j": 0.0, "brut_mm_j": 0.0, "m3": 0.0})
            continue
        etc = clim["et0"][m] * kc
        pe = pluie_efficace(clim["pluie"][m]) / JOURS_MOIS[m]
        net = max(0.0, etc * kr - pe) * facteur
        if rdi and crop_key in RDI and m in RDI[crop_key][1]:
            net *= RDI[crop_key][0]
        brut = net / eff / (1 - lr)
        out.append(
            {
                "etc_mm_j": etc,
                "net_mm_j": net,
                "brut_mm_j": brut,
                "m3": brut * area_m2 / 1000 * JOURS_MOIS[m],
            }
        )
    return out, {"kr": kr, "efficience": eff, "lessivage": lr}


def consommation_actuelle(cfg, zone_cfg, zinfo, dzone):
    """Estimation de la consommation actuelle (m3/an) + gaspillages identifies."""
    irr = zinfo["irrigation"]
    typ = irr["type"]
    declared = zone_cfg.get("irrigation_actuelle", {}).get("consommation_m3_an")
    notes = []
    if typ == "aucun":
        return {
            "m3_an": float(declared or 0),
            "mensuel": [0.0] * 12,
            "source": "aucune irrigation",
            "notes": notes,
        }
    if typ == "gravitaire":
        area = zinfo["surface_m2"]
        mens, p = besoins_zone(cfg, zinfo, dzone, "gravitaire", False, area)
        notes.append("Surface entiere irriguee (y compris inter-rangs nus).")
    elif typ == "aspersion":
        area = min(
            irr.get("surface_mouillee_m2", zinfo["surface_m2"]),
            1.6 * zinfo["surface_m2"],
        )
        mens, p = besoins_zone(cfg, zinfo, dzone, "aspersion", False, area)
        cov = irr.get("couverture_plantes_pct", 100)
        if cov < 95:
            notes.append(
                f"{100-cov:.0f}% des plantes ne sont atteintes par aucun asperseur (irrigation non uniforme)."
            )
        if irr.get("hors_zone_m2", 0) > 1:
            notes.append(
                f"{irr['hors_zone_m2']:.0f} m2 arroses hors de la parcelle (chemins, voisins)."
            )
    else:  # goutte a goutte existant
        area = dzone["surface_utile_m2"]
        mens, p = besoins_zone(cfg, zinfo, dzone, typ, True, area)
        waste = irr.get("part_inutile_pct", 0) / 100
        if waste > 0:
            notes.append(
                f"{irr.get('longueur_inutile_m', 0):.0f} m de ligne goutte-a-goutte sur sol sans plante "
                f"({waste*100:.0f}% du reseau)."
            )
            for r in mens:
                r["m3"] *= 1 + waste
        cov = irr.get("couverture_plantes_pct", 100) / 100
        if cov < 0.95:
            notes.append(
                f"Seulement {cov*100:.0f}% des plantes sont a portee d'une ligne : "
                "les autres sont en stress hydrique, l'agriculteur compense souvent en irriguant plus longtemps."
            )
            for r in mens:
                r["m3"] *= 1 + 0.5 * (1 - cov)  # surdosage compensatoire
    total = sum(r["m3"] for r in mens)
    src = "estimation du modele"
    if declared:
        total = float(declared)
        src = "valeur declaree par l'utilisateur"
    return {
        "m3_an": total,
        "mensuel": [r["m3"] for r in mens],
        "source": src,
        "notes": notes,
        "parametres": p,
    }


def programme(cfg, zinfo, dzone, mens_opt):
    """Programme d'irrigation mensuel : litres/plante/jour, frequence, duree par arrosage."""
    crop = get_crop(zinfo["culture"])
    sol = SOLS[cfg.get("sol", "limoneux")]
    area_pl = dzone["surface_par_plante_m2"]
    q_pl = dzone["debit_par_plante_l_h"]
    pw = dzone.get("pw", 0.4)
    # dose maximale avant percolation : RAW = p * RU * profondeur * Pw (mm)
    raw_mm = (
        crop["p"]
        * sol["ru_mm_m"]
        * zinfo.get("ru_facteur", 1.0)
        * crop["prof_racine_m"]
        * pw
    )
    if crop["type"] == "maraichage":
        raw_mm *= 0.5  # maintenir l'humidite haute en maraichage
    lignes = []
    for m in range(12):
        bj = mens_opt[m]["brut_mm_j"]
        if bj <= 0.01:
            lignes.append(
                {
                    "mois": m,
                    "l_plante_j": 0,
                    "intervalle_j": None,
                    "duree_min": 0,
                    "m3_jour_zone": 0,
                }
            )
            continue
        l_pl_j = bj * area_pl
        # goutte-a-goutte : arrosages frequents (bulbe humide stable), au plus tous les 3 jours
        imax = 1 if sol["infiltration_mm_h"] >= 25 else 3
        net = mens_opt[m]["net_mm_j"]
        interval = int(max(1, min(imax, math.floor(raw_mm / net) if net else imax)))
        duree_min = (l_pl_j * interval) / q_pl * 60 if q_pl else 0
        # pas plus de 4 h d'affilee (percolation sous le bulbe) ...
        while duree_min > 240 and interval > 1:
            interval -= 1
            duree_min = (l_pl_j * interval) / q_pl * 60
        # ... ni moins de 15 min (mauvaise uniformite pendant la mise en pression)
        while duree_min < 15 and interval < 7:
            interval += 1
            duree_min = (l_pl_j * interval) / q_pl * 60
        lignes.append(
            {
                "mois": m,
                "l_plante_j": l_pl_j,
                "intervalle_j": interval,
                "duree_min": duree_min,
                "m3_jour_zone": bj * dzone["surface_utile_m2"] / 1000,
            }
        )
    return lignes, raw_mm
