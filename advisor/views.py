from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.views import journey_context
from services import demo_data

MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png"}


def index(request, pid):
    ctx = journey_context(pid, "crops")
    zones = demo_data.zones(pid)
    ctx.update({
        "mode": request.session.get(f"crops_mode_{pid}"),  # None → pop-up « nue ou plantée ? »
        "recommendations": demo_data.crop_recommendations(pid),
        "zones": zones,
        "catalog": demo_data.crop_catalog(),
        "irrigation_types": demo_data.IRRIGATION_TYPES,
        "default_zone": zones[-1]["id"] if zones else "",
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
