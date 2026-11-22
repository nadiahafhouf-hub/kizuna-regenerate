"""Surveillance d'une installation : production attendue (IA 1) vs mesurée → cause (IA 2) → date (IA 3) → alertes.

Mesures : celles de l'ESP32 si elles existent (energy.MesurePV), sinon une SIMULATION construite sur la
VRAIE météo du lieu (Open-Meteo : rayonnement dans le plan des panneaux, température, pluie, poussière des
45 derniers jours) + un encrassement simulé :
    vitesse = 0,25 %/jour + 0,6 %/jour × e^(−distance à la source de poussière / 5 km), × (1 + poussière/200)
    pluie ≥ 5 mm → 70 % de la saleté partie ; nettoyage → 100 %.
La simulation est déterministe par parcelle (même résultat à chaque affichage) et l'écran le signale.
"""
import json
import math
import zlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from django.conf import settings
from django.utils import timezone

from . import ia_cause, ia_prevision
from .ia_production import attendu_w_par_kwc, hauteur_soleil

CACHE = Path(settings.BASE_DIR) / "fixtures" / "energy" / "meteo"
JOURS = 45
NETTOYAGE_SUPPOSE_JOURS = 16


def meteo_recente(pid, lat, lon, inclinaison=33, reseau=True):
    """45 jours horaires de vraie météo (cache du jour ; repli sur le dernier cache)."""
    f = CACHE / f"{pid}.json"
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("jour") == date.today().isoformat() or not reseau:
            return d
    if not reseau:
        return None
    try:
        m = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "past_days": JOURS, "forecast_days": 1, "timezone": "auto",
            "hourly": "global_tilted_irradiance,temperature_2m,precipitation", "tilt": inclinaison, "azimuth": 0},
            timeout=30).json()
        a = requests.get("https://air-quality-api.open-meteo.com/v1/air-quality", params={
            "latitude": lat, "longitude": lon, "past_days": JOURS, "forecast_days": 1, "timezone": "auto",
            "hourly": "dust"}, timeout=30).json()
        d = {"jour": date.today().isoformat(), "utc_offset_s": m.get("utc_offset_seconds", 3600),
             "heures": m["hourly"]["time"], "poa": m["hourly"]["global_tilted_irradiance"],
             "t_air": m["hourly"]["temperature_2m"], "pluie": m["hourly"]["precipitation"],
             "poussiere": dict(zip(a["hourly"]["time"], a["hourly"]["dust"]))}
    except Exception:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d), encoding="utf-8")
    return d


def _vitesse_site(lat, lon, sources):
    from diagnostics.sampling import distance_km
    d = min((distance_km(lat, lon, s["lat"], s["lon"]) for s in sources), default=50)
    return 0.0025 + 0.006 * math.exp(-d / 5), d


def serie_journaliere(pid, lat, lon, kwc, meteo, nettoyages, sources, mesures_esp32=None):
    """DataFrame journalier : attendu_kwh, mesure_kwh, ip, pluie_mm, poussiere_max, perte_vraie (simulation)."""
    idx = pd.to_datetime(meteo["heures"])
    poa = np.array([x or 0 for x in meteo["poa"]], dtype=float)
    t = np.array([x if x is not None else 20 for x in meteo["t_air"]], dtype=float)
    h = hauteur_soleil(idx, lat, lon, meteo["utc_offset_s"] / 3600)
    att_w = attendu_w_par_kwc(poa, t, h) * kwc
    df = pd.DataFrame({"att_w": att_w, "pluie": [x or 0 for x in meteo["pluie"]],
                       "poussiere": [meteo["poussiere"].get(x) or 0 for x in meteo["heures"]]}, index=idx)
    j = df.resample("1D").agg({"att_w": "sum", "pluie": "sum", "poussiere": "max"})
    j = j[j.index.date < date.today()]   # journées complètes seulement
    j["attendu_kwh"] = j.att_w / 1000

    if mesures_esp32:   # vraies mesures de l'installation
        m = pd.Series({pd.Timestamp(k): v for k, v in mesures_esp32.items()}).resample("1D").sum() / 1000
        j["mesure_kwh"] = m.reindex(j.index)
        j["perte_vraie"] = np.nan
        j["source"] = "esp32"
    else:               # simulation déterministe sur la vraie météo
        rng = np.random.default_rng(zlib.crc32(pid.encode()))
        v0, _ = _vitesse_site(lat, lon, sources)
        jours_nettoyes = {n for n in nettoyages}
        perte, pertes = 0.02, []
        for d, r in j.iterrows():
            if d.date() in jours_nettoyes:
                perte = 0.0
            perte += v0 * (1 + r.poussiere / 200)
            if r.pluie >= ia_prevision.PLUIE_NETTOIE_MM:
                perte *= 1 - ia_prevision.PLUIE_EFFICACITE
            pertes.append(min(perte, 0.6))
        j["perte_vraie"] = pertes
        j["mesure_kwh"] = j.attendu_kwh * (1 - j.perte_vraie) * (1 + rng.normal(0, 0.02, len(j)))
        j["source"] = "simulation"
    j["ip"] = j.mesure_kwh / j.attendu_kwh
    return j[j.attendu_kwh > 0.5 * kwc].drop(columns=["att_w"])


