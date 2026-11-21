import datetime
import json
import time
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from core.strings import get_strings
from core.views import journey_context
from services import demo_data
from .logic import (creer_plan, etat, evenements_pour_passeport, plan_actif, plan_complet, plan_db_vers_dict,
                    regenerer, simuler_jour_suivant)
from services.irrigation_engine import satellite as sat_engine

from . import network
from .models import DripNetworkPlan, IrrigationPlan

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


def _profil(request, pid, plan=None):
    """LandProfile de la parcelle, avec l'origine GPS corrigée sur la carte dynamique si elle est envoyée
    (sinon celle du dernier calcul, sinon celle du diagnostic). Les cases et les zones ne changent pas."""
    profile = dict(demo_data.land_profile(pid))
    if plan is not None and plan.land_profile.get("origine"):
        profile["origine"] = dict(plan.land_profile["origine"])
    try:
        lat, lon = float(request.POST["origin_lat"]), float(request.POST["origin_lon"])
        if -85 < lat < 85 and -180 <= lon <= 180:
            profile["origine"] = {**profile.get("origine", {}), "lat": round(lat, 7), "lon": round(lon, 7),
                                  "point": "coin_nord_ouest"}
    except (KeyError, ValueError):
        pass
    return profile


def network_page(request, pid):
    """Réseau goutte-à-goutte optimal : image satellite automatique (ou photo), tracé, conseils, carte."""
    ctx = journey_context(pid, "irrigation")
    dernier = DripNetworkPlan.objects.filter(parcelle_id=pid).first()
    profile = _profil(request, pid, dernier)
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
    plan = dernier
    o = profile.get("origine") or {}
    res = (plan.resultat or {}) if plan else {}
    ctx.update({
        "net": plan,
        "res": res,
        "ia": (res.get("photo") or {}).get("detection_ia"),
        "ia_active": network.config_ia() is not None,
        "google": bool(settings.GOOGLE_MAPS_BROWSER_KEY),
        "fournisseur": network.config_satellite()["fournisseur"],
        "origin": o,
        "legende_source": sat_engine.legende_source(plan.source_image) if plan else "",
        "net_config": {
            "previewUrl": reverse("irrigation:network_preview", args=[pid]),
            "geojsonUrl": reverse("irrigation:network_geojson", args=[pid]) if plan and plan.geojson else None,
            "tiles": sat_engine.FOURNISSEURS["esri"]["url"],
            "attribution": sat_engine.FOURNISSEURS["esri"]["attribution"],
            "zoom": (plan.source_image or {}).get("zoom", 18) if plan else 18,
            # carte dynamique : parcelle déplaçable (Google Maps si clé navigateur, sinon Leaflet + Esri)
            "googleKey": settings.GOOGLE_MAPS_BROWSER_KEY or None,
            "parcel": {"lat": o.get("lat"), "lon": o.get("lon"),
                       "largeur": profile.get("largeur_m"), "longueur": profile.get("longueur_m")},
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
    profile = _profil(request, pid, DripNetworkPlan.objects.filter(parcelle_id=pid).first())
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


# Valeurs du formulaire « Already planted » (bloc 2) → type d'irrigation du moteur
IRRIGATION_CROPS = {"GOUTTE_A_GOUTTE": "goutte_a_goutte", "ASPERSION": "aspersion",
                    "GRAVITAIRE": "gravitaire", "AUCUNE": "aucun"}


@require_http_methods(["GET", "POST"])
def network_card(request, pid):
    """Carte « réseau goutte-à-goutte » insérée dans la page Crops, mode « Already planted » (HTMX).
    GET : dernier réseau calculé. POST : calcule le réseau à partir de l'image satellite, en reprenant
    la zone, la culture et l'irrigation actuelle saisies dans le formulaire du bloc 2."""
    S = get_strings()["network"]
    dernier = DripNetworkPlan.objects.filter(parcelle_id=pid).first()
    erreur = None
    if request.method == "POST":
        profile = _profil(request, pid, dernier)
        zone_id, crop = request.POST.get("zone"), request.POST.get("crop")
        irr = IRRIGATION_CROPS.get(request.POST.get("irrigation"), "aucun")
        zones = []
        for z in profile.get("zones", []):
            z = dict(z)
            if z.get("id") == zone_id:  # zone déclarée plantée par l'agriculteur
                z.update(etat="PLANTEE", irrigation_actuelle={"type": irr})
                if crop:
                    z["culture"] = crop
            zones.append(z)
        profile["zones"] = zones
        try:
            sat_engine.coins_lonlat(profile)
            dernier = network.creer_reseau(pid, profile, {"mode": "satellite"})
        except sat_engine.SatelliteErreur as e:
            erreur = str(e)
        except Exception as e:
            erreur = f"{S['err_analysis']} {e}"
            dernier = DripNetworkPlan.objects.filter(parcelle_id=pid).first()
    return render(request, "irrigation/_network_card.html", {
        "parcel": {"id": pid}, "net": dernier, "erreur": erreur,
        "ia": ((dernier.resultat or {}).get("photo") or {}).get("detection_ia") if dernier else None,
        "legende_source": sat_engine.legende_source(dernier.source_image) if dernier else ""})


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
