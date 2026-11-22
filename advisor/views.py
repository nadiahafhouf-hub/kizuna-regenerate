from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from core.views import journey_context, sans_diagnostic
from services import demo_data
from .logic import CULTURES_ARBRES, champ_parcelle, crop_recommendations_ui, plan_png, recommandation
from .services.etat_terre import etat_terre

MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png"}


def index(request, pid):
    if (r := sans_diagnostic(request, pid)):
        return r
    ctx = journey_context(pid, "crops")
    zones = demo_data.zones(pid)
    try:   # bloc 2 : vraies règles ; secours = version démo
        bloc2 = crop_recommendations_ui(pid)
        recs = bloc2["zones"]
    except Http404:
        raise
    except Exception:
        bloc2, recs = None, demo_data.crop_recommendations(pid)
    # Terre nue ou plantée ? Choix de l'agriculteur, sinon détecté par le diagnostic (Sentinel-2)
    try:
        detection = etat_terre(demo_data.land_profile(pid))
    except Exception:
        detection = {"etat": None}
    mode = ((request.GET.get("mode") if request.GET.get("mode") in ("bare", "planted") else None)
            or request.session.get(f"crops_mode_{pid}")
            or {"NUE": "bare", "PLANTEE": "planted"}.get(detection["etat"]) or "bare")
    ctx.update({
        "mode": mode,  # choix de l'agriculteur > diagnostic satellite > terre nue
        "detection": detection,
        "mode_choisi": bool(request.session.get(f"crops_mode_{pid}")),
        "recommendations": recs,
        "bloc2": bloc2,
        "zones": zones,
        "catalog": demo_data.crop_catalog(),
        "irrigation_types": demo_data.IRRIGATION_TYPES,
        "default_zone": zones[-1]["id"] if zones else "",
        "cultures_arbres": CULTURES_ARBRES,
    })
    return render(request, "advisor/crops.html", ctx)


@require_POST
def set_mode(request, pid):
    mode = request.POST.get("mode")
    if mode in ("bare", "planted"):
        request.session[f"crops_mode_{pid}"] = mode
    return JsonResponse({"mode": request.session.get(f"crops_mode_{pid}")})


@require_POST
def score(request, pid):
    """Terre plantée : photo (optionnelle) + formulaire → score d'optimalité (partiel HTMX).
    La photo n'est pas stockée : Gemini Vision sera branché ici (bloc 2)."""
    photo = request.FILES.get("photo")
    error = None
    if photo:
        if photo.content_type not in PHOTO_TYPES:
            error = "err_type"
        elif photo.size > MAX_PHOTO_BYTES:
            error = "err_size"
    try:
        spacing = float((request.POST.get("spacing") or "0").replace(",", "."))
    except ValueError:
        spacing = 0.0
    irrigation = request.POST.get("irrigation")
    if irrigation not in demo_data.IRRIGATION_TYPES:
        irrigation = "GOUTTE_A_GOUTTE"
    if error:
        return render(request, "advisor/_score_error.html", {"error": error})
    result = demo_data.score_planting(pid, request.POST.get("zone"), request.POST.get("crop"),
                                      max(spacing, 0.05), irrigation,
                                      photo.name if photo else None)
    return render(request, "advisor/_score_result.html", {"r": result})


def recommandation_json(request, pid):
    """Recommandation terre nue complète (JSON) : pour le passeport / chatbot du bloc 4."""
    demo_data.parcel(pid)  # 404 si parcelle inconnue
    return JsonResponse(recommandation(pid), json_dumps_params={"ensure_ascii": False})


def plan(request, pid):
    """Plan PNG (zones, plantes, goutte-à-goutte, une vanne par zone), aussi enregistré dans media/."""
    demo_data.parcel(pid)
    rel = plan_png(pid)
    return FileResponse(open(Path(settings.MEDIA_ROOT) / rel, "rb"), content_type="image/png")


@require_http_methods(["GET", "POST"])
def champ_json(request, pid):
    """Terre déjà plantée : arbres détectés, axe du champ et chemin d'irrigation (vue large du champ).
    GET : dernière analyse (calculée la première fois). POST : nouvelle analyse avec les réglages de la carte."""
    demo_data.parcel(pid)
    try:
        r = champ_parcelle(pid, request.POST.dict() if request.method == "POST" else None)
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=422)
    return JsonResponse(r, json_dumps_params={"ensure_ascii": False})
