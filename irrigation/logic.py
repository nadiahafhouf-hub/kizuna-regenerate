"""Irrigation : pont entre les calculs (irrigation/services, sans Django) et l'interface.

`irrigation_plan_ui(pid)` renvoie les champs attendus par templates/irrigation/irrigation.html
et static/js/irrigation_sim.js (contrat de services/demo_data.irrigation_plan), calcules par
generer_planning() : besoin FAO par zone, annulation pluie, quota de nappe (VERT > ORANGE > ROUGE),
pompage seulement si production solaire >= puissance de la pompe, reservoir jamais deborde.
"""
import datetime
from pathlib import Path

from django.conf import settings
from django.db.utils import DatabaseError

from advisor.logic import CACHE_DIR, recommandation
from .services.meteo import ensoleillement, prevision_7_jours
from .services.planning import PARAMETRES_DEFAUT, generer_planning


def parametres():
    from .models import IrrigationSettings
    try:
        return IrrigationSettings.charger().en_dict()
    except DatabaseError:            # base pas encore migree : valeurs par defaut
        return dict(PARAMETRES_DEFAUT, debit_goutte_m3_h=3.0)


def plan_complet(pid, date_debut=None):
    """Sortie brute de generer_planning (JSON complet, pour le passeport / debug)."""
    reco = recommandation(pid)
    o = reco.get("origine") or {}
    meteo = prevision_7_jours(o.get("lat"), o.get("lon"), reco["climat"], date_debut, cache_dir=CACHE_DIR)
    plan = generer_planning(reco, parametres(), meteo=meteo)
    return reco, meteo, plan


def _hhmm(minutes):
    return f"{int(minutes) // 60 % 24:02d}:{int(minutes) % 60:02d}"


def _temps(pluie, soleil):
    """Icone Lucide + libelle a partir de la pluie et de l'ensoleillement."""
    if pluie >= 5:
        return "cloud-rain", "Rain"
    if pluie >= 1:
        return "cloud-drizzle", "Light rain"
    if soleil < 0.5:
        return "cloud", "Cloudy"
    if soleil < 0.85:
        return "cloud-sun", "Partly cloudy"
    return "sun", "Sunny"


