"""Meteo des 7 prochains jours : Open-Meteo Forecast, sinon moyennes du climat (partie A). Sans Django."""
import datetime
import json
import math
import time
import urllib.request
from pathlib import Path

from advisor.services.climat import hors_ligne

SOURCE_API = "Open-Meteo (prevision)"
SOURCE_SECOURS = "moyennes du climat (secours sans internet)"
DUREE_CACHE_S = 3600


def rayonnement_ciel_clair(lat, jour, heure):
    """Rayonnement global horizontal (W/m2) par ciel clair, modele de Haurwitz x 0,9 (brume)."""
    n = jour.timetuple().tm_yday
    decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (284 + n))))
    phi = math.radians(lat or 34)
    angle = math.radians(15 * (heure - 12))
    s = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(angle)
    if s <= 0.02:
        return 0.0
    return round(0.9 * 1098 * s * math.exp(-0.057 / s), 1)


def ensoleillement(lat, jour_iso, rayonnement):
    """Part du rayonnement par ciel clair recue ce jour-la (1 = grand soleil, 0,3 = tres nuageux)."""
    jour = datetime.date.fromisoformat(jour_iso)
    clair = sum(rayonnement_ciel_clair(lat, jour, h) for h in range(24))
    return round(max(0.0, min(1.0, sum(rayonnement) / clair)), 2) if clair else 0.0


def meteo_de_secours(lat, climat, date_debut, nb_jours=7):
    jours = []
    for d in range(nb_jours):
        jour = date_debut + datetime.timedelta(days=d)
        jours.append(dict(
            date=jour.isoformat(),
            et0_mm=round(climat["et0_mm_jour"], 2),
            pluie_mm=round(climat["pluie_mm"] / 365, 2),
            tmax_c=None, tmin_c=None,
            rayonnement_w_m2=[rayonnement_ciel_clair(lat, jour, h) for h in range(24)],
        ))
    return dict(source=SOURCE_SECOURS, jours=jours)


def meteo_open_meteo(lat, lon, date_debut, nb_jours=7, timeout=8):
    fin = date_debut + datetime.timedelta(days=nb_jours - 1)
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&daily=et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min"
           "&hourly=shortwave_radiation&timezone=auto&start_date=%s&end_date=%s"
           ) % (lat, lon, date_debut.isoformat(), fin.isoformat())
    with urllib.request.urlopen(url, timeout=timeout) as r:
        d = json.load(r)
    rad = d["hourly"]["shortwave_radiation"]
    jours = []
    for i, date in enumerate(d["daily"]["time"]):
        heures = rad[i * 24:(i + 1) * 24]
        if len(heures) != 24 or any(v is None for v in heures):
            raise ValueError("rayonnement incomplet")
        et0 = d["daily"]["et0_fao_evapotranspiration"][i]
        pluie = d["daily"]["precipitation_sum"][i]
        if et0 is None or pluie is None:
            raise ValueError("donnees manquantes")
        tx, tn = d["daily"]["temperature_2m_max"][i], d["daily"]["temperature_2m_min"][i]
        jours.append(dict(date=date, et0_mm=round(et0, 2), pluie_mm=round(pluie, 1),
                          tmax_c=round(tx) if tx is not None else None, tmin_c=round(tn) if tn is not None else None,
                          rayonnement_w_m2=[round(v, 1) for v in heures]))
    if len(jours) < nb_jours:
        raise ValueError("prevision trop courte")
    return dict(source=SOURCE_API, jours=jours)


def prevision_7_jours(lat, lon, climat, date_debut=None, timeout=8, cache_dir=None):
    """Prevision Open-Meteo (gardee 1 h en cache fichier), sinon moyennes du climat."""
    date_debut = date_debut or datetime.date.today()
    chemin = Path(cache_dir) / f"meteo_{float(lat):.2f}_{float(lon):.2f}_{date_debut}.json" if cache_dir else None
    if chemin and chemin.exists():
        try:
            m = json.loads(chemin.read_text(encoding="utf-8"))
            if time.time() - m.pop("_t", 0) < DUREE_CACHE_S:
                return m
        except (ValueError, OSError):
            pass
    try:
        if hors_ligne():
            raise ConnectionError("mode hors ligne")
        m = meteo_open_meteo(lat, lon, date_debut, timeout=timeout)
    except Exception:
        return meteo_de_secours(lat, climat, date_debut)
    if chemin:
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(json.dumps(dict(m, _t=time.time())), encoding="utf-8")
        except OSError:
            pass
    return m
