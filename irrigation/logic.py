"""Irrigation : pont entre les calculs (irrigation/services, sans Django), la base et l'interface.

- Le planning 7 jours est calcule par generer_planning() puis ENREGISTRE (IrrigationPlan + IrrigationEvent).
- Parcours : BROUILLON -> Valider -> VALIDE -> Automatique -> AUTO <-> MANUEL (reprendre la main).
- Automate simule : « Simuler la journee suivante » avance une horloge simulee d'un jour et traite
  les evenements passes (pluie, humidite simulee, reservoir, quota), vannes et journal ValveEvent.
- `irrigation_plan_ui(pid)` garde le contrat de services/demo_data.irrigation_plan (memes champs).
"""
import datetime

from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from advisor.logic import CACHE_DIR, recommandation
from advisor.services.eau import texture_info
from .services.automatisme import decider_arrosage, decider_pompage, humidite_simulee
from .services.meteo import ensoleillement, prevision_7_jours
from .services.planning import PARAMETRES_DEFAUT, generer_planning


# ───────────────────────────── calcul ─────────────────────────────

def parametres():
    from .models import IrrigationSettings
    try:
        return IrrigationSettings.charger().en_dict()
    except DatabaseError:            # base pas encore migree : valeurs par defaut
        return dict(PARAMETRES_DEFAUT, debit_goutte_m3_h=3.0)


def plan_complet(pid, date_debut=None, meteo=None, params=None, volumes_forces=None):
    """(reco, meteo, plan) : sortie brute de generer_planning."""
    reco = recommandation(pid)
    if meteo is None:
        o = reco.get("origine") or {}
        meteo = prevision_7_jours(o.get("lat"), o.get("lon"), reco["climat"], date_debut, cache_dir=CACHE_DIR)
    plan = generer_planning(reco, params or parametres(), meteo=meteo, volumes_forces=volumes_forces)
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


def _vers_ui(pid, reco, meteo, plan):
    """Planning -> format de templates/irrigation/irrigation.html (contrat demo_data.irrigation_plan)."""
    from services import demo_data
    p = plan["parametres"]
    lat = (reco.get("origine") or {}).get("lat")
    zones_reco = {z["id"]: z for z in reco["zones"]}
    debit_goutte = p.get("debit_goutte_m3_h", 3.0)
    debit_pompe = p["debit_pompe_m3_h"]
    jours_meteo = {j["date"]: j for j in meteo["jours"]}
    trad_jour = plan["totaux"]["eau_traditionnelle_l"] / 1000 / max(1, len(plan["jours"]))

    days = []
    for i, j in enumerate(plan["jours"]):
        d = datetime.date.fromisoformat(j["date"])
        evts = [e for e in plan["evenements"] if e["date"] == j["date"]]
        arrosages = [e for e in evts if e["type"] == "ARROSAGE"]
        # creneaux : une vanne a la fois, enchaines a partir de l'heure de chaque dose
        slots, fin = [], 0
        for e in sorted([e for e in arrosages if e["statut"] != "ANNULE" and e["volume_l"] > 0], key=lambda e: e["heure"]):
            debut = max(int(e["heure"][:2]) * 60, fin)
            minutes = max(1, round(e["volume_l"] / 1000 / debit_goutte * 60))
            z = zones_reco.get(e["zone_id"], {})
            slots.append({"zone": e["zone_id"], "color": e["couleur"], "plant": z.get("culture", ""),
                          "volume_m3": round(e["volume_l"] / 1000, 3), "leaching_pct": round(z.get("lr", 0) * 100),
                          "minutes": minutes, "start": _hhmm(debut), "reason": e["raison"], "status": e["statut"]})
            fin = debut + minutes
        zone_totals = []
        for zid in dict.fromkeys(sl["zone"] for sl in slots):
            mes = [sl for sl in slots if sl["zone"] == zid]
            zone_totals.append({"zone": zid, "color": mes[0]["color"], "doses": len(mes), "start": mes[0]["start"],
                                "volume_m3": round(sum(sl["volume_m3"] for sl in mes), 2),
                                "done": all(sl["status"] == "FAIT" for sl in mes)})
        annulations = sorted({e["raison"] for e in arrosages if e["statut"] == "ANNULE" and e["raison"]})
        reductions = sorted({r.strip() for e in arrosages if e["statut"] != "ANNULE"
                             for r in e["raison"].split(" ; ") if r.startswith("reduit")})
        pompages = sorted([e for e in evts if e["type"] == "POMPAGE" and e["statut"] != "ANNULE"], key=lambda e: e["heure"])
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
            "reductions": reductions, "slots": slots, "zone_totals": zone_totals,
            "irrigation_m3": round(sum(sl["volume_m3"] for sl in slots), 2),
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


