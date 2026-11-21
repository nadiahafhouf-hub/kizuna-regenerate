import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Parcel
from core.strings import get_strings
from core.views import journey_context
from services import demo_data

from .geo import land_profile_to_geojson
from .models import LandProfile, SensorReading
from .pipeline import construire_land_profile
from .sampling import centre_case, distance_km, plan_capteurs
from .satellite import SatelliteIndisponible
from .satellite_fusion import appliquer_satellite

EXPERIENCE = Path(settings.BASE_DIR) / "fixtures" / "bloc1" / "experience_capteurs.json"
METRIQUES_CD = Path(settings.BASE_DIR) / "fixtures" / "bloc1" / "modele_cd_metriques.json"
TEXTURES = ["sableux", "sablo-limoneux", "limoneux", "argilo-limoneux", "argileux"]
TEXTURE_USDA = {"sableux": "loamy sand", "sablo-limoneux": "sandy loam", "limoneux": "loam",
                "argilo-limoneux": "clay loam", "argileux": "clay"}


def _session_readings(request, pid):
    return request.session.get(f"readings_{pid}", [])


# ───────────────────────── Page Diagnostic (résultat) ─────────────────────────

def index(request, pid):
    if not demo_data.has_profile(pid):
        return redirect("diagnostics:plan", pid)
    ctx = journey_context(pid, "diagnostic")
    profile = demo_data.land_profile(pid)
    sensors = demo_data.sensors(pid, _session_readings(request, pid))
    sources = demo_data.pollution_sources()
    ctx.update({
        "profile": profile,
        "zones": demo_data.zones(pid),
        "sensors": sensors,
        "sources": sources,
        "interp": profile.get("interpolation"),
        "triage": profile.get("tri_labo"),
        "sat": profile.get("satellite"),
        "fusion": profile.get("fusion_ce"),
        "controles": profile.get("points_controle") or [],
        "needs_sat": demo_data.is_db_parcel(pid) and not profile.get("satellite"),
        "is_db": demo_data.is_db_parcel(pid),
        "map_data": {
            "geojson": land_profile_to_geojson(profile),
            "bounds": demo_data.parcel_bounds(profile),
            "sensors": sensors,
            "sources": sources,
            "center": ctx["parcel"]["center"],
            "caseUrl": reverse("diagnostics:case", args=[pid, 0, 0]).replace("/0/0/", "/{l}/{c}/"),
            "hasConfidence": any("confiance" in c for c in profile["cases"]),
            "hasSatellite": bool(profile.get("satellite")),
            "controles": profile.get("points_controle") or [],
        },
    })
    return render(request, "diagnostics/diagnostic.html", ctx)


def case(request, pid, ligne, col):
    """Panneau latéral (HTMX) : valeurs d'une case comparées aux seuils."""
    return render(request, "diagnostics/_case_panel.html", {"c": demo_data.case_detail(pid, ligne, col)})


def sensors_list(request, pid):
    """Liste des capteurs (rafraîchie en HTMX après un nouveau relevé)."""
    return render(request, "diagnostics/_sensor_list.html", {
        "sensors": demo_data.sensors(pid, _session_readings(request, pid)),
    })


FIELDS = {"CE_dS_m": (0, 40), "pH": (3, 11), "Cd_mg_kg": (0, 100), "Pb_mg_kg": (0, 2000)}
# (clé, unité, pas, exemple) pour le formulaire
FORM_FIELDS = [("CE_dS_m", "dS/m", "0.1", "9.5"), ("pH", "", "0.1", "7.8"),
               ("Cd_mg_kg", "mg/kg", "0.1", "4.2"), ("Pb_mg_kg", "mg/kg", "1", "120")]


