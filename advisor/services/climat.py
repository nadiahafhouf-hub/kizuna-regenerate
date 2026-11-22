"""Climat d'une parcelle : Open-Meteo Archive, sinon NASA POWER, sinon table de secours.

Sans Django. Cache en fichiers JSON pour ne pas rappeler l'API a chaque page.
Variable d'environnement REGEN_HORS_LIGNE=1 : on n'appelle jamais internet (tests, demo sans reseau).
"""
import datetime
import json
import math
import os
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCE_API = "Open-Meteo"
SOURCE_NASA = "NASA POWER"
SOURCE_SECOURS = "table de secours"
DUREE_CACHE_SECOURS_S = 600   # on reessaie l'API apres 10 min si on etait hors ligne


def hors_ligne():
    return os.environ.get("REGEN_HORS_LIGNE", "") not in ("", "0", "false", "False")


def charger_regions():
    with open(DATA_DIR / "regions.json", encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def climat_open_meteo(lat, lon, timeout=8):
    """Climat reel de la derniere annee complete (API gratuite, sans cle)."""
    an = datetime.date.today().year - 1
    url = ("https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s"
           "&start_date=%d-01-01&end_date=%d-12-31&timezone=auto&daily=temperature_2m_max,"
           "temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration") % (lat, lon, an, an)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        d = json.load(r)["daily"]
    mois = {}
    for date, tx, tn in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"]):
        m = mois.setdefault(date[5:7], [[], []])
        m[0].append(tx)
        m[1].append(tn)

    def moy(v):
        v = [x for x in v if x is not None]
        if not v:
            raise ValueError("donnees vides")
        return sum(v) / len(v)

    return dict(
        lat=lat, lon=lon, annee=an,
        pluie_mm=round(sum(p or 0 for p in d["precipitation_sum"])),
        tmin_hiver=round(min(moy(m[1]) for m in mois.values()), 1),
        tmax_ete=round(max(moy(m[0]) for m in mois.values()), 1),
        et0_mm_jour=round(moy(d["et0_fao_evapotranspiration"]), 2),
    )


def rayonnement_extraterrestre(lat, jour_annee):
    """Ra (MJ/m2/jour), FAO-56 equation 21."""
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * jour_annee / 365)
    decl = 0.409 * math.sin(2 * math.pi * jour_annee / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(decl))))
    return 24 * 60 / math.pi * 0.0820 * dr * (ws * math.sin(phi) * math.sin(decl)
                                               + math.cos(phi) * math.cos(decl) * math.sin(ws))


def et0_hargreaves(tmax, tmin, lat, jour_annee):
    """ET0 (mm/jour) par Hargreaves (FAO-56 eq. 52) : utile quand on n'a que les temperatures."""
    tmoy = (tmax + tmin) / 2
    ra = rayonnement_extraterrestre(lat, jour_annee)
    return 0.0023 * (tmoy + 17.8) * math.sqrt(max(0.0, tmax - tmin)) * 0.408 * ra


def climat_nasa_power(lat, lon, timeout=15):
    """Deuxieme source reelle (NASA POWER, gratuite, sans cle) : annee precedente, donnees journalieres."""
    an = datetime.date.today().year - 1
    url = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M_MAX,T2M_MIN,PRECTOTCORR"
           "&community=AG&longitude=%s&latitude=%s&start=%d0101&end=%d1231&format=JSON") % (lon, lat, an, an)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        p = json.load(r)["properties"]["parameter"]
    mois, pluie, et0 = {}, 0.0, []
    for date, tx in p["T2M_MAX"].items():
        tn, pr = p["T2M_MIN"].get(date, -999), p["PRECTOTCORR"].get(date, -999)
        if -999 in (tx, tn):          # -999 = donnee manquante chez NASA
            continue
        m = mois.setdefault(date[4:6], [[], []])
        m[0].append(tx)
        m[1].append(tn)
        if pr != -999:
            pluie += pr
        jour = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:])).timetuple().tm_yday
        et0.append(et0_hargreaves(tx, tn, lat, jour))
    if len(et0) < 300:
        raise ValueError("annee trop incomplete")
    moy = lambda v: sum(v) / len(v)
    return dict(lat=lat, lon=lon, annee=an, pluie_mm=round(pluie),
                tmin_hiver=round(min(moy(m[1]) for m in mois.values()), 1),
                tmax_ete=round(max(moy(m[0]) for m in mois.values()), 1),
                et0_mm_jour=round(moy(et0), 2))


def region_la_plus_proche(lat, lon, regions):
    def dist(r):
        return math.hypot(r["lat"] - lat, (r["lon"] - lon) * math.cos(math.radians(lat)))
    return min(regions, key=lambda k: dist(regions[k]))


def climat_de_secours(lat, lon, region):
    regions = charger_regions()
    if region in regions:
        nom, note = region, ""
    else:   # region inconnue : on prend la plus proche (le systeme marche partout)
        nom = region_la_plus_proche(lat, lon, regions)
        note = f" (region la plus proche : {nom})"
    c = dict(regions[nom])
    c.update(lat=lat, lon=lon, source=SOURCE_SECOURS, detail_source=f"{SOURCE_SECOURS}{note}")
    return c


def obtenir_climat(lat, lon, region, cache_dir=None, timeout=8, cache_only=False):
    """Renvoie pluie_mm (an), tmin_hiver, tmax_ete, et0_mm_jour + source."""
    cle = f"climat_{float(lat):.2f}_{float(lon):.2f}_{datetime.date.today().year - 1}.json"
    chemin = Path(cache_dir) / cle if cache_dir else None
    if chemin and chemin.exists():
        try:
            c = json.loads(chemin.read_text(encoding="utf-8"))
            frais = c.get("source") in (SOURCE_API, SOURCE_NASA) or time.time() - c.get("_t", 0) < DUREE_CACHE_SECOURS_S
            if frais:
                c.pop("_t", None)
                c["depuis_cache"] = True
                return c
        except (ValueError, OSError):
            pass
    c = None
    if not cache_only and not hors_ligne():
        try:
            c = climat_open_meteo(lat, lon, timeout=timeout)
            c.update(source=SOURCE_API, detail_source=f"{SOURCE_API} (archive {c['annee']})")
        except Exception:
            try:   # Open-Meteo limite parfois les appels (erreur 429) : deuxieme source reelle
                c = climat_nasa_power(lat, lon, timeout=timeout + 7)
                c.update(source=SOURCE_NASA, detail_source=f"{SOURCE_NASA} ({c['annee']}, ET0 Hargreaves)")
            except Exception:
                c = None
    if c is None:
        c = climat_de_secours(lat, lon, region)
    if chemin and not cache_only and not hors_ligne():
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(json.dumps(dict(c, _t=time.time()), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    c["depuis_cache"] = False
    return c
