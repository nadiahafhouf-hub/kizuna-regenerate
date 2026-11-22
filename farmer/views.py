"""Vue « Farmer » : interface simple pour l'agriculteur.

Aucune logique nouvelle : chaque page appelle les MÊMES fonctions que la vue Expert & Jury
(services.demo_data, irrigation.logic, advisor.logic, energy.services.projet, passeport) et poste vers
les MÊMES actions (irrigation:action, irrigation:simuler, energy:clean). On ne fait ici que choisir
les chiffres à montrer et les traduire en phrases courtes.
"""
import base64
import datetime

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from core.strings import get_strings
from services import demo_data

PAGES = ["water", "soil", "plants", "sun", "certificate"]
EXPERT = {"home": "core:home", "water": "irrigation:index", "soil": "diagnostics:index",
          "plants": "advisor:index", "sun": "energy:index", "certificate": "passport:index"}
ICONS = {"home": "house", "water": "droplets", "soil": "map", "plants": "sprout", "sun": "sun",
         "certificate": "badge-check"}


def _F():
    return get_strings()["farmer"]


def _jour(d):
    """date ISO ou date -> « Thu 25 Nov »."""
    if isinstance(d, str):
        d = datetime.date.fromisoformat(d[:10])
    return d.strftime("%a %d %b").replace(" 0", " ")


ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


def _tuile(center, z=17):
    """Vue du ciel de la parcelle (une tuile Esri World Imagery, sans clé) + position du centre dans la tuile,
    pour les cartes « photo » de la vue Farmer. None si la parcelle n'a pas encore de position."""
    import math
    try:
        lat, lon = float(center[0]), float(center[1])
    except (TypeError, ValueError, IndexError):
        return None
    n = 2 ** z
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return {"url": ESRI.format(z=z, x=int(fx), y=int(fy)),
            "pos": f"{round((fx % 1) * 100)}% {round((fy % 1) * 100)}%"}


def _centre(pid):
    try:
        return demo_data.parcel(pid).get("center")
    except Exception:
        return None


def _meteo(pid, plan_ui=None):
    """Météo du jour déjà chargée par le planning d'irrigation (Open-Meteo) : aucun appel en plus."""
    try:
        if plan_ui is None:
            from irrigation.logic import plan_actif
            if plan_actif(pid, creer=False) is None:   # on ne crée pas de planning juste pour la météo
                return None
            plan_ui = demo_data.irrigation_plan(pid)
        d = (plan_ui.get("days") or [None])[0]
        if not d:
            return None
        return {"tmax": d.get("tmax"), "tmin": d.get("tmin"), "condition": d.get("condition"),
                "icon": d.get("icon") or "sun", "rain": d.get("rain"), "et0": d.get("et0"),
                "date": f"{d.get('weekday', '')} {d.get('day', '')} {d.get('month', '')}".strip()}
    except Exception:
        return None


def _ctx(page, pid=None, **extra):
    """Contexte commun : onglets, parcelle, lien vers la page experte équivalente."""
    F = _F()
    tabs = [{"key": "home", "label": F["tabs"]["home"], "icon": ICONS["home"], "url": reverse("farmer:home")}]
    if pid:
        tabs = [{"key": k, "label": F["tabs"][k], "icon": ICONS[k], "url": reverse(f"farmer:{k}", args=[pid])}
                for k in PAGES] + tabs
    parcel = None
    if pid:
        try:
            parcel = demo_data.parcel(pid)
        except Http404:
            parcel = {**demo_data._record(pid), "worst": None}
    return {"page": page, "tabs": tabs, "parcel": parcel, "pid": pid,
            "tile": _tuile(_centre(pid)) if pid else None,
            "page_url_name": f"farmer:{page}" if page != "home" else "farmer:water",
            "all_parcels": demo_data._parcel_records(with_profile_only=False),
            "expert_url": reverse(EXPERT[page], args=[pid]) if pid and page != "home" else reverse("core:home"),
            "F": F, **extra}


def _sans_profil(pid):
    demo_data._record(pid)          # parcelle inconnue -> 404
    return None if demo_data.has_profile(pid) else redirect("farmer:soil", pid)


