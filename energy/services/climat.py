"""Climat solaire et hydrique d'un lieu (sources ouvertes, sans compte), avec cache.

- PVGIS v5.3 (Commission européenne, JRC) : production mensuelle d'1 kWc à l'inclinaison optimale,
  pertes système 14 % incluses (base SARAH-3, 2005-2023).
- Open-Meteo Archive (ERA5) : évapotranspiration de référence ET0 (FAO-56) et pluie, mois par mois.
- Open-Meteo Air Quality (CAMS) : prévision de poussière désertique et PM10 sur 5 jours.

Cache : fixtures/energy/climat/<lat>_<lon>.json (versionné pour les parcelles de démo → démo hors ligne).
Repli si le réseau manque : valeurs mesurées pour Gabès (33.88 N, 10.07 E) le 22/11/2026.
"""
import json
from datetime import date
from pathlib import Path

import requests
from django.conf import settings

CACHE = Path(settings.BASE_DIR) / "fixtures" / "energy" / "climat"
PVGIS = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
METEO = "https://api.open-meteo.com/v1/forecast"

# Repli : Gabès (PVGIS-SARAH3 et ERA5 2025, récupérés le 22/11/2026)
GABES = {
    "source": "repli Gabès (PVGIS v5.3 + Open-Meteo ERA5 2025)",
    "pv_kwh_kwc_jour": [4.48, 4.89, 5.08, 5.32, 5.25, 5.29, 5.41, 5.30, 5.00, 4.65, 4.33, 4.09],
    "inclinaison_deg": 33, "pv_kwh_kwc_an": 1797.2,
    "et0_mm_jour": [2.73, 2.71, 4.43, 4.81, 5.70, 6.60, 7.40, 6.42, 5.33, 4.46, 3.41, 2.07],
    "pluie_mm_mois": [50.4, 14.2, 38.1, 10.1, 25.3, 0.1, 0.0, 0.7, 9.2, 15.4, 10.7, 34.6],
}


def _cle(lat, lon):
    return f"{lat:.2f}_{lon:.2f}"


def climat(lat, lon, reseau=True):
    """Climat mensuel (12 valeurs) : production PV par kWc, ET0, pluie. Cache → réseau → repli Gabès."""
    f = CACHE / f"{_cle(lat, lon)}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    if not reseau:
        return GABES
    try:
        pv = requests.get(PVGIS, params={"lat": lat, "lon": lon, "peakpower": 1, "loss": 14,
                                         "optimalangles": 1, "outputformat": "json"}, timeout=40).json()
        mois = pv["outputs"]["monthly"]["fixed"]
        an = date.today().year - 1
        a = requests.get(ARCHIVE, params={"latitude": lat, "longitude": lon, "start_date": f"{an}-01-01",
                                          "end_date": f"{an}-12-31", "timezone": "auto",
                                          "daily": "et0_fao_evapotranspiration,precipitation_sum"}, timeout=40).json()["daily"]
        et0, pluie = [[] for _ in range(12)], [0.0] * 12
        for t, e, p in zip(a["time"], a["et0_fao_evapotranspiration"], a["precipitation_sum"]):
            m = int(t[5:7]) - 1
            et0[m].append(e or 0)
            pluie[m] += p or 0
        out = {
            "source": f"PVGIS v5.3 ({pv['inputs']['meteo_data']['radiation_db']}) + Open-Meteo ERA5 {an}",
            "pv_kwh_kwc_jour": [round(x["E_d"], 2) for x in mois],
            "inclinaison_deg": pv["inputs"]["mounting_system"]["fixed"]["slope"]["value"],
            "pv_kwh_kwc_an": round(pv["outputs"]["totals"]["fixed"]["E_y"], 1),
            "et0_mm_jour": [round(sum(v) / len(v), 2) for v in et0],
            "pluie_mm_mois": [round(v, 1) for v in pluie],
        }
    except Exception:
        return GABES
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def previsions(lat, lon):
    """5 jours : poussière (µg/m³, max journalier) et pluie (mm). None si pas de réseau. Cache 3 h."""
    from django.core.cache import cache
    cle = f"prev_{_cle(lat, lon)}"
    if cache.get(cle) is not None:
        return cache.get(cle)
    out = _previsions(lat, lon)
    if out is not None:
        cache.set(cle, out, 3 * 3600)
    return out


def _previsions(lat, lon):
    try:
        air = requests.get(AIR, params={"latitude": lat, "longitude": lon, "hourly": "dust,pm10",
                                        "forecast_days": 5, "timezone": "auto"}, timeout=20).json()["hourly"]
        met = requests.get(METEO, params={"latitude": lat, "longitude": lon, "daily": "precipitation_sum",
                                          "forecast_days": 5, "timezone": "auto"}, timeout=20).json()["daily"]
    except Exception:
        return None
    jours = {}
    for t, d in zip(air["time"], air["dust"]):
        jours.setdefault(t[:10], []).append(d or 0)
    return [{"date": j, "poussiere_max": round(max(jours.get(j, [0])), 0), "pluie_mm": round(p or 0, 1)}
            for j, p in zip(met["time"], met["precipitation_sum"])]