# ───────────────────────────── base de données ─────────────────────────────

def _aware(d, t=datetime.time(0, 0)):
    return timezone.make_aware(datetime.datetime.combine(d, t))


def parcelle_db(pid):
    """Ligne core.Parcel (creee a partir de la parcelle de demo / LandProfile si besoin)."""
    from core.models import Parcel
    from services import demo_data
    info = demo_data.parcel(pid)           # 404 si inconnue
    lp = demo_data.land_profile(pid)
    o = lp.get("origine") or {}
    parcel, _ = Parcel.objects.get_or_create(parcelle_id=pid, defaults=dict(
        nom=info.get("name", ""), agriculteur=info.get("farmer", ""), region=lp.get("region", "Gabes"),
        origine_lat=o.get("lat", 0), origine_lon=o.get("lon", 0), largeur_m=lp.get("largeur_m", 30),
        longueur_m=lp.get("longueur_m", 30), taille_case_m=lp.get("taille_case_m", 10),
        texture_sol=lp.get("texture_sol", "")))
    return parcel


def _enregistrer(plan_db, plan):
    from .models import IrrigationEvent
    plan_db.programme.all().delete()
    IrrigationEvent.objects.bulk_create([
        IrrigationEvent(plan=plan_db, zone_id=e["zone_id"], couleur=e.get("couleur", ""),
                        date=datetime.date.fromisoformat(e["date"]),
                        heure=datetime.time(*map(int, e["heure"].split(":"))), type=e["type"],
                        volume_l=e["volume_l"], volume_prevu_l=e["volume_l"], energie_kwh=e.get("energie_kwh", 0),
                        statut=e["statut"], raison=e["raison"], ordre=i)
        for i, e in enumerate(plan["evenements"])])


def _appliquer(plan_db, plan):
    plan_db.planning = {k: v for k, v in plan.items() if k != "evenements"}
    plan_db.date_debut = datetime.date.fromisoformat(plan["date_debut"])
    plan_db.quota_m3 = plan["parametres"]["quota_nappe_m3_semaine"]
    plan_db.horloge = _aware(plan_db.date_debut)
    plan_db.culture = ", ".join(sorted({z["culture"] for z in plan["zones"]}))[:80]


def _init_vannes(plan_db):
    from .models import ValveState
    for z in plan_db.planning.get("zones", []):
        v, _ = ValveState.objects.get_or_create(parcel=plan_db.parcel, zone_id=z["id"])
        v.ouverte = False
        v.derniere_action = "closed (new plan)"
        v.save()


@transaction.atomic
def creer_plan(pid):
    from .models import IrrigationPlan
    parcel = parcelle_db(pid)
    reco, meteo, plan = plan_complet(pid)
    plan_db = IrrigationPlan(parcel=parcel, meteo=meteo, statut=IrrigationPlan.Statut.BROUILLON)
    _appliquer(plan_db, plan)
    plan_db.save()
    _enregistrer(plan_db, plan)
    _init_vannes(plan_db)
    return plan_db


def plan_actif(pid, creer=True):
    """Dernier planning de la parcelle ; on en cree un s'il n'y en a pas (ou s'il est perime)."""
    from .models import IrrigationPlan
    parcel = parcelle_db(pid)
    plan_db = IrrigationPlan.objects.filter(parcel=parcel).exclude(planning={}).first()
    if plan_db is None and creer:
        plan_db = creer_plan(pid)
    return plan_db


@transaction.atomic
def regenerer(plan_db):
    """Apres « Modifier un volume » : tout est recalcule (quota, pompage, reservoir), meme meteo."""
    from .models import IrrigationPlan
    pid = plan_db.parcel.parcelle_id
    _, _, plan = plan_complet(pid, meteo=plan_db.meteo, params=plan_db.planning.get("parametres"),
                              volumes_forces=plan_db.volumes_forces)
    _appliquer(plan_db, plan)
    plan_db.statut = IrrigationPlan.Statut.BROUILLON
    plan_db.save()
    _enregistrer(plan_db, plan)
    _init_vannes(plan_db)
    return plan_db


def plan_db_vers_dict(plan_db):
    """Planning stocke + evenements a jour (statut, volume, raison) depuis la base."""
    plan = dict(plan_db.planning)
    plan["evenements"] = [{"zone_id": e.zone_id, "couleur": e.couleur, "date": e.date.isoformat(),
                           "heure": e.heure.strftime("%H:%M"), "type": e.type, "volume_l": e.volume_l,
                           "statut": e.statut, "raison": e.raison, "energie_kwh": e.energie_kwh}
                          for e in plan_db.programme.all()]
    return plan


