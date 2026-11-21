import json
from datetime import date

from django.shortcuts import render
from django.urls import reverse

from core.strings import get_strings
from core.views import journey_context
from services import demo_data

from .geo import land_profile_to_geojson


def _session_readings(request, pid):
    return request.session.get(f"readings_{pid}", [])


def index(request, pid):
    ctx = journey_context(pid, "diagnostic")
    profile = demo_data.land_profile(pid)
    sensors = demo_data.sensors(pid, _session_readings(request, pid))
    sources = demo_data.pollution_sources()
    ctx.update({
        "profile": profile,
        "zones": demo_data.zones(pid),
        "sensors": sensors,
        "sources": sources,
        "map_data": {
            "geojson": land_profile_to_geojson(profile),
            "bounds": demo_data.parcel_bounds(profile),
            "sensors": sensors,
            "sources": sources,
            "center": ctx["parcel"]["center"],
            "caseUrl": reverse("diagnostics:case", args=[pid, 0, 0]).replace("/0/0/", "/{l}/{c}/"),
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
