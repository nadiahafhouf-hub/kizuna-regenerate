import json

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from services import demo_data

from .strings import get_strings

STEP_URLS = {
    "diagnostic": "diagnostics:index",
    "crops": "advisor:index",
    "irrigation": "irrigation:index",
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
    return {
        "parcel": demo_data.parcel(pid),
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
    })


def load_demo(request):
    return redirect("diagnostics:index", demo_data.DEMO_PARCEL)


@require_POST
def chat(request):
    try:
        q = json.loads(request.body or b"{}").get("q", "")
    except ValueError:
        q = ""
    return JsonResponse({"reply": demo_data.chatbot_reply(str(q)[:500])})