# ───────────────────────────── d. My farm ─────────────────────────────
def home(request):
    from energy.models import Alerte
    from irrigation.logic import plan_actif
    F = _F()["home"]
    cards = []
    for r in demo_data._parcel_records(with_profile_only=False):
        pid = r["id"]
        c = {"id": pid, "name": r.get("name", pid), "worst": None, "area_ha": r.get("area_ha"),
             "tile": _tuile(_centre(pid)), "healthy_pct": None}
        if not demo_data.has_profile(pid):
            c.update(state=F["no_diag"], todo=F["todo"]["diagnose"], url=reverse("farmer:soil", args=[pid]),
                     icon="scan-search")
        else:
            p = demo_data.parcel(pid)
            c.update(worst=p["worst"], area_ha=p.get("area_ha"), state=F["state"][p["worst"]],
                     healthy_pct=p.get("healthy_pct"), zones_count=p.get("zones_count"),
                     todo=F["todo"]["ok"], url=reverse("farmer:water", args=[pid]), icon="circle-check")
            try:
                plan_db = plan_actif(pid, creer=False)
            except Exception:
                plan_db = None
            if plan_db is not None and plan_db.statut == "BROUILLON":
                c.update(todo=F["todo"]["approve"], icon="droplets")
            elif Alerte.objects.filter(parcelle_id=pid, lue=False, type__in=["NETTOYER", "PREVOIR"]).exists():
                c.update(todo=F["todo"]["clean"], url=reverse("farmer:sun", args=[pid]), icon="sun")
        cards.append(c)
    avec = [c for c in cards if c["worst"]]
    hero = next((c for c in avec if c["tile"]), None)
    meteo = next((m for m in (_meteo(c["id"]) for c in avec[:3]) if m), None)
    chips = [k for k in ("ROUGE", "ORANGE", "VERT") if any(c["worst"] == k for c in cards)]
    if any(c["worst"] is None for c in cards):
        chips.append("none")
    return render(request, "farmer/home.html", _ctx("home", cards=cards, chips=chips, meteo=meteo,
                  hero_tile=_tuile(_centre(hero["id"]), z=16) if hero else None,
                  hero_name=hero["name"] if hero else None))


# ───────────────────────────── a. Water ─────────────────────────────
def _arrosages(plan_db, jour, plan_ui):
    """Arrosages PREVUS (ou faits) d'un jour : litres, première heure, zones, minutes (planning bloc 3)."""
    evs = [e for e in plan_db.programme.all() if e.type == "ARROSAGE" and e.date == jour and e.statut != "ANNULE"]
    if not evs:
        return None
    minutes = 0
    for d in plan_ui.get("days", []):
        if str(d.get("date")) == jour.isoformat():
            minutes = sum(s.get("minutes", 0) for s in d.get("slots", []))
    evs.sort(key=lambda e: (e.heure, e.ordre))
    zones = sorted({e.zone_id for e in evs})
    return {"litres": sum(e.volume_l for e in evs), "heure": evs[0].heure.strftime("%H:%M"),
            "zones": zones, "minutes": minutes, "fait": all(e.statut == "FAIT" for e in evs)}


def water(request, pid):
    if (r := _sans_profil(pid)):
        return r
    from irrigation.logic import etat, plan_actif
    F = _F()["water"]
    try:
        plan_db = plan_actif(pid)
        st = etat(plan_db)
    except Http404:
        raise
    except Exception:
        return render(request, "farmer/water.html", _ctx("water", pid, erreur=True))
    plan_ui = demo_data.irrigation_plan(pid)
    jours = plan_db.planning.get("jours", [])
    from django.utils import timezone
    aujourdhui = timezone.localtime(plan_db.horloge).date() if plan_db.horloge else plan_db.date_debut
    demain = aujourdhui + datetime.timedelta(days=1)
    seuil = plan_db.planning.get("parametres", {}).get("seuil_pluie_mm", 5)
    pluie = next((j for j in jours if j["date"] >= aujourdhui.isoformat() and j.get("pluie_mm", 0) >= seuil), None)
    maxi = max([j.get("arrose_l", 0) for j in jours] or [1]) or 1
    semaine = [{"label": _jour(j["date"])[:3], "litres": round(j.get("arrose_l", 0)),
                "pct": max(4, round(100 * j.get("arrose_l", 0) / maxi)), "pluie": j.get("pluie_mm", 0) >= seuil,
                "today": j["date"] == aujourdhui.isoformat()} for j in jours]
    statut = plan_db.statut
    action = {"BROUILLON": ("valider", F["btn"]["valider"], "check"),
              "VALIDE": ("automatique", F["btn"]["automatique"], "play"),
              "AUTO": ("manuel", F["btn"]["manuel"], "hand"),
              "MANUEL": ("automatique", F["btn"]["restart"], "rotate-ccw")}.get(statut)
    if st["semaine_finie"]:
        action = ("nouveau", F["btn"]["nouveau"], "calendar-plus")
    ctx = _ctx("water", pid,
               statut=statut, statut_label=F["status"].get(statut, statut), aide=F["help"].get(statut, ""),
               today=_arrosages(plan_db, aujourdhui, plan_ui), tomorrow=_arrosages(plan_db, demain, plan_ui),
               tank=st["reservoir"], economie=st["economie"],
               pluie=_jour(pluie["date"]) if pluie else None, semaine=semaine,
               horloge=st["horloge"], semaine_finie=st["semaine_finie"], meteo=_meteo(pid, plan_ui),
               action=action, action_url=reverse("irrigation:action", args=[pid, action[0]]) if action else None,
               sim_url=reverse("irrigation:simuler", args=[pid]) if statut != "BROUILLON" else None,
               here=request.path)
    return render(request, "farmer/water.html", ctx)


