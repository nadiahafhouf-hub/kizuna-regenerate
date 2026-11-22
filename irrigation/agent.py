"""Agent d'irrigation (bloc 3) : rassemble tout ce que l'on sait de chaque zone avant de planifier.

Sources, de la plus sûre à la moins sûre :
  1. réseau goutte-à-goutte calculé (DripNetworkPlan) : zone déclarée PLANTÉE dans Crops (« Already planted »),
     culture, irrigation actuelle, plantes détectées sur l'image, débit réel du réseau ;
  2. analyse du champ du bloc 2 (« Already planted », vue large) : culture et arbres détectés ;
  3. LandProfile (état des zones / Sentinel-2) ;
  4. recommandation « terre nue » du bloc 2 : culture conseillée et nombre de plants à planter.

Les DÉCISIONS (litres, heures, pompage) restent calculées par irrigation/services/planning.py ;
ce module ne fait que préparer les données de chaque zone.
"""
import copy
import json
import math
import unicodedata

# irrigation actuelle (formulaire Crops ou LandProfile) -> efficience de l'eau apportée
EFFICIENCE = {"goutte_a_goutte": 0.9, "aspersion": 0.75, "gravitaire": 0.6}
TYPES = {"GOUTTE_A_GOUTTE": "goutte_a_goutte", "ASPERSION": "aspersion", "GRAVITAIRE": "gravitaire",
         "AUCUNE": "aucun", "AUCUN": "aucun"}
NOMS_IRRIGATION = {"goutte_a_goutte": "goutte-à-goutte", "aspersion": "aspersion",
                   "gravitaire": "submersion / gravitaire", "aucun": "pluvial (pas d'irrigation)"}
COUVERTURE_NOUVELLE_PLANTATION = 0.5   # 1re année : plants jeunes, couvert réduit de moitié


def _sans_accent(t):
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")


def plante(nom, plantes):
    """Paramètres d'eau (kc, couverture, seuil_ce) d'une culture de la base du bloc 2 (nom FR, EN ou latin)."""
    from advisor.services.recommandation import trouver_plante
    if not nom:
        return None, None
    cle, p = trouver_plante(nom, plantes)
    if p:
        return cle, p
    n = _sans_accent(nom)
    for cle, p in plantes.items():   # « Olivier » -> olivier, « Palmier dattier » -> palmier, « Olive » -> olivier
        if cle in n or _sans_accent(p["nom"]).split(" ")[0] in n or n.split(" ")[0] in _sans_accent(p["nom"]):
            return cle, p
    return None, None


def type_irrigation(valeur):
    v = str(valeur or "").strip()
    return TYPES.get(v.upper(), v.lower() if v.lower() in EFFICIENCE or v.lower() == "aucun" else None)


def dernier_reseau(pid):
    from .models import DripNetworkPlan
    try:
        return DripNetworkPlan.objects.filter(parcelle_id=pid, statut=DripNetworkPlan.Statut.OK).first()
    except Exception:
        return None


def _champ(pid):
    """Dernière analyse « Already planted » du champ (bloc 2), si elle existe (pas de nouvel appel)."""
    from advisor.logic import _fichier_champ
    f = _fichier_champ(pid)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):
        return None


def _diametre_couronne(culture):
    from services.irrigation_engine.crops import culture_depuis_nom, get_crop
    cle, _ = culture_depuis_nom(culture or "")
    return float(get_crop(cle).get("diam_couronne_m", 3.0))


