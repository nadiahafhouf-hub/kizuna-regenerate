"""Vraies données de production photovoltaïque : NREL PVDAQ (accès libre, sans compte).

Système n°4 « NREL x-Si » (Golden, Colorado) : 1 kWc, mesures à la minute de la puissance AC,
du rayonnement dans le plan des modules (POA), de la température ambiante et des modules.
Source : OEDI data lake (s3://oedi-data-lake/pvdaq/), licence ouverte NREL.

On agrège à l'heure et on garde un petit CSV compressé dans fixtures/energy/ (versionné) pour que
l'entraînement soit reproductible sans réseau.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
from django.conf import settings

BASE = "https://oedi-data-lake.s3.amazonaws.com/pvdaq/parquet/pvdata/system_id%3D{sid}/year={y}/month={m}/day={d}/system_{sid}__date_{y}_{m:02d}_{d:02d}.snappy.000.parquet"
SYSTEME = 4
KWC = 1.0
METRIQUES = {315: "ac_power_w", 313: "poa_w_m2", 320: "t_air_c", 321: "t_module_c"}
SORTIE = Path(settings.BASE_DIR) / "fixtures" / "energy" / "pvdaq_s4_horaire.csv.gz"


def _jour(j: date, sid=SYSTEME):
    url = BASE.format(sid=sid, y=j.year, m=j.month, d=j.day)
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return None
        df = pd.read_parquet(BytesIO(r.content))
    except Exception:
        return None
    df = df[df.metric_id.isin(METRIQUES)]
    if df.empty:
        return None
    df = df.pivot_table(index="measured_on", columns="metric_id", values="value", aggfunc="mean")
    df = df.rename(columns=METRIQUES)
    df.index = pd.to_datetime(df.index)
    return df.resample("1h").mean()


def telecharger(debut: date, fin: date, workers=16):
    jours = [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        morceaux = [d for d in ex.map(_jour, jours) if d is not None]
    df = pd.concat(morceaux).sort_index()
    df = df[[c for c in METRIQUES.values() if c in df]]
    df.index.name = "heure_locale"
    return df


def charger():
    """Données horaires versionnées (fixtures). Colonnes : ac_power_w, poa_w_m2, t_air_c, t_module_c."""
    return pd.read_csv(SORTIE, parse_dates=["heure_locale"], index_col="heure_locale")