def new_reading(request, pid):
    """Modale « New sensor reading ». GET : formulaire ; POST : validation, couleur via
    couleur_case(), stockage en session (démo, pas de base)."""
    profile = demo_data.land_profile(pid)
    cells = [(c["ligne"], c["col"], c["couleur"]) for c in profile["cases"]]
    ctx = {
        "pid": pid,
        "cells": [{"value": f"{l}-{c}", "ligne": l, "col": c, "couleur": k} for l, c, k in cells],
        "fields": FORM_FIELDS,
        "today": date.today().isoformat(), "values": {}, "errors": {},
    }
    if request.method != "POST":
        return render(request, "diagnostics/_sensor_form.html", ctx)

    data, errors = {}, {}
    for key, (lo, hi) in FIELDS.items():
        raw = (request.POST.get(key) or "").replace(",", ".").strip()
        try:
            v = float(raw)
            if not lo <= v <= hi:
                raise ValueError
            data[key] = v
        except ValueError:
            errors[key] = f"{lo} – {hi}"
    try:
        ligne, col = (int(x) for x in request.POST.get("cell", "").split("-"))
        if (ligne, col) not in {(l, c) for l, c, _ in cells}:
            raise ValueError
    except ValueError:
        errors["cell"] = "?"
        ligne = col = 0
    when = request.POST.get("date") or ctx["today"]

    if errors:
        ctx.update({"values": request.POST, "errors": errors})
        return render(request, "diagnostics/_sensor_form.html", ctx)

    reading = demo_data.make_reading(ligne, col, data["CE_dS_m"], data["pH"], data["Cd_mg_kg"],
                                     data["Pb_mg_kg"], when)
    readings = _session_readings(request, pid) + [reading]
    request.session[f"readings_{pid}"] = readings
    sensor = demo_data.sensors(pid, readings)[-1]
    T = get_strings()
    resp = render(request, "diagnostics/_sensor_success.html", {"pid": pid, "r": sensor})
    resp["HX-Trigger"] = json.dumps({
        "toast": {"message": T["diagnostic"]["form"]["success"], "kind": "success"},
        "reading-added": sensor,
    })
    return resp


# ───────────────────────── Parcours agriculteur : parcelle → plan → relevés ─────────────────────────

def _geometrie(pid):
    """Dimensions + origine (coin nord-ouest) d'une parcelle, en base ou de démo."""
    obj = Parcel.objects.filter(parcelle_id=pid).first()
    if obj and demo_data.is_db_parcel(pid):
        return {"largeur": obj.largeur_m, "longueur": obj.longueur_m, "lat": obj.origine_lat,
                "lon": obj.origine_lon, "taille": obj.taille_case_m, "texture": obj.texture_sol,
                "region": obj.region}
    p = demo_data.land_profile(pid)
    return {"largeur": p["largeur_m"], "longueur": p["longueur_m"], "lat": p["origine"]["lat"],
            "lon": p["origine"]["lon"], "taille": p["taille_case_m"], "texture": p["texture_sol"],
            "region": p["region"]}


def _plan(pid):
    g = _geometrie(pid)
    return g, plan_capteurs(g["largeur"], g["longueur"], g["lat"], g["lon"], g["taille"],
                            demo_data.pollution_sources())


def _experience_pour(nb_cases):
    if not EXPERIENCE.exists():
        return None
    data = json.loads(EXPERIENCE.read_text(encoding="utf-8"))
    return min(data["tailles"], key=lambda t: abs(t["nb_cases"] - nb_cases))


def _prochain_id():
    n = Parcel.objects.filter(parcelle_id__startswith="KZ-").count() + 1
    while Parcel.objects.filter(parcelle_id=f"KZ-{n:03d}").exists():
        n += 1
    return f"KZ-{n:03d}"


def new_parcel(request):
    """L'agriculteur donne la taille de sa terre et clique son coin nord-ouest sur la carte."""
    T = get_strings()
    values, error = {"largeur": 30, "longueur": 30, "region": "Gabes"}, None
    if request.method == "POST":
        values = request.POST
        try:
            largeur, longueur = int(float(values["largeur"])), int(float(values["longueur"]))
            lat, lon = float(values["lat"]), float(values["lon"])
            if not (10 <= largeur <= 500 and 10 <= longueur <= 500 and -90 < lat < 90 and -180 < lon < 180):
                raise ValueError
        except (KeyError, ValueError):
            error = T["newparcel"]["invalid"]
        else:
            p = Parcel.objects.create(
                parcelle_id=_prochain_id(), nom=values.get("nom", "")[:120],
                agriculteur=values.get("agriculteur", "")[:120], region=values.get("region", "")[:80] or "Gabes",
                origine_lat=lat, origine_lon=lon, largeur_m=largeur, longueur_m=longueur, taille_case_m=10,
                texture_sol=values.get("texture") if values.get("texture") in TEXTURES else "")
            return redirect("diagnostics:plan", p.parcelle_id)
    return render(request, "diagnostics/new_parcel.html", {
        "values": values, "error": error, "textures": TEXTURES,
        "sources": demo_data.pollution_sources(), "all_parcels": demo_data.parcels(),
    })