def zones_agent(pid, reco=None):
    """Une ligne par zone : état (NUE / PLANTEE), culture, nombre de plantes, source, kc, couverture,
    irrigation actuelle et réseau goutte-à-goutte s'il a été calculé."""
    from advisor.logic import recommandation
    from advisor.services.etat_terre import etat_terre
    from advisor.services.recommandation import charger_plantes
    from services import demo_data

    reco = reco or recommandation(pid)
    profile = demo_data.land_profile(pid)
    plantes = charger_plantes()
    net = dernier_reseau(pid)
    champ = _champ(pid)
    zones_net = {z.get("id"): z for z in ((net.land_profile or {}).get("zones", []) if net else [])}
    res_net = {}
    for rz in ((net.resultat or {}).get("zones", []) if net else []):
        res_net[str(rz.get("nom", "")).split(" ")[0]] = rz
    conseil_net = {str(c.get("zone", "")).split(" ")[0]: c for c in (net.conseil if net else [])}
    zones_lp = {z.get("id"): z for z in profile.get("zones", [])}
    etat_global = etat_terre(profile).get("etat")

    out = []
    for z in reco["zones"]:
        zid = z["id"]
        zn, zl, rn, cn = zones_net.get(zid, {}), zones_lp.get(zid, {}), res_net.get(zid), conseil_net.get(zid)
        etat = str(zn.get("etat") or zl.get("etat") or "").upper() or None
        if etat not in ("NUE", "PLANTEE"):
            if cn and (cn.get("n_plantes") or 0) > (cn.get("a_replanter") or 0):
                etat = "PLANTEE"           # plantes détectées sur l'image par le réseau
            else:
                etat = etat_global or "NUE"
        irr = type_irrigation((zn.get("irrigation_actuelle") or zl.get("irrigation_actuelle") or {}).get("type"))
        surface = float(z["surface_m2"])
        a = dict(id=zid, couleur=z["couleur"], surface_m2=surface, etat=etat,
                 culture_recommandee=z["culture"], kc=z["kc"], couverture=z["couverture"], seuil_ce=z["seuil_ce"])
        if etat == "PLANTEE":
            culture, source = None, None
            if zn.get("culture"):
                culture, source = zn["culture"], "Crops (déjà planté)"
            elif champ and champ.get("culture"):
                culture, source = champ["culture"], "analyse du champ (bloc 2)"
            cle, p = plante(culture, plantes) if culture else (None, None)
            if not p:   # culture inconnue : on garde celle de la recommandation
                culture, source = culture or z["culture"], source or "recommandation (culture non précisée)"
            else:
                a.update(kc=p["kc"], couverture=p["couverture"], seuil_ce=min(z["seuil_ce"], p["seuil_ce"]))
            nb = None
            if cn:
                nb = int((cn.get("n_plantes") or 0) - (cn.get("a_replanter") or 0)) or None
                source = (source or "réseau") + " + plantes vues sur l'image (réseau)"
            if nb:   # couverture réelle du sol par les couronnes
                d = _diametre_couronne(culture)
                a["couverture"] = round(min(1.0, max(0.05, nb * math.pi * (d / 2) ** 2 / surface)), 2)
            a.update(culture=culture, nb_plantes=nb, source=source,
                     note="plantes déjà en place : arrosage de chaque plante existante")
            irr = irr or "gravitaire"      # sans information : irrigation traditionnelle supposée
        else:
            a.update(culture=z["culture"], nb_plantes=z.get("nb_plants"), source="recommandation terre nue (Crops)",
                     couverture=round(z["couverture"] * COUVERTURE_NOUVELLE_PLANTATION, 2),
                     note="nouvelle plantation : jeunes plants la 1re année (couvert réduit de moitié)")
            irr = irr or "aucun"
        a["irrigation_actuelle"] = irr
        a["irrigation_actuelle_nom"] = NOMS_IRRIGATION.get(irr, irr)
        a["efficience_actuelle"] = EFFICIENCE.get(irr)
        if rn:   # réseau goutte-à-goutte conçu pour cette zone
            c = rn.get("conception") or {}
            a["reseau"] = {k: c.get(k) for k in ("debit_zone_l_h", "n_goutteurs", "goutteurs_par_plante",
                                                  "debit_goutteur_l_h", "lignes_par_rang", "mode")}
            a["debit_reseau_l_h"] = c.get("debit_zone_l_h")
        out.append(a)
    return out


def reco_agent(pid):
    """Recommandation du bloc 2 corrigée par l'agent : la planification arrose ce qui est VRAIMENT planté."""
    from advisor.logic import recommandation
    reco = copy.deepcopy(recommandation(pid))
    za = {a["id"]: a for a in zones_agent(pid, reco)}
    for z in reco["zones"]:
        a = za.get(z["id"])
        if a:
            z.update({k: a.get(k) for k in ("culture", "kc", "couverture", "seuil_ce", "etat", "nb_plantes",
                                            "source", "irrigation_actuelle", "efficience_actuelle",
                                            "debit_reseau_l_h", "note")})
    reco["agent_zones"] = list(za.values())
    return reco