def irrigation_plan_ui(pid, date_debut=None):
    """Contrat de demo_data.irrigation_plan : le planning enregistre (sinon calcule a la volee)."""
    plan_db = None
    try:
        plan_db = plan_actif(pid)
    except DatabaseError:
        pass
    if plan_db is not None:
        reco = recommandation(pid)
        return _vers_ui(pid, reco, plan_db.meteo, plan_db_vers_dict(plan_db))
    reco, meteo, plan = plan_complet(pid, date_debut)
    return _vers_ui(pid, reco, meteo, plan)


# ───────────────────────────── automate simule ─────────────────────────────

def niveau_reservoir_l(plan_db):
    faits = plan_db.programme.filter(statut="FAIT")
    pompe = sum(e.volume_l for e in faits if e.type == "POMPAGE")
    arrose = sum(e.volume_l for e in faits if e.type == "ARROSAGE")
    return plan_db.planning["totaux"]["niveau_initial_l"] + pompe - arrose, pompe, arrose


def _jour(plan_db, date):
    return next((j for j in plan_db.planning.get("jours", []) if j["date"] == date.isoformat()), {"pluie_mm": 0})


def tick(plan_db):
    """Traite les evenements PREVU dont l'heure simulee est passee. Seulement en mode AUTO."""
    from .models import IrrigationPlan, SoilMoistureReading, ValveEvent, ValveState
    if plan_db.statut != IrrigationPlan.Statut.AUTO:
        return []
    p = plan_db.planning["parametres"]
    texture = texture_info(plan_db.parcel.texture_sol)["nom"]
    cap_l = p["capacite_reservoir_m3"] * 1000
    quota_l = p["quota_nappe_m3_semaine"] * 1000
    niveau, pompe_total, _ = niveau_reservoir_l(plan_db)
    traites = []
    a_faire = [e for e in plan_db.programme.filter(statut="PREVU") if _aware(e.date, e.heure) <= plan_db.horloge]
    for e in sorted(a_faire, key=lambda x: (x.date, x.heure, x.ordre)):
        quand = _aware(e.date, e.heure)
        with transaction.atomic():
            if e.type == "POMPAGE":
                statut, vol, raison = decider_pompage(e.volume_l, niveau, cap_l, pompe_total, quota_l)
                e.energie_kwh = round(vol / (p["debit_pompe_m3_h"] * 1000) * p["puissance_pompe_kw"], 3) if vol else 0
                if statut == "FAIT":
                    niveau += vol
                    pompe_total += vol
                    ValveEvent.objects.create(plan=plan_db, horodatage=quand, action="POMPAGE_RESERVOIR",
                                              volume_l=vol, energie="SOLAIRE")
            else:
                j = _jour(plan_db, e.date)
                veille = e.date - datetime.timedelta(days=1)
                arrose_veille = plan_db.programme.filter(zone_id=e.zone_id, date=veille, statut="FAIT").exists()
                hum = humidite_simulee(texture, j.get("pluie_mm", 0), _jour(plan_db, veille).get("pluie_mm", 0),
                                       arrose_veille, graine=f"{plan_db.parcel_id}|{e.zone_id}|{e.date}|{e.heure}")
                SoilMoistureReading.objects.create(parcel=plan_db.parcel, zone_id=e.zone_id, humidite_pct=hum,
                                                   horodatage=quand)
                statut, vol, raison = decider_arrosage(e.volume_l, j.get("pluie_mm", 0), hum, niveau,
                                                       p["seuil_pluie_mm"], p["seuil_humidite_pct"])
                vanne, _ = ValveState.objects.get_or_create(parcel=plan_db.parcel, zone_id=e.zone_id)
                if statut == "FAIT":
                    vanne.ouverte = True                      # ouverture...
                    vanne.save()
                    ValveEvent.objects.create(plan=plan_db, horodatage=quand, action="OUVERTURE",
                                              volume_l=vol, energie="RESERVOIR")
                    niveau -= vol
                    vanne.ouverte = False                     # ...fermeture une fois le volume passe
                    fin = quand + datetime.timedelta(minutes=max(1, round(vol / 1000 / p.get("debit_goutte_m3_h", 3.0) * 60)))
                    ValveEvent.objects.create(plan=plan_db, horodatage=fin, action="FERMETURE", energie="RESERVOIR")
                    vanne.derniere_action = f"opened {e.date:%d/%m} {e.heure:%H:%M}: {vol} L, then closed (soil {hum:g} %)"
                else:
                    vanne.derniere_action = f"stayed closed {e.date:%d/%m} {e.heure:%H:%M}: {raison}"
                vanne.save()
            e.statut, e.volume_l, e.raison, e.traite_le = statut, vol, raison, plan_db.horloge
            e.save()
            traites.append({"zone_id": e.zone_id, "type": e.type, "date": e.date.isoformat(),
                            "heure": e.heure.strftime("%H:%M"), "volume_l": vol, "statut": statut, "raison": raison})
    return traites


