from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.strings import get_strings
from core.views import journey_context
from services import demo_data


def _approved(request, parcel):
    return request.session.get(f"irrigation_approved_{parcel['id']}", parcel["irrigation_status"] == "AUTO")


def index(request, pid):
    ctx = journey_context(pid, "irrigation")
    plan = demo_data.irrigation_plan(pid)
    approved = _approved(request, ctx["parcel"])
    sysc = plan["system"]
    ctx.update({
        "plan": plan,
        "approved": approved,
        "reservoir_start_m3": round(sysc["reservoir_m3"] * sysc["reservoir_start_pct"] / 100, 1),
        "reservoir_hint": get_strings()["irrigation"]["reservoir_hint"].format(
            pump=sysc["pump_kw"], kwp=sysc["solar_kwp"]),
        # Données passées au JS (planning, courbes horaires, paramètres de la simulation)
        "sim_config": {
            "approved": approved,
            "approveUrl": reverse("irrigation:approve", args=[pid]),
            "system": sysc,
            "days": [{k: d[k] for k in ("index", "weekday", "day", "month", "slots", "pump",
                                        "hourly", "irrigation_m3", "flood_m3", "skipped")}
                     for d in plan["days"]],
        },
    })
    return render(request, "irrigation/irrigation.html", ctx)


@require_POST
def approve(request, pid):
    """L'agriculteur valide le planning → mode automatique (stocké en session pour la démo)."""
    demo_data.parcel(pid)  # 404 si parcelle inconnue
    request.session[f"irrigation_approved_{pid}"] = True
    return JsonResponse({"mode": "AUTO"})


@require_POST
def reset(request, pid):
    """Remet la démo à zéro (plan à valider)."""
    request.session[f"irrigation_approved_{pid}"] = False
    return JsonResponse({"mode": "PENDING"})
