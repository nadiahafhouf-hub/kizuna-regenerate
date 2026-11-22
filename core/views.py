import json

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from services import demo_data

from .strings import get_strings


def sans_diagnostic(request, pid):
    """Parcelle créée mais sol pas encore diagnostiqué : Crops, Irrigation et Passport ont besoin
    du LandProfile du bloc 1. On renvoie vers le plan des capteurs (comme la page Diagnostic)."""
    demo_data._record(pid)   # parcelle inconnue -> 404
    if demo_data.has_profile(pid):
        return None
    from django.contrib import messages
    messages.info(request, get_strings()["app"]["need_diagnostic"].format(pid=pid), extra_tags="diagnostic")
    return redirect("diagnostics:plan", pid)

STEP_URLS = {
    "diagnostic": "diagnostics:index",
    "crops": "advisor:index",
    "irrigation": "irrigation:index",
    "solar": "energy:index",
    "passport": "passport:index",
}


def journey_context(pid, step) -> dict:
    """Contexte commun aux 4 pages du parcours : parcelle, stepper, sélecteur de parcelle."""
    keys = list(STEP_URLS)
    current = keys.index(step)
    steps = []
    for i, s in enumerate(get_strings()["steps"]):
        steps.append({**s, "url": reverse(STEP_URLS[s["key"]], args=[pid]),
                      "state": "current" if i == current else "done" if i < current else "todo"})
    try:
        p = demo_data.parcel(pid)
    except Http404:
        # parcelle créée mais pas encore diagnostiquée (plan des capteurs / saisie des relevés)
        p = {**demo_data._record(pid), "worst": "VERT", "zones_count": 0, "cells_count": 0}
    return {
        "parcel": p,
        "all_parcels": demo_data.parcels(),
        "steps": steps,
        "step": step,
        "step_url_name": STEP_URLS[step],
        "next_step": steps[current + 1] if current + 1 < len(steps) else None,
    }


def home(request):
    ps = demo_data.parcels()
    map_data = {
        "parcels": [{"id": p["id"], "name": p["name"], "worst": p["worst"], "center": p["center"],
                     "bounds": p["bounds"], "url": reverse("diagnostics:index", args=[p["id"]])}
                    for p in ps],
        "sources": demo_data.pollution_sources(),
    }
    return render(request, "core/dashboard.html", {
        "parcels_list": ps,
        "kpis": demo_data.global_kpis(),
        "map_data": map_data,
        "demo_pid": demo_data.DEMO_PARCEL,
        "solar_alerts": _alertes_solaires(),
    })


def _alertes_solaires():
    """Alertes non lues du volet photovoltaïque (app energy), pour le tableau de bord."""
    try:
        from energy.models import Alerte
        return list(Alerte.objects.filter(lue=False)[:5])
    except Exception:
        return []


def load_demo(request):
    return redirect("diagnostics:index", demo_data.DEMO_PARCEL)


@require_POST
def chat(request):
    try:
        q = json.loads(request.body or b"{}").get("q", "")
    except ValueError:
        q = ""
    return JsonResponse({"reply": demo_data.chatbot_reply(str(q)[:500])})
