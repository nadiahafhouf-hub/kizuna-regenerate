"""Calendrier d'arrosage (IrrigationEvent) et simulation simple de la pompe.

Le plan donne un programme MOYEN par mois. L'agent d'irrigation peut ensuite corriger chaque evenement
avec la meteo du jour : duree x (ET0 prevue / ET0 moyenne du mois), annulation si pluie > 5 mm.
"""

import datetime as dt
from .crops import MOIS, JOURS_MOIS

RENDEMENT_POMPE = 0.60


def pompage(res, C):
    b = res["bilan"]
    hmt = max(C.hmt_m, 10.0)
    vol = b["optimal_m3_an"] + b.get("nouvelles_zones_m3_an", 0)
    kwh_m3 = 9.81 * hmt / 3600 / RENDEMENT_POMPE
    return {
        "hmt_m": float(hmt),
        "kwh_par_m3": float(kwh_m3),
        "kwh_an": float(vol * kwh_m3),
        "volume_m3_an": float(vol),
        "heures_pointe_j": float(b["heures_pompage_pointe"]),
        "mois_pointe": b["mois_pointe"],
    }


def generer_evenements(res, debut=None, jours=14, heure_debut="05:00", conception=None):
    """Liste d'evenements {date, heure, zone, secteur, duree_min, volume_m3}. Les secteurs s'enchainent
    (une seule vanne ouverte a la fois), en commencant tot le matin."""
    C = conception or res.get("_conception")
    debut = debut or dt.date.today()
    if isinstance(debut, str):
        debut = dt.date.fromisoformat(debut)
    h0 = dt.datetime.strptime(heure_debut, "%H:%M").time()
    zones_c = [z for z in C.zones if not z.get("vide")]
    ev = []
    for j in range(jours):
        d = debut + dt.timedelta(days=j)
        m = d.month - 1
        t = dt.datetime.combine(d, h0)
        for zr, zc in zip(res["zones"], zones_c):
            prog = zr.get("programme") or []
            if prog:
                p = prog[m]
                if not p["intervalle_j"] or p["duree_min"] <= 0:
                    continue
                if (d - debut).days % p["intervalle_j"]:
                    continue
                duree = p["duree_min"]
            else:  # aspersion : dose journaliere
                mm = zr["mensuel_optimal"][m]["brut_mm_j"]
                if mm <= 0:
                    continue
                duree = (
                    mm
                    * zc["surface_utile_m2"]
                    / 1000
                    / (zc["debit_zone_l_h"] / 1000)
                    * 60
                )
            for s in zc["secteurs"]:
                vol = s["debit_l_h"] * duree / 60 / 1000
                ev.append(
                    {
                        "date": d.isoformat(),
                        "heure": t.strftime("%H:%M"),
                        "zone": zr["nom"],
                        "secteur": s.get("label", ""),
                        "duree_min": int(round(duree)),
                        "volume_m3": round(float(vol), 2),
                        "debit_m3_h": round(float(s["debit_l_h"]) / 1000, 2),
                    }
                )
                t += dt.timedelta(minutes=duree + 2)
    return ev


def ajuster_meteo(evenements, et0_prevu, pluie_prevue=None, climat=None):
    """Correction par l'agent : et0_prevu / pluie_prevue = {date_iso: mm}. climat = dict avec 'et0' mensuel."""
    out = []
    for e in evenements:
        e = dict(e)
        d = dt.date.fromisoformat(e["date"])
        if pluie_prevue and pluie_prevue.get(e["date"], 0) > 5:
            e.update(
                statut="annule", motif=f"pluie prevue {pluie_prevue[e['date']]} mm"
            )
        elif climat and e["date"] in et0_prevu:
            f = et0_prevu[e["date"]] / climat["et0"][d.month - 1]
            f = min(max(f, 0.5), 1.5)
            e["duree_min"] = round(e["duree_min"] * f)
            e["volume_m3"] = round(e["volume_m3"] * f, 2)
            e.update(statut="ajuste", facteur_meteo=round(f, 2))
        out.append(e)
    return out