def plan(request, pid):
    ctx = journey_context(pid, "diagnostic")
    g, p = _plan(pid)
    ctx.update({
        "geo": g, "plan": p, "is_db": demo_data.is_db_parcel(pid),
        "size_hint": f"{g['largeur']} × {g['longueur']} m · 10 m",
        "has_profile": demo_data.has_profile(pid),
        "experience": _experience_pour(p["nb_cases"]),
        "plan_data": {"plan": p, "origin": [g["lat"], g["lon"]], "taille": g["taille"],
                      "sources": demo_data.pollution_sources()},
    })
    return render(request, "diagnostics/plan.html", ctx)


def simulate(request, pid):
    """Démo : relevés réalistes pour chaque point du plan (générateur diagnostics.synthetic)."""
    import numpy as np

    from .synthetic import generer_parcelle, mesurer
    g, p = _plan(pid)
    c_lat, c_lon = centre_case(g["lat"], g["lon"], (p["nb_lignes"] - 1) / 2, (p["nb_colonnes"] - 1) / 2, g["taille"])
    src = min(demo_data.pollution_sources(), key=lambda s: distance_km(c_lat, c_lon, s["lat"], s["lon"]))
    from .sampling import cap_vers
    d = distance_km(c_lat, c_lon, src["lat"], src["lon"])
    rng = np.random.default_rng()
    verite = generer_parcelle(p["nb_lignes"], p["nb_colonnes"], g["taille"], distance_km=d,
                              cap=cap_vers(src["lat"], src["lon"], c_lat, c_lon), seed=int(rng.integers(1e9)))
    mes = mesurer(verite, [(q["ligne"], q["col"]) for q in p["points"]], rng)
    # XRF : Cu et Zn corrélés au Cd (ordre de grandeur des sols agricoles)
    for m in mes:
        m["Cu_mg_kg"] = round(float(18 + 6 * m["Cd_mg_kg"] * rng.uniform(0.7, 1.3)), 1)
        m["Zn_mg_kg"] = round(float(55 + 25 * m["Cd_mg_kg"] * rng.uniform(0.7, 1.3)), 1)
    return JsonResponse({"distance_km": round(d, 2), "source": src["name"], "texture": verite["texture"],
                         "readings": {q["id"]: m for q, m in zip(p["points"], mes)}})


def _tri_labo(point_id, valeurs, texture):
    """Tri IA (diagnostics.ml_cd) si l'XRF a fourni Cu et Zn."""
    if valeurs.get("Cu_mg_kg") is None or valeurs.get("Zn_mg_kg") is None:
        return None
    from .ml_cd import predire_risque_cd
    r = predire_risque_cd({"Pb_mg_kg": valeurs["Pb_mg_kg"], "Zn_mg_kg": valeurs["Zn_mg_kg"],
                           "Cu_mg_kg": valeurs["Cu_mg_kg"], "pH": valeurs["pH"],
                           "texture": TEXTURE_USDA.get(texture, "sandy loam"), "occupation": "Cropland"})
    if r is None:
        return None
    return {"point": point_id, "cd_mesure_xrf": valeurs["Cd_mg_kg"], **r}