def irrigation_plan_ui(pid, date_debut=None):
    from services import demo_data
    reco, meteo, plan = plan_complet(pid, date_debut)
    p = plan["parametres"]
    lat = (reco.get("origine") or {}).get("lat")
    zones_reco = {z["id"]: z for z in reco["zones"]}
    debit_goutte = p.get("debit_goutte_m3_h", 3.0)
    debit_pompe = p["debit_pompe_m3_h"]
    jours_meteo = {j["date"]: j for j in meteo["jours"]}
    # arrosage traditionnel par jour (submersion, rendement 0,6, sans meteo) : meme base que les totaux
    trad_jour = plan["totaux"]["eau_traditionnelle_l"] / 1000 / max(1, len(plan["jours"]))

    days = []
    for i, j in enumerate(plan["jours"]):
        d = datetime.date.fromisoformat(j["date"])
        evts = [e for e in plan["evenements"] if e["date"] == j["date"]]
        arrosages = [e for e in evts if e["type"] == "ARROSAGE"]
        # creneaux : une vanne a la fois, enchaines a partir de l'heure de chaque dose
        slots, fin = [], 0
        for e in sorted([e for e in arrosages if e["statut"] == "PREVU" and e["volume_l"] > 0],
                        key=lambda e: e["heure"]):
            debut = max(int(e["heure"][:2]) * 60, fin)
            minutes = max(1, round(e["volume_l"] / 1000 / debit_goutte * 60))
            z = zones_reco.get(e["zone_id"], {})
            slots.append({"zone": e["zone_id"], "color": e["couleur"], "plant": z.get("culture", ""),
                          "volume_m3": round(e["volume_l"] / 1000, 3), "leaching_pct": round(z.get("lr", 0) * 100),
                          "minutes": minutes, "start": _hhmm(debut), "reason": e["raison"]})
            fin = debut + minutes
        zone_totals = []
        for zid in dict.fromkeys(sl["zone"] for sl in slots):
            mes = [sl for sl in slots if sl["zone"] == zid]
            zone_totals.append({"zone": zid, "color": mes[0]["color"], "doses": len(mes), "start": mes[0]["start"],
                                "volume_m3": round(sum(sl["volume_m3"] for sl in mes), 2)})
        annulations = sorted({e["raison"] for e in arrosages if e["statut"] == "ANNULE" and e["raison"]})
        reductions = sorted({r.strip() for e in arrosages if e["statut"] == "PREVU"
                             for r in e["raison"].split(" ; ") if r.startswith("reduit")})
        # pompage : fenetre continue a partir de la 1re heure de soleil suffisant (meme volume que le plan)
        pompages = sorted([e for e in evts if e["type"] == "POMPAGE"], key=lambda e: e["heure"])
        volume_pompe = sum(e["volume_l"] for e in pompages) / 1000
        heures = volume_pompe / debit_pompe if debit_pompe else 0
        debut_p = int(pompages[0]["heure"][:2]) * 60 if pompages else 11 * 60
        pompe_h = [0.0] * 24
        for e in pompages:
            pompe_h[int(e["heure"][:2])] = round(p["puissance_pompe_kw"] * min(1.0, e["volume_l"] / 1000 / debit_pompe), 2)
        mj = jours_meteo.get(j["date"], {})
        soleil = ensoleillement(lat, j["date"], j["rayonnement_w_m2"]) if lat is not None else 1.0
        icon, condition = _temps(j["pluie_mm"], soleil)
        days.append({
            "index": i, "date": j["date"], "weekday": d.strftime("%a"), "day": d.day, "month": d.strftime("%b"),
            "icon": icon, "condition": condition,
            "tmax": mj.get("tmax_c") if mj.get("tmax_c") is not None else "–",
            "tmin": mj.get("tmin_c") if mj.get("tmin_c") is not None else "–",
            "et0": j["et0_mm"], "rain": j["pluie_mm"], "cloud": soleil,
            "skipped": not slots, "skip_reason": annulations[0] if annulations and not slots else "",
            "reductions": reductions,
            "slots": slots, "zone_totals": zone_totals,
            "irrigation_m3": round(j["arrose_l"] / 1000, 2),
            "flood_m3": round(trad_jour, 2),
            "pump": {"start": _hhmm(debut_p), "end": _hhmm(debut_p + round(heures * 60)),
                     "hours": round(heures, 2), "volume_m3": round(volume_pompe, 2),
                     "kwh": round(sum(e["energie_kwh"] for e in pompages), 2),
                     "slots_h": [int(e["heure"][:2]) for e in pompages]},
            "solar_kwh": round(sum(j["production_kw"]), 1),
            "hourly": {"solar": j["production_kw"], "pump": pompe_h},
            "reservoir_morning_m3": round(j["niveau_matin_l"] / 1000, 2),
            "reservoir_evening_m3": round(j["niveau_soir_l"] / 1000, 2),
        })

    t = plan["totaux"]
    week = t["arrosage_prevu_l"] / 1000
    flood = t["eau_traditionnelle_l"] / 1000
    heures_pompe = [h for d in days for h in d["pump"]["slots_h"]]
    return {
        "system": {
            "solar_kwp": p["puissance_crete_kwc"], "pump_kw": p["puissance_pompe_kw"], "pump_flow_m3h": debit_pompe,
            "drip_flow_m3h": debit_goutte, "reservoir_m3": p["capacite_reservoir_m3"],
            "reservoir_start_pct": round(p["niveau_initial_m3"] / p["capacite_reservoir_m3"] * 100)
            if p["capacite_reservoir_m3"] else 0,
            "drip_efficiency": 0.9, "flood_efficiency": p["rendement_submersion"],
            "irrigation_start_h": p["heure_arrosage"],
            "pump_start_h": min(heures_pompe) if heures_pompe else 11,
            "pump_end_h": max(heures_pompe) + 1 if heures_pompe else 14,
            "quota_m3": p["quota_nappe_m3_semaine"], "rain_skip_mm": p["seuil_pluie_mm"],
            "moisture_skip_pct": p["seuil_humidite_pct"], "performance_ratio": p["ratio_performance"],
        },
        "days": days,
        "zones": demo_data.zones(pid),
        "totals": {
            "irrigation_m3": round(week, 1), "flood_m3": round(flood, 1),
            "saved_m3": round(max(0.0, flood - week), 1),
            "saved_pct": round((flood - week) / flood * 100) if flood else 0,
            "solar_kwh": round(sum(d["solar_kwh"] for d in days), 1),
            "pump_kwh": round(t["energie_kwh"], 1),
            "pumped_m3": round(t["pompe_prevu_l"] / 1000, 1), "quota_m3": round(t["quota_l"] / 1000, 1),
            "need_m3": round(t["besoin_l"] / 1000, 1),
        },
        "sources": {"meteo": plan["source_meteo"], "climat": reco["climat"].get("detail_source", reco["climat"]["source"]),
                    "ce_eau_dS_m": plan.get("ce_eau_dS_m")},
    }


def evenements_pour_passeport(pid, jours=7):
    """Evenements FAIT et ANNULE de la semaine ecoulee (date, zone, volume, type, raison), pour la chaine
    de hash du bloc 4. L'automate etant simule, on rejoue le planning des `jours` derniers jours :
    un evenement prevu est compte FAIT, une annulation garde sa raison. Ordre chronologique stable."""
    debut = datetime.date.today() - datetime.timedelta(days=jours)
    _, _, plan = plan_complet(pid, debut)
    aujourd_hui = datetime.date.today().isoformat()
    out = []
    for e in sorted(plan["evenements"], key=lambda e: (e["date"], e["heure"], e["zone_id"])):
        if e["date"] >= aujourd_hui or (e["statut"] == "PREVU" and e["volume_l"] <= 0):
            continue
        out.append({"date": e["date"], "heure": e["heure"], "zone_id": e["zone_id"], "type": e["type"],
                    "volume_l": e["volume_l"], "statut": "FAIT" if e["statut"] == "PREVU" else "ANNULE",
                    "energie_kwh": e["energie_kwh"], "raison": e["raison"], "donnees": "simulees"})
    return out
