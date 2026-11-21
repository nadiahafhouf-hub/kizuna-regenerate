"""Données de démo pour l'interface.

TOUTES les pages lisent leurs données ici. Chaque fonction sera remplacée par le vrai
calcul du bloc correspondant (diagnostics.pipeline, advisor, irrigation, passport) sans
toucher aux templates : garder les mêmes noms de champs.

Sources : fixtures/land_profile.sample.json + fixtures/demo/*.json
"""
import copy
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.http import Http404

from diagnostics.couleur import couleur_case
from diagnostics.geo import M_PAR_DEG_LAT
from services import seuils as S
from services.cultures import CULTURES, KC, cultures_compatibles

FIXTURES = Path(settings.BASE_DIR) / "fixtures"
DEMO = FIXTURES / "demo"
COLORS = ("ROUGE", "ORANGE", "VERT")
GENESIS_HASH = "0" * 64
DEMO_PARCEL = "GAB-001"


def _read(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ───────────────────────────────── Parcelles ─────────────────────────────────

def _parcel_records():
    return _read(DEMO / "parcels.json")


def _record(pid):
    for p in _parcel_records():
        if p["id"] == pid:
            return p
    raise Http404(f"Unknown parcel {pid}")


def land_profile(pid) -> dict:
    """LandProfile (contrat du bloc 1). Remplacé plus tard par diagnostics.contract.latest_for."""
    return _read(FIXTURES / _record(pid)["land_profile"])


def _deg(lat):
    """Degrés par mètre (lat, lon) à cette latitude."""
    return 1 / M_PAR_DEG_LAT, 1 / (M_PAR_DEG_LAT * math.cos(math.radians(lat)))


def cell_center(profile, ligne, col):
    o, t = profile["origine"], profile["taille_case_m"]
    dlat, dlon = _deg(o["lat"])
    return o["lat"] - (ligne + 0.5) * t * dlat, o["lon"] + (col + 0.5) * t * dlon


def parcel_bounds(profile):
    o = profile["origine"]
    dlat, dlon = _deg(o["lat"])
    sud = o["lat"] - profile["longueur_m"] * dlat
    est = o["lon"] + profile["largeur_m"] * dlon
    return [[sud, o["lon"]], [o["lat"], est]]


def _zone_shares(profile):
    area = profile["largeur_m"] * profile["longueur_m"]
    shares = {c: 0.0 for c in COLORS}
    for z in profile["zones"]:
        shares[z["couleur"]] += z["surface_m2"]
    return {c: round(v / area * 100, 1) for c, v in shares.items()}, area


def _worst(colors):
    for c in COLORS:
        if c in colors:
            return c
    return "VERT"


def parcel(pid) -> dict:
    rec = copy.deepcopy(_record(pid))
    prof = land_profile(pid)
    shares, area = _zone_shares(prof)
    (s, w), (n, e) = parcel_bounds(prof)
    rec.update({
        "area_m2": area,
        "area_ha": area / 10_000,
        "shares": shares,
        "healthy_pct": shares["VERT"],
        "worst": _worst([z["couleur"] for z in prof["zones"]]),
        "zones_count": len(prof["zones"]),
        "cells_count": len(prof["cases"]),
        "last_reading": prof["date_mesure"],
        "texture": prof["texture_sol"],
        "size": f'{prof["largeur_m"]} × {prof["longueur_m"]} m',
        "center": [(s + n) / 2, (w + e) / 2],
        "bounds": [[s, w], [n, e]],
    })
    return rec


def parcels() -> list[dict]:
    return [parcel(p["id"]) for p in _parcel_records()]


def global_kpis() -> dict:
    ps = parcels()
    area = sum(p["area_m2"] for p in ps)
    healthy = sum(p["area_m2"] * p["healthy_pct"] / 100 for p in ps)
    return {
        "water_saved_m3": sum(p["season"]["water_saved_m3"] for p in ps),
        "solar_kwh": sum(p["season"]["solar_kwh"] for p in ps),
        "healthy_pct": round(healthy / area * 100, 1) if area else 0,
        "parcels": len(ps),
        "area_m2": area,
    }


# ───────────────────────────────── Bloc 1 : diagnostic ─────────────────────────────────

THRESHOLDS = {
    # clé: (unité, seuil orange, seuil rouge, échelle max de la jauge)
    "CE_dS_m": ("dS/m", S.CE_STRESS, S.CE_SEVERE, 15.0),
    "Cd_mg_kg": ("mg/kg", S.CD_SEUIL_SAIN, S.CD_LIMITE_UE, 8.0),
    "Pb_mg_kg": ("mg/kg", S.PB_RISQUE_MODERE, S.PB_RISQUE_ELEVE, 180.0),
}
PH_SCALE = (4.0, 10.0)


def _status_one_sided(value, warn, crit):
    return "ROUGE" if value >= crit else "ORANGE" if value >= warn else "VERT"


def _status_ph(ph):
    if ph <= S.PH_ACIDE_SEVERE or ph >= S.PH_ALCALIN_SEVERE:
        return "ROUGE"
    if ph <= S.PH_ACIDE_STRESS or ph >= S.PH_ALCALIN_STRESS:
        return "ORANGE"
    return "VERT"


def threshold_rows(values: dict) -> list[dict]:
    """Lignes « valeur vs seuils » pour CE, pH, Cd, Pb (composant threshold_row)."""
    rows = []
    for key in ("CE_dS_m", "pH", "Cd_mg_kg", "Pb_mg_kg"):
        v = float(values[key])
        if key == "pH":
            lo, hi = PH_SCALE
            pct = lambda x: round((x - lo) / (hi - lo) * 100, 1)  # noqa: E731
            rows.append({
                "key": key, "value": v, "unit": "", "status": _status_ph(v),
                "pct": max(0, min(100, pct(v))),
                "ticks": [pct(S.PH_ACIDE_STRESS), pct(S.PH_ALCALIN_STRESS)],
                "range": f"{S.PH_ACIDE_STRESS}–{S.PH_ALCALIN_STRESS}",
            })
        else:
            unit, warn, crit, scale = THRESHOLDS[key]
            rows.append({
                "key": key, "value": v, "unit": unit,
                "status": _status_one_sided(v, warn, crit),
                "pct": max(0, min(100, round(v / scale * 100, 1))),
                "ticks": [round(warn / scale * 100, 1), round(crit / scale * 100, 1)],
                "range": f"< {warn:g}",
                "limit": crit,
            })
    return rows


def _zone_of(profile, ligne, col):
    for z in profile["zones"]:
        if [ligne, col] in z["cases"]:
            return z
    return None


def case_detail(pid, ligne, col) -> dict:
    prof = land_profile(pid)
    for c in prof["cases"]:
        if c["ligne"] == ligne and c["col"] == col:
            lat, lon = cell_center(prof, ligne, col)
            zone = _zone_of(prof, ligne, col)
            return {**c, "lat": lat, "lon": lon, "zone": zone, "rows": threshold_rows(c),
                    "size_m": prof["taille_case_m"]}
    raise Http404("Unknown cell")


def sensors(pid, extra=()) -> list[dict]:
    """Capteurs physiques = cases mesurées (source « capteur ») + relevés ajoutés en session."""
    prof = land_profile(pid)
    out = []
    for c in prof["cases"]:
        if c["source"] == "capteur":
            lat, lon = cell_center(prof, c["ligne"], c["col"])
            out.append({**c, "id": f"S{len(out) + 1}", "lat": lat, "lon": lon,
                        "date": prof["date_mesure"], "new": False})
    for r in extra:
        lat, lon = cell_center(prof, r["ligne"], r["col"])
        out.append({**r, "id": f"S{len(out) + 1}", "lat": lat, "lon": lon, "new": True})
    return out


def make_reading(ligne, col, ce, ph, cd, pb, when) -> dict:
    """Relevé saisi dans la modale « New sensor reading ». La couleur vient de couleur_case()."""
    return {"ligne": ligne, "col": col, "CE_dS_m": ce, "pH": ph, "Cd_mg_kg": cd,
            "Pb_mg_kg": pb, "date": when, "source": "capteur",
            "couleur": couleur_case(ce, ph, cd, pb)}


def pollution_sources() -> list[dict]:
    return _read(DEMO / "pollution_sources.json")


def zones(pid) -> list[dict]:
    """Zones enrichies (valeurs max, part de surface) pour les cartes de zone."""
    prof = land_profile(pid)
    area = prof["largeur_m"] * prof["longueur_m"]
    out = []
    for z in prof["zones"]:
        cells = [c for c in prof["cases"] if [c["ligne"], c["col"]] in z["cases"]]
        months = z["traitement"]["mois_avant_sain"]
        out.append({
            **z,
            "share_pct": round(z["surface_m2"] / area * 100),
            "ce_max": max(c["CE_dS_m"] for c in cells),
            "cd_max": max(c["Cd_mg_kg"] for c in cells),
            "pb_max": max(c["Pb_mg_kg"] for c in cells),
            "cells_count": len(cells),
            "months": months,
            # anneau du compte à rebours : 36 mois = anneau plein
            "months_pct": min(100, round(months / 36 * 100)),
        })
    return out


# ───────────────────────────────── Bloc 2 : cultures ─────────────────────────────────

def _crops_meta():
    return _read(DEMO / "crops.json")


def crop_catalog() -> list[dict]:
    meta = _crops_meta()["crops"]
    return [{**c, **meta.get(c["nom"], {"en": c["nom"], "icon": "sprout",
                                         "income_tnd_ha": 0, "spacing_m": 1.0})}
            for c in CULTURES]


WATER_LEVEL = {"FAIBLE": 1, "MOYEN": 2, "ELEVE": 3}


def crop_recommendations(pid) -> list[dict]:
    """Bloc 2 branché : vraies règles de advisor.logic (une culture par zone verte,
    traitement du bloc 1 pour ROUGE/ORANGE, jamais d'alimentaire sur zone interdite).
    En cas d'erreur, on retombe sur l'ancienne version démo : la page ne plante jamais."""
    try:
        from advisor.logic import crop_recommendations_ui
        return crop_recommendations_ui(pid)["zones"]
    except Http404:
        raise
    except Exception:
        return _crop_recommendations_demo(pid)


def _crop_recommendations_demo(pid) -> list[dict]:
    """Ancienne version démo (secours). Zone ROUGE : plantes de dépollution
    uniquement, jamais de culture alimentaire."""
    meta = _crops_meta()
    catalog = {c["nom"]: c for c in crop_catalog()}
    out = []
    for z in zones(pid):
        if z["couleur"] == "ROUGE":
            plants = [{"latin": p, **meta["remediation_plants"].get(
                p, {"en": p, "role": "", "icon": "leaf"})} for p in z["traitement"]["plantes"]]
            out.append({"zone": z, "remediation": plants, "crops": []})
            continue
        crops = []
        # cultures_compatibles() exige un seuil FAO ≥ CE (aucune perte de rendement) ;
        # pour le conseil on accepte une légère perte (seuil ≥ 80 % de la CE), signalée sur la carte.
        strict = {c["nom"] for c in cultures_compatibles(z["couleur"], z["ce_max"])}
        for full in catalog.values():
            if z["couleur"] == "ORANGE" and full["alimentaire"]:
                continue
            if full["nom"] not in strict and full["ce_seuil"] < 0.8 * z["ce_max"]:
                continue
            margin = full["ce_seuil"] - z["ce_max"]
            crops.append({**full, "water_level": WATER_LEVEL[full["besoin_eau"]],
                          "salt_margin": round(margin, 1),
                          "salt_pct": min(100, round(full["ce_seuil"] / 20 * 100))})
        # zone verte : cultures alimentaires d'abord, puis par revenu
        crops.sort(key=lambda c: (-(z["couleur"] == "VERT" and c["alimentaire"]), -c["income_tnd_ha"]))
        out.append({"zone": z, "remediation": [], "crops": crops[:6]})
    return out


IRRIGATION_TYPES = ("GOUTTE_A_GOUTTE", "ASPERSION", "GRAVITAIRE", "AUCUNE")


def score_planting(pid, zone_id, crop_nom, spacing_m, irrigation, photo_name=None) -> dict:
    """Score d'optimalité /100 (simulé mais basé sur les vraies règles) + actions concrètes."""
    zone = next((z for z in zones(pid) if z["id"] == zone_id), None)
    crop = next((c for c in crop_catalog() if c["nom"] == crop_nom), None)
    if zone is None or crop is None:
        raise Http404("Unknown zone or crop")

    actions, crit = [], []

    # 1. Compatibilité avec la zone (30)
    if zone["couleur"] == "ROUGE" and crop["alimentaire"]:
        s1 = 0
        actions.append(("high", "octagon-alert", "food_in_red"))
    elif zone["couleur"] == "ORANGE" and crop["alimentaire"]:
        s1 = 10
        actions.append(("high", "triangle-alert", "food_in_orange"))
    else:
        s1 = 30
    crit.append({"key": "zone", "score": s1, "max": 30})

    # 2. Tolérance au sel (30)
    margin = crop["ce_seuil"] - zone["ce_max"]
    s2 = 30 if margin >= 2 else 22 if margin >= 0 else max(0, round(30 + margin * 6))
    if margin < 0:
        actions.append(("high", "waves", "salt_stress"))
    elif margin < 2:
        actions.append(("medium", "waves", "salt_margin"))
    crit.append({"key": "salt", "score": s2, "max": 30})

    # 3. Espacement (20)
    rec = crop["spacing_m"]
    dev = abs(spacing_m - rec) / rec if rec else 0
    s3 = 20 if dev <= 0.15 else 12 if dev <= 0.4 else 5
    if s3 < 20:
        actions.append(("medium", "ruler", "spacing_wider" if spacing_m < rec else "spacing_tighter"))
    crit.append({"key": "spacing", "score": s3, "max": 20})

    # 4. Irrigation et regroupement par besoin en eau (20)
    s4 = {"GOUTTE_A_GOUTTE": 20, "ASPERSION": 12, "GRAVITAIRE": 5, "AUCUNE": 8}[irrigation]
    if irrigation == "ASPERSION" and zone["ce_max"] >= S.CE_STRESS:
        s4 = 7
        actions.append(("high", "droplets", "sprinkler_salt"))
    elif irrigation in ("GRAVITAIRE", "ASPERSION"):
        actions.append(("medium", "droplets", "switch_drip"))
    if crop["besoin_eau"] == "ELEVE":
        s4 = max(0, s4 - 4)
        actions.append(("low", "layers", "group_water"))
    crit.append({"key": "water", "score": s4, "max": 20})

    if zone["couleur"] != "VERT":
        actions.append(("low", "flask-conical", "retest"))
    if not actions:
        actions.append(("low", "circle-check", "all_good"))

    total = sum(c["score"] for c in crit)
    for c in crit:
        c["pct"] = round(c["score"] / c["max"] * 100)
    stress = []
    if margin < 0:
        stress.append("leaf_tip_burn")
    if zone["cd_max"] >= S.CD_SEUIL_SAIN:
        stress.append("metal_uptake_risk")
    return {
        "score": total,
        "grade": "VERT" if total >= 75 else "ORANGE" if total >= 50 else "ROUGE",
        "criteria": crit,
        "actions": [{"priority": p, "icon": i, "key": k} for p, i, k in actions],
        "zone": zone, "crop": crop, "spacing_m": spacing_m, "irrigation": irrigation,
        "photo": {
            "name": photo_name,
            "detected": crop["en"],
            "confidence": 86,
            "canopy_pct": 62 if margin >= 0 else 41,
            "stress": stress,
        },
    }


# ───────────────────────────────── Bloc 3 : irrigation ─────────────────────────────────

def _kc_for(zone):
    plant = zone["traitement"]["plantes"][0]
    key = {"Atriplex halimus": "Atriplex", "Noccaea caerulescens": "Atriplex",
           "Sedum alfredii": "Atriplex"}.get(plant, plant)
    return plant, KC.get(key, 0.8)


def _solar_curve(kwp, cloud):
    """Production horaire (kW) pour une journée de novembre : lever ~6h30, coucher ~17h30."""
    return [round(max(0.0, kwp * 0.85 * math.sin(math.pi * (h + 0.5 - 6.5) / 11)) * cloud, 2)
            if 6 <= h <= 17 else 0.0 for h in range(24)]


def irrigation_plan(pid, start=None) -> dict:
    """Planning 7 jours branché sur irrigation.logic : météo Open-Meteo, besoin FAO par zone,
    annulation pluie, quota de nappe (VERT > ORANGE > ROUGE), pompage seulement si le solaire
    suffit, réservoir jamais débordé. En cas d'erreur : ancienne version démo (la page ne plante jamais)."""
    try:
        from irrigation.logic import irrigation_plan_ui
        return irrigation_plan_ui(pid, start)
    except Http404:
        raise
    except Exception:
        return _irrigation_plan_demo(pid, start)


def _irrigation_plan_demo(pid, start=None) -> dict:
    """Ancienne version démo (secours) : irrigation à 6 h par gravité, pompage solaire à midi."""
    cfg = _read(DEMO / "irrigation.json")
    sysc, week = cfg["system"], cfg["week"]
    start = start or date.today()
    zs = zones(pid)
    days = []
    for i, w in enumerate(week):
        d = start + timedelta(days=i)
        slots = []
        need_net = 0.0
        flood = 0.0
        for z in zs:
            plant, kc = _kc_for(z)
            net_mm = max(0.0, w["et0"] * kc - 0.8 * w["rain"])
            lf = 0.25 if z["ce_max"] >= S.CE_SEVERE else 0.15 if z["ce_max"] >= S.CE_STRESS else 0.05
            net_m3 = net_mm * z["surface_m2"] / 1000
            gross = net_m3 / sysc["drip_efficiency"] / (1 - lf)
            need_net += gross
            flood += net_m3 / sysc["flood_efficiency"]
            if gross > 0.01:
                slots.append({"zone": z["id"], "color": z["couleur"], "plant": plant,
                              "volume_m3": round(gross, 2), "leaching_pct": round(lf * 100),
                              "minutes": max(5, round(gross / sysc["drip_flow_m3h"] * 60))})
        # horaires d'irrigation enchaînés à partir de 6 h
        t = sysc["irrigation_start_h"] * 60
        for s in slots:
            s["start"] = f"{t // 60:02d}:{t % 60:02d}"
            t += s["minutes"]
        solar = _solar_curve(sysc["solar_kwp"], w["cloud"])
        pump_h = min(sysc["pump_end_h"] - sysc["pump_start_h"], need_net / sysc["pump_flow_m3h"])
        pump = [0.0] * 24
        rem = pump_h
        for h in range(sysc["pump_start_h"], sysc["pump_end_h"]):
            frac = max(0.0, min(1.0, rem))
            pump[h] = round(sysc["pump_kw"] * frac, 2)
            rem -= frac
        end_min = sysc["pump_start_h"] * 60 + round(pump_h * 60)
        days.append({
            "index": i, "date": d.isoformat(), "weekday": d.strftime("%a"), "day": d.day,
            "month": d.strftime("%b"), **w,
            "skipped": not slots,
            "slots": slots,
            "irrigation_m3": round(need_net, 2),
            "flood_m3": round(flood, 2),
            "pump": {"start": f'{sysc["pump_start_h"]:02d}:00',
                     "end": f"{end_min // 60:02d}:{end_min % 60:02d}",
                     "hours": round(pump_h, 2),
                     "volume_m3": round(pump_h * sysc["pump_flow_m3h"], 2),
                     "kwh": round(sum(pump), 2)},
            "solar_kwh": round(sum(solar), 1),
            "hourly": {"solar": solar, "pump": pump},
        })
    week_m3 = sum(d["irrigation_m3"] for d in days)
    week_flood = sum(d["flood_m3"] for d in days)
    saved = week_flood - week_m3
    return {
        "system": sysc,
        "days": days,
        "zones": zs,
        "totals": {
            "irrigation_m3": round(week_m3, 1),
            "flood_m3": round(week_flood, 1),
            "saved_m3": round(saved, 1),
            "saved_pct": round(saved / week_flood * 100) if week_flood else 0,
            "solar_kwh": round(sum(d["solar_kwh"] for d in days), 1),
            "pump_kwh": round(sum(d["pump"]["kwh"] for d in days), 1),
        },
    }


# ───────────────────────────────── Bloc 4 : passeport ─────────────────────────────────

def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(prev, event) -> str:
    core = {k: event[k] for k in ("type", "date", "title", "data")}
    return hashlib.sha256((prev + _canonical(core)).encode("utf-8")).hexdigest()


def passport(pid, tampered=False) -> dict:
    """Chaîne de hash locale : hash_n = sha256(hash_{n-1} + JSON canonique de l'événement).
    `tampered=True` modifie un événement APRÈS scellement pour la démo /verify."""
    events = copy.deepcopy(_read(DEMO / "passport_events.json")[pid])
    prev = GENESIS_HASH
    for ev in events:
        ev["prev_hash"] = prev
        ev["hash"] = _hash(prev, ev)
        prev = ev["hash"]
    if tampered and len(events) > 1:
        # quelqu'un « améliore » l'ancienne analyse : la chaîne doit le détecter
        events[0]["data"]["cd_max"] = 0.8
        events[0]["summary"] = "9 cells measured. Max Cd 0.8 mg/kg."
    # vérification : recalcul de chaque hash à partir des données stockées
    prev, intact = GENESIS_HASH, True
    for ev in events:
        ok = ev["prev_hash"] == prev and _hash(ev["prev_hash"], ev) == ev["hash"]
        ev["valid"] = ok and intact
        intact = intact and ok
        prev = ev["hash"]
    p = parcel(pid)
    zs = zones(pid)
    pid_str = f"{pid}-P{len(events)}" + ("-T" if tampered else "")
    return {
        "id": pid_str,
        "parcel": p,
        "zones": zs,
        "events": events,
        "intact": intact,
        "head_hash": events[-1]["hash"],
        "issued": events[-1]["date"],
        "status": p["worst"],
        "food_area_m2": sum(z["surface_m2"] for z in zs if z["culture_alimentaire_autorisee"]),
    }


def passport_by_id(passport_id) -> dict:
    """/verify/<id>/ : « GAB-001-P4 » (ou « GAB-001-P4-T » = démo falsifiée)."""
    tampered = passport_id.endswith("-T")
    base = passport_id[:-2] if tampered else passport_id
    if "-P" not in base:
        raise Http404("Unknown passport")
    pid = base.rsplit("-P", 1)[0]
    _record(pid)
    data = passport(pid, tampered=tampered)
    if data["id"] != passport_id:
        raise Http404("Unknown passport")
    return data


def passport_pdf_input(pid) -> dict:
    """Données attendues par services.passport_generator.generate_passport_pdf."""
    prof = land_profile(pid)
    worst = max(prof["cases"], key=lambda c: c["Cd_mg_kg"])
    zs = zones(pid)
    status = parcel(pid)["worst"]
    color_en = {"ROUGE": "RED", "ORANGE": "ORANGE", "VERT": "GREEN"}[status]
    plants = sorted({p for z in zs for p in z["traitement"]["plantes"]})
    months = max(z["months"] for z in zs)
    return {
        "zone_color": color_en,
        "plant_mix": ", ".join(plants),
        "safe_for_fodder": status != "ROUGE",
        "planting_cycles": math.ceil(months / 6),
        "lat": round(prof["origine"]["lat"], 5),
        "lon": round(prof["origine"]["lon"], 5),
        "input": {"ec": worst["CE_dS_m"], "ph": worst["pH"], "cd_mg_kg": worst["Cd_mg_kg"],
                  "pb_mg_kg": worst["Pb_mg_kg"]},
    }


# ───────────────────────────────── Chatbot ─────────────────────────────────

def chatbot_config() -> dict:
    return _read(DEMO / "chatbot.json")


def chatbot_reply(question: str) -> str:
    """Réponse simulée par mots-clés. À remplacer par services.rag + Gemini."""
    cfg = chatbot_config()
    q = question.lower()
    best, best_hits = None, 0
    for a in cfg["answers"]:
        hits = sum(1 for k in a["keywords"] if k in q)
        if hits > best_hits:
            best, best_hits = a, hits
    return best["reply"] if best else cfg["fallback"]
