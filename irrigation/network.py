"""Bloc 3 : lien entre Django et le moteur de réseau goutte-à-goutte (services/irrigation_engine).

Le moteur lit directement le LandProfile du contrat (origine au coin nord-ouest, cases, zones,
traitement) : aucune conversion n'est nécessaire. Aucune logique agronomique ici.
"""

import json
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction

from services.irrigation_engine.parcelle import analyser_parcelle

from .models import DripNetworkPlan


def config_satellite():
    """Paramètres du téléchargement des images satellite (settings.SATELLITE_*)."""
    return {
        "fournisseur": getattr(settings, "SATELLITE_FOURNISSEUR", "esri"),
        "url": getattr(settings, "SATELLITE_TILE_URL", None),
        "zoom": getattr(settings, "SATELLITE_ZOOM", 19),
        "attribution": getattr(settings, "SATELLITE_ATTRIBUTION", None),
        "cache": str(Path(settings.MEDIA_ROOT) / "tiles_cache"),
    }


def _json_sur(o):
    """Supprime les objets non sérialisables (numpy, conception)."""
    return json.loads(json.dumps({k: v for k, v in o.items() if not k.startswith("_")}, default=float))


def creer_reseau(parcelle_id, land_profile, calage, photo=None):
    """Crée et calcule un DripNetworkPlan. photo : UploadedFile, chemin, ou None (satellite)."""
    plan = DripNetworkPlan.objects.create(parcelle_id=parcelle_id, land_profile=land_profile,
                                          calage=calage or {})
    if photo is not None:
        if isinstance(photo, (str, Path)):
            with open(photo, "rb") as f:
                plan.photo.save(Path(photo).name, File(f), save=True)
        else:
            plan.photo.save(photo.name, photo, save=True)
    return calculer(plan)


def calculer(plan):
    tmp = Path(tempfile.mkdtemp(prefix="reseau_"))
    try:
        res = analyser_parcelle(plan.land_profile, plan.photo.path if plan.photo else None,
                                plan.calage or None, tmp, options={"satellite": config_satellite()})
        sat = res.pop("satellite", None)
        geo = res.pop("geojson")
        b = res["bilan"]
        pid = plan.parcelle_id
        with transaction.atomic():
            if sat and not plan.photo:  # image satellite téléchargée : gardée comme photo du plan
                with open(sat["image"], "rb") as f:
                    plan.photo.save(f"{pid}_satellite.png", File(f), save=False)
                garde = {k: v for k, v in (plan.calage or {}).items() if k in ("source_px", "plantes_px")}
                plan.calage = {"mode": "satellite", "coins_px": sat["coins_px"], "zoom": sat["zoom"],
                               "source_image": sat["source_image"], **garde}
            plan.resultat = _json_sur(res)
            plan.geojson = geo
            plan.conso_actuelle_m3_an = float(b["actuel_m3_an"])
            plan.conso_optimale_m3_an = float(b["optimal_m3_an"])
            plan.economie_pct = float(b["economie_pct"])
            plan.heures_pompage_pointe = float(b["heures_pompage_pointe"])
            for champ, fichier in (("image_photo_analysee", "1_photo_analysee.png"),
                                   ("image_plan", "2_plan_optimal.png"),
                                   ("rapport", "rapport.html"),
                                   ("image_trace", "4_trace_sur_photo.png")):
                if (tmp / fichier).exists():
                    with open(tmp / fichier, "rb") as f:
                        getattr(plan, champ).save(f"{pid}_{plan.pk}_{fichier}", File(f), save=False)
            plan.statut = DripNetworkPlan.Statut.OK
            plan.message = "\n".join(res.get("avertissements", []))
            plan.save()
    except Exception as exc:  # le plan garde la trace de l'erreur
        plan.statut = DripNetworkPlan.Statut.ERREUR
        plan.message = f"{type(exc).__name__}: {exc}"
        plan.save()
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return plan