# ───────────────────────────── b. Soil ─────────────────────────────
def _nom_plante(rec):
    if rec is None:
        return None
    if rec.get("remediation"):
        return rec["remediation"][0]["en"]
    crops = [c for c in rec.get("crops", []) if c.get("recommended")] or rec.get("crops", [])
    return crops[0]["en"] if crops else None


def _recs(pid):
    try:
        from advisor.logic import crop_recommendations_ui
        return {z["zone"]["id"]: z for z in crop_recommendations_ui(pid)["zones"]}
    except Exception:
        return {}


def soil(request, pid):
    demo_data._record(pid)
    if not demo_data.has_profile(pid):
        return render(request, "farmer/soil.html", _ctx("soil", pid, vide=True,
                      plan_url=reverse("diagnostics:plan", args=[pid])))
    from diagnostics.geo import land_profile_to_geojson
    profile = demo_data.land_profile(pid)
    recs = _recs(pid)
    zones = []
    for z in demo_data.zones(pid):
        rec = recs.get(z["id"])
        zones.append({**z, "plante": _nom_plante(rec),
                      "mois": (z.get("traitement") or {}).get("mois_avant_sain")})
    ordre = {"ROUGE": 0, "ORANGE": 1, "VERT": 2}
    zones.sort(key=lambda z: ordre.get(z["couleur"], 3))
    p = demo_data.parcel(pid)
    date = profile.get("date_mesure") or p.get("last_reading")
    try:
        from advisor.services.etat_terre import etat_terre
        couvert = etat_terre(profile).get("couvert_pct")
    except Exception:
        couvert = None
    stats = {"area_ha": p.get("area_ha"), "zones": p.get("zones_count"), "healthy": round(p.get("healthy_pct") or 0),
             "salt": round((p.get("shares") or {}).get("ORANGE", 0)), "polluted": round((p.get("shares") or {}).get("ROUGE", 0)),
             "cover": couvert}
    return render(request, "farmer/soil.html", _ctx(
        "soil", pid, zones=zones, date=_jour(date) if date else "", stats=stats,
        map_data={"geojson": land_profile_to_geojson(profile), "bounds": demo_data.parcel_bounds(profile)},
        plan_url=reverse("diagnostics:plan", args=[pid]), readings_url=reverse("diagnostics:readings", args=[pid])))


