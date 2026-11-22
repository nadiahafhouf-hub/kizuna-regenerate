"""Assemble le volet solaire d'une parcelle : plantes (bloc 2) → dimensionnement → surveillance (IA 1-2-3)."""
from django.http import Http404

from services import demo_data

from . import climat as climat_mod
from .dimensionnement import couverture_installation, dimensionner
from .surveillance import creer_alertes, evaluer

# Valeurs par défaut si le bloc 2 ne fournit pas une culture (Atriplex, cf. bloc 2)
DEFAUT_PLANTE = {"kc": 0.65, "couverture": 0.6, "espacement_m": 1.0, "lr": 0.1}


def zones_plantes(pid, config=None):
    """Zones avec culture, coefficients et nombre de plantes (bloc 2), surchargé par l'agriculteur."""
    try:
        from advisor.logic import recommandation
        reco = recommandation(pid)
        zones = [{k: z.get(k) for k in ("id", "couleur", "culture", "nb_plants", "kc", "couverture", "espacement_m",
                                        "lr", "surface_m2")} for z in reco["zones"]]
    except Http404:
        raise
    except Exception:
        zones = [{"id": z["id"], "couleur": z["couleur"], "culture": "Atriplex halimus", "surface_m2": z["surface_m2"],
                  "nb_plants": z["surface_m2"], **DEFAUT_PLANTE} for z in demo_data.zones(pid)]
    surcharges = (config.plantes if config else {}) or {}
    for z in zones:
        z["nb_plants_bloc2"] = z["nb_plants"]
        if str(z["id"]) in surcharges:
            z["nb_plants"] = max(0, int(surcharges[str(z["id"])]))
        for k, v in DEFAUT_PLANTE.items():
            if z.get(k) is None:
                z[k] = v
    return zones


def analyse(pid, config, reseau=True, surveiller=True):
    profil = demo_data.land_profile(pid)
    lat0, lon0 = profil["origine"]["lat"], profil["origine"]["lon"]
    from diagnostics.sampling import centre_case
    nl = -(-profil["longueur_m"] // profil["taille_case_m"])
    nc = -(-profil["largeur_m"] // profil["taille_case_m"])
    lat, lon = centre_case(lat0, lon0, (nl - 1) / 2, (nc - 1) / 2, profil["taille_case_m"])
    clim = climat_mod.climat(lat, lon, reseau=reseau)
    zones = zones_plantes(pid, config)
    dim = dimensionner(zones, clim, profondeur_m=config.profondeur_m, panneau_wc=config.panneau_wc)
    # installation actuelle réglée dans le bloc 3 (paramètres d'irrigation)
    actuelle = None
    try:
        from irrigation.models import IrrigationSettings
        s = IrrigationSettings.charger()
        actuelle = couverture_installation(dim, s.puissance_crete_kwc, s.puissance_pompe_kw)
    except Exception:
        pass
    etat, nouvelles = None, []
    if surveiller:
        previsions = climat_mod.previsions(lat, lon) if reseau else None
        etat = evaluer(pid, lat, lon, dim["kwc"], demo_data.pollution_sources(), hauteur_m=dim["hauteur_totale_m"],
                       previsions=previsions, reseau=reseau)
        nouvelles = creer_alertes(pid, etat)
    return {"lat": lat, "lon": lon, "climat": clim, "dim": dim, "actuelle": actuelle, "etat": etat,
            "nouvelles_alertes": nouvelles}
