import json
import time
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from core.strings import get_strings
from core.views import journey_context
from services import demo_data
from services.irrigation_engine import satellite as sat_engine

from . import network
from .models import DripNetworkPlan


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


# ---------------------------------------------------------------- réseau goutte-à-goutte (satellite / photo)
def _points(raw, n=None):
    pts = json.loads(raw or "[]")
    if not isinstance(pts, list) or not all(isinstance(p, list) and len(p) == 2 for p in pts):
        raise ValueError("points")
    if n is not None and len(pts) != n:
        raise ValueError("points")
    return [[float(a), float(b)] for a, b in pts]


def _calage_depuis_post(post, photo):
    """Formulaire de la page réseau → calage du moteur."""
    S = get_strings()["network"]
    if post.get("source_image", "satellite") == "satellite":
        cal = {"mode": "satellite"}
        if post.get("satellite_zoom"):  # clics faits sur l'aperçu : même zoom, donc mêmes pixels
            cal["zoom"] = int(post["satellite_zoom"])
        else:
            return cal
    else:
        if not photo:
            raise ValueError(S["err_photo"])
        try:
            cal = {"mode": "coins", "coins_px": _points(post.get("coins_px"), 4)}
        except ValueError:
            raise ValueError(S["err_corners"])
    try:
        src = _points(post.get("source_px"))
        plantes = _points(post.get("plantes_px"))
    except ValueError:
        raise ValueError(S["err_points"])
    if src:
        cal["source_px"] = src[0]
    if plantes:
        cal["plantes_px"] = plantes
    return cal


def network_page(request, pid):
    """Réseau goutte-à-goutte optimal : image satellite automatique (ou photo), tracé, conseils, carte."""
    ctx = journey_context(pid, "irrigation")
    profile = demo_data.land_profile(pid)
    if request.method == "POST":
        photo = request.FILES.get("photo") if request.POST.get("source_image") == "photo" else None
        try:
            cal = _calage_depuis_post(request.POST, photo)
            if cal["mode"] == "satellite":
                sat_engine.coins_lonlat(profile)  # origine GPS valide ?
            network.creer_reseau(pid, profile, cal, photo)
        except (ValueError, sat_engine.SatelliteErreur) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"{get_strings()['network']['err_analysis']} {e}")
        return redirect("irrigation:network", pid=pid)
    plan = DripNetworkPlan.objects.filter(parcelle_id=pid).first()
    ctx.update({
        "net": plan,
        "res": (plan.resultat or {}) if plan else {},
        "legende_source": sat_engine.legende_source(plan.source_image) if plan else "",
        "map_tiles": sat_engine.FOURNISSEURS["esri"]["url"],
        "map_attribution": sat_engine.FOURNISSEURS["esri"]["attribution"],
        "net_config": {
            "previewUrl": reverse("irrigation:network_preview", args=[pid]),
            "geojsonUrl": reverse("irrigation:network_geojson", args=[pid]) if plan and plan.geojson else None,
            "tiles": sat_engine.FOURNISSEURS["esri"]["url"],
            "attribution": sat_engine.FOURNISSEURS["esri"]["attribution"],
            "zoom": (plan.source_image or {}).get("zoom", 18) if plan else 18,
        },
    })
    return render(request, "irrigation/network.html", ctx)


@require_POST
def network_recompute(request, pid):
    plan = DripNetworkPlan.objects.filter(parcelle_id=pid).first()
    if plan:
        try:
            network.calculer(plan)
        except Exception as e:
            messages.error(request, f"{get_strings()['network']['err_analysis']} {e}")
    return redirect("irrigation:network", pid=pid)


@require_http_methods(["GET", "POST"])
def network_preview(request, pid):
    """AJAX : télécharge l'image satellite de l'emprise et renvoie l'aperçu (contour + grille des cases)."""
    profile = demo_data.land_profile(pid)
    dossier = Path(settings.MEDIA_ROOT) / "irrigation" / "network" / "previews" / pid
    if dossier.exists():  # un seul aperçu par parcelle
        for f in dossier.glob("*.png"):
            f.unlink(missing_ok=True)
    stamp = int(time.time())
    try:
        sat = sat_engine.image_satellite(profile, dossier, nom=f"satellite_{stamp}.png", **network.config_satellite())
        k = sat_engine.apercu(sat, profile, dossier / f"preview_{stamp}.png")
    except sat_engine.SatelliteErreur as e:
        return JsonResponse({"error": str(e)}, status=422)
    except Exception as e:
        return JsonResponse({"error": f"{type(e).__name__}: {e}"}, status=422)
    return JsonResponse({
        "image": default_storage.url(f"irrigation/network/previews/{pid}/preview_{stamp}.png"),
        "scale": k, "corners": [[x * k, y * k] for x, y in sat["coins_px"]],
        "coins_px": sat["coins_px"], "zoom": sat["zoom"], "resolution_m_px": sat["resolution_m_px"],
        "legend": sat_engine.legende_source(sat_engine.source_image(sat)),
        "warnings": sat["avertissements"]})


def network_geojson(request, pid):
    plan = get_object_or_404(DripNetworkPlan.objects.filter(parcelle_id=pid)[:1])
    return JsonResponse(plan.geojson or {})


def network_api(request, pid):
    """Résumé JSON du dernier réseau (pour les autres blocs : passeport, advisor)."""
    plan = get_object_or_404(DripNetworkPlan.objects.filter(parcelle_id=pid)[:1])
    r = plan.resultat or {}
    return JsonResponse({
        "id": plan.pk, "parcelle_id": pid, "statut": plan.statut, "message": plan.message,
        "bilan": r.get("bilan"), "conseil": r.get("conseil_simple"), "recommandations": r.get("recommandations"),
        "photo": r.get("photo"), "pompage": r.get("pompage"),
        "images": {k: getattr(plan, k).url for k in ("image_trace", "image_photo_analysee", "image_plan", "rapport")
                   if getattr(plan, k)}})
