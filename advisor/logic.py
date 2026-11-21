"""Bloc 2 : pont entre les calculs (advisor/services, sans Django) et l'interface.

`crop_recommendations_ui(pid)` renvoie exactement les champs attendus par
templates/advisor/crops.html et components/crop_card.html (contrat de services/demo_data),
plus une clé `bloc2` avec le détail du calcul (culture retenue, eau, lessivage...).
"""
import json
from pathlib import Path

from django.conf import settings

from .services.geo import geojson_plan
from .services.plan_image import dessiner_plan
from .services.recommandation import charger_plantes, recommander_cultures

CACHE_DIR = Path(getattr(settings, "REGEN_CACHE_DIR", Path(settings.BASE_DIR) / "cache"))
CROPS_META = Path(settings.BASE_DIR) / "fixtures" / "demo" / "crops.json"

# cle de advisor/data/plantes.json -> nom dans services/cultures.py (catalogue de l'interface)
NOM_CATALOGUE = {"palmier": "Palmier dattier", "grenadier": "Grenadier", "olivier": "Olivier",
                 "orge": "Orge", "luzerne": "Luzerne", "maraichage": "Tomate",
                 "atriplex_halimus": "Atriplex"}
# cultures absentes du catalogue : libelle anglais + icone Lucide
HORS_CATALOGUE = {"henne": ("Henna", "leaf"), "jojoba": ("Jojoba (cosmetic oil)", "sprout"),
                  "agrumes": ("Citrus", "citrus")}
# melanges de la regle de secours -> especes affichees
MELANGES = {"atriplex_hyper": ["Atriplex halimus", "Brassica juncea"],
            "moutarde_tournesol": ["Brassica juncea", "Helianthus annuus"],
            "atriplex_salsola": ["Atriplex halimus", "Salsola"]}
WATER_LEVEL = {"FAIBLE": 1, "MOYEN": 2, "ELEVE": 3}


def _meta():
    with open(CROPS_META, encoding="utf-8") as f:
        return json.load(f)


def recommandation(pid):
    """JSON complet de la recommandation (terre nue) pour une parcelle."""
    from services import demo_data   # import tardif : demo_data importe advisor.logic
    return recommander_cultures(demo_data.land_profile(pid), cache_dir=CACHE_DIR)


def _besoin_eau(kc):
    return "FAIBLE" if kc <= 0.7 else "MOYEN" if kc <= 0.9 else "ELEVE"


def _carte(cle, plantes, meta, ce_max, choisie):
    """Carte au format components/crop_card.html."""
    p = plantes[cle]
    nom_cat = NOM_CATALOGUE.get(cle)
    m = meta["crops"].get(nom_cat, {}) if nom_cat else {}
    en, icon = HORS_CATALOGUE.get(cle, (p["nom"], "sprout"))
    besoin = _besoin_eau(p["kc"])
    return {
        "nom": nom_cat or p["nom"], "en": m.get("en", en), "icon": m.get("icon", icon),
        "alimentaire": p["alimentaire"], "ce_seuil": p["seuil_ce"], "besoin_eau": besoin,
        "water_level": WATER_LEVEL[besoin], "salt_margin": round(p["seuil_ce"] - ce_max, 1),
        "salt_pct": min(100, round(p["seuil_ce"] / 20 * 100)),
        "income_tnd_ha": m.get("income_tnd_ha", "—"), "spacing_m": p["espacement_m"],
        "recommended": choisie, "cle": cle,
    }


def crop_recommendations_ui(pid):
    from services import demo_data
    reco = recommandation(pid)
    plantes = charger_plantes()
    meta = _meta()
    par_id = {z["id"]: z for z in reco["zones"]}
    out = []
    for z in demo_data.zones(pid):
        r = par_id.get(z["id"])
        if r is None:
            continue
        bloc2 = {k: r[k] for k in ("culture", "decide_par", "note", "besoin_litres_jour", "lr", "etc_mm_jour",
                                   "collecte_drainage", "nb_plants", "microbes", "alimentaire", "arrosages_par_jour")}
        if r["couleur"] in ("ROUGE", "ORANGE"):
            especes = MELANGES.get(r["cle"]) or [n.strip() for n in r["culture"].split(" + ")]
            remediation = [{"latin": n, **meta["remediation_plants"].get(n, {"en": n, "role": "", "icon": "leaf"})}
                           for n in especes]
            out.append({"zone": z, "remediation": remediation, "crops": [], "bloc2": bloc2})
        else:
            cles = [r["cle"]] + [a["cle"] for a in r["alternatives"]]
            crops = [_carte(c, plantes, meta, r["ce_max_dS_m"], i == 0) for i, c in enumerate(cles) if c in plantes]
            out.append({"zone": z, "remediation": [], "crops": crops, "bloc2": bloc2})
    try:
        geo = geojson_plan(reco)
    except Exception:          # la carte est un plus : jamais bloquante
        geo = None
    return {"zones": out, "climat": reco["climat"], "geo": geo, "ce_eau_dS_m": reco.get("ce_eau_dS_m"),
            "ce_eau_source": reco.get("ce_eau_source"), "besoin_total_litres_jour": reco["besoin_total_litres_jour"],
            "avertissements": reco["avertissements"]}


def _nom_en(cle, nom, meta):
    """Libelle anglais d'une plante de la base (memes noms que les cartes de la page)."""
    nom_cat = NOM_CATALOGUE.get(cle)
    if nom_cat and nom_cat in meta["crops"]:
        return meta["crops"][nom_cat]["en"]
    return HORS_CATALOGUE.get(cle, (nom, None))[0]


def _reco_en_anglais(reco):
    """Copie de la recommandation avec les noms de cultures en anglais (les noms latins restent)."""
    import copy
    meta = _meta()
    r = copy.deepcopy(reco)
    for z in r["zones"]:
        if z["couleur"] == "VERT":
            z["culture"] = _nom_en(z["cle"], z["culture"], meta)
            for a in z["alternatives"]:
                a["nom"] = _nom_en(a["cle"], a["nom"], meta)
        elif z["cle"] in MELANGES:
            z["culture"] = " + ".join(MELANGES[z["cle"]])
    return r


def plan_png(pid):
    """Dessine le plan dans media/advisor/plans/ (lu aussi par le passeport). Renvoie le chemin relatif."""
    rel = f"advisor/plans/plan_{pid}.png"
    chemin = Path(settings.MEDIA_ROOT) / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    dessiner_plan(_reco_en_anglais(recommandation(pid)), str(chemin))
    return rel