def readings(request, pid):
    """Saisie des relevés point par point → pipeline du bloc 1 → LandProfile en base."""
    if not demo_data.is_db_parcel(pid):
        return redirect("diagnostics:plan", pid)
    T = get_strings()
    ctx = journey_context(pid, "diagnostic")
    g, p = _plan(pid)
    ctx.update({"geo": g, "plan": p, "today": date.today().isoformat(), "errors": {}, "values": {},
                "fields": FORM_FIELDS + [("Cu_mg_kg", "mg/kg", "0.1", "30"), ("Zn_mg_kg", "mg/kg", "1", "90")],
                "textures": TEXTURES})
    if request.method != "POST":
        return render(request, "diagnostics/readings.html", ctx)

    mesures, errors, tri, texture = [], {}, [], request.POST.get("texture") or g["texture"]
    for q in p["points"]:
        v = {}
        for key, (lo, hi) in {**FIELDS, "Cu_mg_kg": (0, 5000), "Zn_mg_kg": (0, 10000)}.items():
            raw = (request.POST.get(f"{q['id']}_{key}") or "").replace(",", ".").strip()
            if not raw and key in ("Cu_mg_kg", "Zn_mg_kg"):
                v[key] = None
                continue
            try:
                v[key] = float(raw)
                if not lo <= v[key] <= hi:
                    raise ValueError
            except ValueError:
                errors[f"{q['id']}_{key}"] = True
        if not any(k.startswith(q["id"] + "_") for k in errors):
            mesures.append({"id": q["id"], "ligne": q["ligne"], "col": q["col"], "lat": q["lat"], "lon": q["lon"], **v})
    if errors:
        ctx.update({"errors": errors, "values": request.POST, "error_msg": T["readings"]["invalid"]})
        return render(request, "diagnostics/readings.html", ctx)

    when = request.POST.get("date") or ctx["today"]
    parcelle = Parcel.objects.get(parcelle_id=pid)
    if texture in TEXTURES and texture != parcelle.texture_sol:
        parcelle.texture_sol = texture
        parcelle.save(update_fields=["texture_sol"])
    lp = construire_land_profile(pid, g["largeur"], g["longueur"], g["lat"], g["lon"], mesures, when,
                                 region=g["region"], texture_sol=texture, taille_m=g["taille"])
    tri = [t for t in (_tri_labo(m["id"], m, texture) for m in mesures) if t]
    lp["tri_labo"] = tri or None
    # même parcelle, même géométrie : on réutilise la dernière image satellite (pas de nouvel appel réseau)
    precedent = LandProfile.objects.filter(parcel=parcelle).order_by("-created_at").first()
    if precedent and (precedent.data.get("satellite") or {}).get("cases"):
        sat = precedent.data["satellite"]
        if len(sat["cases"]) == len(lp["cases"]):
            lp = appliquer_satellite(lp, sat, fusion=True)
    LandProfile.objects.create(parcel=parcelle, date_mesure=when, data=lp)
    SensorReading.objects.bulk_create([
        SensorReading(parcel=parcelle, date_mesure=when, ligne=m["ligne"], col=m["col"], lat=m["lat"],
                      lon=m["lon"], ce_ds_m=m["CE_dS_m"], ph=m["pH"], cd_mg_kg=m["Cd_mg_kg"], pb_mg_kg=m["Pb_mg_kg"])
        for m in mesures])
    request.session.pop(f"readings_{pid}", None)
    return redirect("diagnostics:index", pid)


# ───────────────────────── Couche satellite (Sentinel-2) ─────────────────────────

def analyser_parcelle(pid):
    """Lit Sentinel-2 pour la parcelle ; met à jour le dernier LandProfile si la parcelle est en base.
    Renvoie le dict satellite (lève SatelliteIndisponible)."""
    from .satellite import analyser
    g = _geometrie(pid)
    sat = analyser(g["lat"], g["lon"], g["largeur"], g["longueur"], g["taille"])
    if demo_data.is_db_parcel(pid):
        lp = LandProfile.objects.filter(parcel__parcelle_id=pid).order_by("-created_at").first()
        if lp:
            lp.data = appliquer_satellite(lp.data, sat, fusion=True)
            lp.save(update_fields=["data"])
    return sat


@require_POST
def satellite(request, pid):
    """HTMX : analyse l'image Sentinel-2 la plus récente, puis recharge la page."""
    try:
        analyser_parcelle(pid)
    except SatelliteIndisponible as e:
        return render(request, "diagnostics/_satellite_error.html", {"error": str(e), "pid": pid})
    resp = JsonResponse({"ok": True})
    resp["HX-Refresh"] = "true"
    return resp