# ───────────────────────────── c. Plants ─────────────────────────────
def plants(request, pid):
    if (r := _sans_profil(pid)):
        return r
    from advisor.services.etat_terre import etat_terre
    from irrigation.models import DripNetworkPlan
    profile = demo_data.land_profile(pid)
    try:
        det = etat_terre(profile)
    except Exception:
        det = {"etat": None}
    ndvis = [o["valeurs"]["ndvi"] for z in profile.get("zones", []) for o in z.get("observations", [])
             if (o.get("valeurs") or {}).get("ndvi") is not None]
    ndvi = sum(ndvis) / len(ndvis) if ndvis else None
    sante = None if ndvi is None else "good" if ndvi >= 0.4 else "weak" if ndvi >= 0.2 else "bare"
    # Vision (bloc 3) : dernier réseau calculé ; sans clé Gemini / sans photo -> rien, sans erreur
    vision = None
    net = DripNetworkPlan.objects.filter(parcelle_id=pid).first()
    if net and net.conseil:
        conseil = net.conseil if isinstance(net.conseil, list) else []
        n = sum((c.get("n_plantes") or 0) for c in conseil)
        a = sum((c.get("a_replanter") or 0) for c in conseil)
        ia = ((net.resultat or {}).get("photo") or {}).get("detection_ia") or {}
        if n or a:
            vision = {"n": n, "replant": a, "culture": ia.get("culture_probable")}
    recs = _recs(pid)
    quoi = []
    for z in demo_data.zones(pid):
        rec = recs.get(z["id"])
        nom = _nom_plante(rec)
        if nom:
            quoi.append({"zone": z["id"], "couleur": z["couleur"], "plante": nom,
                         "role": (rec.get("remediation") or [{}])[0].get("role") if rec.get("remediation") else None,
                         "icon": ((rec.get("remediation") or rec.get("crops") or [{}])[0]).get("icon", "sprout")})
    return render(request, "farmer/plants.html", _ctx(
        "plants", pid, det=det, sante=sante, vision=vision, quoi=quoi,
        det_date=_jour(det["date"]) if det.get("date") else None,
        network_url=reverse("irrigation:network", args=[pid])))


# ───────────────────────────── e. Sun ─────────────────────────────
def sun(request, pid):
    if (r := _sans_profil(pid)):
        return r
    from energy.models import Alerte, ConfigSolaire
    from energy.services.projet import analyse
    F = _F()["sun"]
    cfg, _ = ConfigSolaire.objects.get_or_create(parcelle_id=pid)
    a = analyse(pid, cfg)
    etat = a["etat"]
    hero, sous, urgent = F["clean_none"], None, False
    if etat:
        r = etat["recommandation"]
        if (etat.get("cause") or {}).get("cause") == "PANNE":
            hero, urgent = F["pump_fault"], True
        elif r["action"] == "NETTOYER":
            hero, urgent = F["clean_today"], True
        elif r["action"] == "NETTOYER_APRES_TEMPETE" and r.get("tempete"):
            hero, sous = F["clean_on"].format(d=_jour(r["tempete"]["date"])), F["dust"].format(d=_jour(r["tempete"]["date"]))
        elif r["action"] == "ATTENDRE_PLUIE" and r.get("pluie"):
            hero = F["rain"].format(d=_jour(r["pluie"]["date"]))
        elif r.get("date_conseillee"):
            hero = F["clean_on"].format(d=_jour(r["date_conseillee"]))
        if not sous and r.get("tempete"):
            sous = F["dust"].format(d=_jour(r["tempete"]["date"]))
    alertes = Alerte.objects.filter(parcelle_id=pid, lue=False).count()
    mens = a["dim"].get("mensuel") or []
    maxi = max([m["production_kwh_jour"] for m in mens] or [1]) or 1
    mois = [{"mois": m["mois"], "pct": max(4, round(100 * m["production_kwh_jour"] / maxi)),
             "dim": m["mois"] == a["dim"].get("mois_dimensionnant")} for m in mens]
    return render(request, "farmer/sun.html", _ctx(
        "sun", pid, dim=a["dim"], mois=mois, hero=hero,
        panels_text=F["panels"].format(n=a["dim"]["nb_panneaux"]).replace("panels", "panel" if a["dim"]["nb_panneaux"] == 1 else "panels"), sous=sous, urgent=urgent, alertes=alertes,
        cleaned=request.GET.get("cleaned") == "1", here=request.path,
        clean_url=reverse("energy:clean", args=[pid])))


# ───────────────────────────── f. Certificate ─────────────────────────────
def certificate(request, pid):
    if (r := _sans_profil(pid)):
        return r
    from services.passport_generator import generate_qr_for_url
    pp = demo_data.passport(pid)
    verify_url = request.build_absolute_uri(reverse("verify", args=[pp["id"]]))
    qr = base64.b64encode(generate_qr_for_url(verify_url)).decode("ascii")
    first = pp["events"][0]["date"] if pp["events"] else pp["issued"]
    return render(request, "farmer/certificate.html", _ctx(
        "certificate", pid, pp=pp, qr=f"data:image/png;base64,{qr}", verify_url=verify_url,
        events_text=_F()["certificate"]["events"].format(n=len(pp["events"]), d=_jour(first)),
        pdf_url=reverse("passport:pdf", args=[pid])))
