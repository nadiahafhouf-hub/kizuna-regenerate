import datetime

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.strings import get_strings
from core.views import journey_context
from services import demo_data
from .logic import (creer_plan, etat, evenements_pour_passeport, plan_actif, plan_complet, plan_db_vers_dict,
                    regenerer, simuler_jour_suivant)
from .models import IrrigationPlan

S = IrrigationPlan.Statut


def index(request, pid):
    ctx = journey_context(pid, "irrigation")
    try:
        plan_db = plan_actif(pid)
    except Http404:
        raise
    except Exception:            # la page ne plante jamais : planning de demo sans boutons
        plan_db = None
    plan = demo_data.irrigation_plan(pid)
    sysc = plan["system"]
    ctx.update({
        "plan": plan,
        "plan_db": plan_db,
        "etat": etat(plan_db) if plan_db else None,
        "modifiable": plan_db is not None and plan_db.statut in (S.BROUILLON, S.VALIDE),
        "evenements": plan_db.programme.all() if plan_db else [],
        "zones_plan": plan_db.planning.get("zones", []) if plan_db else [],
        "dates": [d["date"] for d in plan["days"]],
        "reservoir_hint": get_strings()["irrigation"]["reservoir_hint"].format(pump=sysc["pump_kw"], kwp=sysc["solar_kwp"]),
        "live_config": {
            "etatUrl": reverse("irrigation:etat", args=[pid]),
            "simUrl": reverse("irrigation:simuler", args=[pid]),
            "statut": plan_db.statut if plan_db else None,
            "days": [{"hourly": d["hourly"], "label": f"{d['weekday']} {d['day']} {d['month']}"} for d in plan["days"]],
        },
    })
    return render(request, "irrigation/irrigation.html", ctx)


@require_POST
def action(request, pid, nom):
    """Valider -> Passer en automatique -> Reprendre la main (MANUEL) -> Repasser en automatique."""
    plan_db = plan_actif(pid)
    transitions = {
        "valider": ((S.BROUILLON,), S.VALIDE),
        "automatique": ((S.VALIDE, S.MANUEL), S.AUTO),
        "manuel": ((S.AUTO,), S.MANUEL),
    }
    if nom == "nouveau":
        creer_plan(pid)
    elif nom in transitions and plan_db.statut in transitions[nom][0]:
        plan_db.statut = transitions[nom][1]
        if nom == "valider":
            plan_db.valide_le = datetime.datetime.now(datetime.timezone.utc)
        plan_db.save(update_fields=["statut", "valide_le"])
    return redirect("irrigation:index", pid=pid)


@require_POST
def modifier(request, pid):
    """Modifier le volume d'une zone pour un jour : tout le planning est recalcule (repasse en brouillon)."""
    plan_db = plan_actif(pid)
    if plan_db.statut in (S.BROUILLON, S.VALIDE):
        zone, date = request.POST.get("zone_id", ""), request.POST.get("date", "")
        try:
            volume = max(0, int(float(request.POST.get("volume_l", ""))))
            datetime.date.fromisoformat(date)
        except ValueError:
            return redirect("irrigation:index", pid=pid)
        if zone in [z["id"] for z in plan_db.planning.get("zones", [])]:
            plan_db.volumes_forces[f"{zone}|{date}"] = volume
            regenerer(plan_db)
    return redirect(reverse("irrigation:index", args=[pid]) + "#events")


@require_POST
def simuler(request, pid):
    """« Simuler la journee suivante » : horloge simulee + 1 jour, puis l'automate traite les evenements."""
    plan_db = plan_actif(pid)
    if plan_db.statut not in (S.AUTO, S.MANUEL):
        return JsonResponse({"ok": False, "message": "validate"}, status=400)
    traites = simuler_jour_suivant(plan_db)
    return JsonResponse({"ok": True, "traites": traites, "etat": etat(plan_db)})


def etat_json(request, pid):
    return JsonResponse(etat(plan_actif(pid)))


@require_POST
def approve(request, pid):
    """Ancienne adresse : valide le planning et passe directement en automatique."""
    plan_db = plan_actif(pid)
    if plan_db.statut in (S.BROUILLON, S.VALIDE, S.MANUEL):
        plan_db.statut = S.AUTO
        plan_db.save(update_fields=["statut"])
    return JsonResponse({"mode": "AUTO"})


@require_POST
def reset(request, pid):
    """Ancienne adresse : nouveau planning (a valider)."""
    creer_plan(pid)
    return JsonResponse({"mode": "PENDING"})


def plan_json(request, pid):
    """Planning complet (evenements avec raisons, reservoir heure par heure, totaux) en JSON."""
    plan_db = plan_actif(pid)
    return JsonResponse(plan_db_vers_dict(plan_db), json_dumps_params={"ensure_ascii": False})


def passeport_json(request, pid):
    """Sortie pour le passeport (bloc 4) : evenements FAIT / ANNULE deja passes."""
    demo_data.parcel(pid)
    return JsonResponse({"parcelle_id": pid, "evenements": evenements_pour_passeport(pid)},
                        json_dumps_params={"ensure_ascii": False})