def simuler_jour_suivant(plan_db):
    """Bouton de demo : avance l'horloge simulee d'un jour puis lance le tick."""
    fin = _aware(plan_db.date_debut + datetime.timedelta(days=7))
    if plan_db.horloge >= fin:
        return []
    plan_db.horloge = min(fin, plan_db.horloge + datetime.timedelta(days=1))
    plan_db.save(update_fields=["horloge"])
    return tick(plan_db)


def etat(plan_db):
    """Etat en direct : vannes, reservoir, quota, eau economisee, derniers evenements."""
    from .models import SoilMoistureReading, ValveState
    p = plan_db.planning["parametres"]
    niveau, pompe, arrose = niveau_reservoir_l(plan_db)
    cap_l = p["capacite_reservoir_m3"] * 1000
    quota_l = p["quota_nappe_m3_semaine"] * 1000
    jours_ecoules = max(0, min(7, (plan_db.horloge - _aware(plan_db.date_debut)).days))
    totaux = plan_db.planning["totaux"]
    trad_jour = totaux["eau_traditionnelle_l"] / max(1, len(plan_db.planning["jours"]))
    trad = trad_jour * jours_ecoules
    kwh = sum(e.energie_kwh for e in plan_db.programme.filter(type="POMPAGE", statut="FAIT"))
    zones = {z["id"]: z for z in plan_db.planning.get("zones", [])}
    humid = {}
    for h in SoilMoistureReading.objects.filter(parcel=plan_db.parcel, horodatage__lte=plan_db.horloge)[:60]:
        humid.setdefault(h.zone_id, h.humidite_pct)
    vannes = [{"zone_id": v.zone_id, "ouverte": v.ouverte, "derniere_action": v.derniere_action,
               "couleur": zones[v.zone_id]["couleur"], "culture": zones[v.zone_id]["culture"],
               "humidite_pct": humid.get(v.zone_id)}
              for v in ValveState.objects.filter(parcel=plan_db.parcel, zone_id__in=list(zones))]
    derniers = [{"zone_id": e.zone_id, "type": e.type, "date": e.date.isoformat(), "heure": e.heure.strftime("%H:%M"),
                 "volume_l": e.volume_l, "statut": e.statut, "raison": e.raison}
                for e in plan_db.programme.exclude(statut="PREVU").exclude(traite_le=None)
                .order_by("-date", "-heure", "-ordre")[:12]]
    return {
        "plan_id": plan_db.id, "statut": plan_db.statut,
        "horloge": timezone.localtime(plan_db.horloge).strftime("%a %d %b · %H:%M"),
        "jours_ecoules": jours_ecoules, "semaine_finie": jours_ecoules >= 7,
        "vannes": vannes,
        "reservoir": {"niveau_l": round(niveau), "capacite_l": round(cap_l),
                      "pct": round(100 * niveau / cap_l) if cap_l else 0},
        "quota": {"pompe_l": round(pompe), "quota_l": round(quota_l),
                  "pct": round(100 * pompe / quota_l) if quota_l else 0},
        "economie": {"traditionnel_m3": round(trad / 1000, 2), "arrose_m3": round(arrose / 1000, 2),
                     "economise_m3": round(max(0, trad - arrose) / 1000, 2), "kwh": round(kwh, 2)},
        "compteurs": {s: plan_db.programme.filter(statut=s).count() for s in ("PREVU", "FAIT", "ANNULE")},
        "derniers": derniers,
    }


def evenements_pour_passeport(pid):
    """Evenements FAIT et ANNULE deja passes (horloge simulee), pour la chaine de hash du bloc 4.
    Ordre chronologique stable : date, heure, plan, ordre."""
    from .models import IrrigationEvent
    qs = (IrrigationEvent.objects.select_related("plan")
          .filter(plan__parcel__parcelle_id=pid, statut__in=["FAIT", "ANNULE"])
          .order_by("date", "heure", "plan_id", "ordre"))
    return [{"plan_id": e.plan_id, "date": e.date.isoformat(), "heure": e.heure.strftime("%H:%M"),
             "zone_id": e.zone_id, "type": e.type, "volume_l": e.volume_l, "statut": e.statut,
             "energie_kwh": e.energie_kwh, "raison": e.raison, "donnees": "simulees"}
            for e in qs if e.traite_le or (e.plan.horloge and _aware(e.date, e.heure) <= e.plan.horloge)]
