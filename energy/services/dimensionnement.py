"""Dimensionnement de l'installation photovoltaïque de pompage — calcul physique (pas d'IA).

Chaîne :  plantes → eau → énergie de pompage → panneaux.

1. Eau par plante et par jour, mois par mois (FAO-56, goutte-à-goutte) :
       L/plante/j = max(0, ET0·Kc·couverture − pluie efficace) × espacement² ÷ (1 − LR) ÷ efficience
   (Kc, couverture, espacement, fraction de lessivage LR et nombre de plantes : bloc 2 par zone,
   le nombre de plantes est modifiable par l'agriculteur).
2. Énergie hydraulique :  E (kWh/j) = ρ·g·H·V / 3,6·10⁶ / η = 0,002725 × V (m³) × H (m) / η
   H = (profondeur de pompage + 10 m de pression goutte-à-goutte) × 1,10 (pertes de charge).
3. Panneaux : kWc = E du mois le plus exigeant ÷ (production PVGIS d'1 kWc ce mois × (1 − marge poussière)).
   La marge poussière (5 %) est TENUE par les alertes de nettoyage (IA 2-3) : sans nettoyage, il faudrait
   surdimensionner davantage.
4. Pompe : débit = volume du jour de pointe ÷ heures équivalentes plein soleil ; puissance ≈ E ÷ ces heures.
   Réservoir : 1 jour de pointe + 20 % (l'eau stockée remplace les batteries : irrigation à l'aube).
"""
import math

MOIS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
JOURS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
G_RHO = 0.002725          # kWh par m³ et par mètre de hauteur (ρ·g / 3,6·10⁶)
PRESSION_GOUTTE_M = 10    # ≈ 1 bar en tête du réseau goutte-à-goutte
PERTES_CHARGE = 1.10
EFFICIENCE_GOUTTE = 0.90
PLUIE_EFFICACE = 0.6      # part de la pluie mensuelle réellement utile (sols sableux, pluies orageuses)
MARGE_POUSSIERE = 0.05


def eau_par_plante_l_jour(et0, pluie_mois, jours, kc, couverture, espacement_m, lr):
    pluie_eff = PLUIE_EFFICACE * pluie_mois / jours
    net_mm = max(0.0, et0 * kc * couverture - pluie_eff)
    return net_mm * espacement_m ** 2 / max(0.5, 1 - lr) / EFFICIENCE_GOUTTE


def dimensionner(zones, clim, profondeur_m=40.0, rendement_pompe=0.45, panneau_wc=450):
    """`zones` : [{id, culture, nb_plants, kc, couverture, espacement_m, lr}].
    `clim` : services.climat.climat(). Renvoie le dimensionnement + le détail mensuel."""
    h_tot = (profondeur_m + PRESSION_GOUTTE_M) * PERTES_CHARGE
    mensuel = []
    for m in range(12):
        litres = sum(z["nb_plants"] * eau_par_plante_l_jour(clim["et0_mm_jour"][m], clim["pluie_mm_mois"][m],
                                                             JOURS[m], z["kc"], z["couverture"],
                                                             z["espacement_m"], z.get("lr", 0.1))
                     for z in zones)
        v = litres / 1000
        e = G_RHO * v * h_tot / rendement_pompe
        y = clim["pv_kwh_kwc_jour"][m] * (1 - MARGE_POUSSIERE)
        mensuel.append({"mois": MOIS[m], "eau_m3_jour": round(v, 2), "energie_kwh_jour": round(e, 2),
                        "pv_kwh_kwc_jour": clim["pv_kwh_kwc_jour"][m], "kwc_necessaire": round(e / y, 3) if y else 0})
    pointe = max(mensuel, key=lambda r: r["kwc_necessaire"])
    i_pointe = mensuel.index(pointe)
    kwc_min = pointe["kwc_necessaire"]
    nb_panneaux = max(1, math.ceil(kwc_min * 1000 / panneau_wc))
    kwc = nb_panneaux * panneau_wc / 1000
    heures_soleil = clim["pv_kwh_kwc_jour"][i_pointe]
    debit = pointe["eau_m3_jour"] / heures_soleil if heures_soleil else 0
    pompe_kw = pointe["energie_kwh_jour"] / heures_soleil if heures_soleil else 0
    for r, m in zip(mensuel, range(12)):
        prod = kwc * clim["pv_kwh_kwc_jour"][m] * (1 - MARGE_POUSSIERE)
        r["production_kwh_jour"] = round(prod, 2)
        r["couverture_pct"] = round(min(999, 100 * prod / r["energie_kwh_jour"])) if r["energie_kwh_jour"] else None
    detail_zones = []
    for z in zones:
        lj = eau_par_plante_l_jour(clim["et0_mm_jour"][i_pointe], clim["pluie_mm_mois"][i_pointe], JOURS[i_pointe],
                                   z["kc"], z["couverture"], z["espacement_m"], z.get("lr", 0.1))
        detail_zones.append({**z, "litres_plante_jour_pointe": round(lj, 1),
                             "m3_jour_pointe": round(z["nb_plants"] * lj / 1000, 2)})
    return {
        "hauteur_totale_m": round(h_tot, 1), "profondeur_m": profondeur_m, "rendement_pompe": rendement_pompe,
        "panneau_wc": panneau_wc, "mois_dimensionnant": pointe["mois"],
        "nb_plants_total": sum(z["nb_plants"] for z in zones),
        "eau_pointe_m3_jour": pointe["eau_m3_jour"], "energie_pointe_kwh_jour": pointe["energie_kwh_jour"],
        "nb_panneaux": nb_panneaux, "kwc": round(kwc, 2), "kwc_minimum": round(kwc_min, 2),
        "surface_panneaux_m2": round(nb_panneaux * 2.0, 1),
        "surface_sol_m2": round(nb_panneaux * 2.0 * 1.6, 1),   # espacement entre rangées (pas d'ombre)
        "pompe_kw": round(pompe_kw, 2), "debit_m3_h": round(debit, 2),
        "reservoir_m3": round(pointe["eau_m3_jour"] * 1.2, 1),
        "energie_an_kwh": round(sum(r["energie_kwh_jour"] * j for r, j in zip(mensuel, JOURS))),
        "mensuel": mensuel, "zones": detail_zones, "climat_source": clim["source"],
        "inclinaison_deg": clim.get("inclinaison_deg"),
    }


def couverture_installation(dim, kwc_installe, pompe_kw_installee):
    """Compare avec l'installation actuelle (paramètres d'irrigation du bloc 3)."""
    pointe = next(r for r in dim["mensuel"] if r["mois"] == dim["mois_dimensionnant"])
    prod = kwc_installe * pointe["pv_kwh_kwc_jour"] * (1 - MARGE_POUSSIERE)
    return {"kwc": kwc_installe, "pompe_kw": pompe_kw_installee,
            "couverture_pointe_pct": round(100 * prod / pointe["energie_kwh_jour"]) if pointe["energie_kwh_jour"] else None}