def evaluer(pid, lat, lon, kwc, sources, hauteur_m=55.0, previsions=None, reseau=True):
    """État complet de l'installation pour la page Solar et les alertes."""
    from energy.models import MesurePV, Nettoyage
    meteo = meteo_recente(pid, lat, lon, reseau=reseau)
    if meteo is None:
        return None
    nettoyages = list(Nettoyage.objects.filter(parcelle_id=pid).values_list("date", flat=True))
    suppose = not nettoyages and not MesurePV.objects.filter(parcelle_id=pid).exists()
    if suppose:   # démo : aucun nettoyage enregistré → on suppose le dernier il y a 16 jours (affiché comme tel)
        nettoyages = [date.today() - timedelta(days=NETTOYAGE_SUPPOSE_JOURS)]
    esp = {m.horodatage.isoformat(): m.puissance_w for m in MesurePV.objects.filter(
        parcelle_id=pid, horodatage__gte=timezone.now() - timedelta(days=JOURS))}
    j = serie_journaliere(pid, lat, lon, kwc, meteo, nettoyages, sources, esp or None)
    if j.empty:
        return None
    dernier = max([n for n in nettoyages if n >= j.index[0].date()], default=None)
    depuis = j[j.index.date >= dernier] if dernier else j
    ip = depuis.ip.dropna().values
    cause = ia_cause.diagnostiquer(ip) if len(ip) >= 10 else None
    reco = ia_prevision.recommander(ip, previsions, energie_attendue_kwh_jour=float(j.attendu_kwh.tail(7).mean()),
                                    hauteur_m=hauteur_m)
    _, dist = _vitesse_site(lat, lon, sources)
    return {
        "source": j.source.iloc[-1], "dernier_nettoyage": dernier.isoformat() if dernier else None,
        "nettoyage_suppose": suppose,
        "jours": [{"date": d.date().isoformat(), "attendu_kwh": round(r.attendu_kwh, 2),
                   "mesure_kwh": round(float(r.mesure_kwh), 2) if pd.notna(r.mesure_kwh) else None,
                   "ip": round(float(r.ip), 3) if pd.notna(r.ip) else None, "pluie_mm": round(r.pluie, 1),
                   "poussiere_max": round(r.poussiere)} for d, r in j.iterrows()],
        "cause": cause, "recommandation": reco, "previsions": previsions,
        "distance_source_km": round(dist, 1),
    }


def creer_alertes(pid, etat):
    """Crée au plus une alerte de chaque type par 24 h. Renvoie les nouvelles alertes."""
    from energy.models import Alerte
    if not etat:
        return []
    nouvelles = []
    reco, cause = etat["recommandation"], etat["cause"] or {}

    def _ajouter(type_, niveau, message):
        recent = Alerte.objects.filter(parcelle_id=pid, type=type_, cree_le__gte=timezone.now() - timedelta(hours=24))
        if not recent.exists():
            nouvelles.append(Alerte.objects.create(parcelle_id=pid, type=type_, niveau=niveau, message=message,
                                                   details={"recommandation": reco, "cause": cause.get("cause")}))

    if cause.get("cause") == "PANNE":
        _ajouter("TECHNICIEN", "ALERTE", "PANNE")
    elif reco["action"] in ("NETTOYER", "NETTOYER_APRES_TEMPETE", "ATTENDRE_PLUIE"):
        _ajouter("NETTOYER", "ALERTE" if reco["action"] == "NETTOYER" else "ATTENTION", reco["action"])
    elif reco["action"] == "PREVOIR":
        _ajouter("PREVOIR", "INFO", "PREVOIR")
    return nouvelles
