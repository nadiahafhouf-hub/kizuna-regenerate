"""Extrait les points LUCAS 2009 méditerranéens calcaires (proches des sols de Gabès).

    python manage.py bloc1_extract_lucas "C:/Users/.../LUCAS_TOPSOIL_v1.xlsx"

Sortie (versionnée, petite) : fixtures/bloc1/lucas_med_calcaire.csv
Filtre : latitude < 41° N, CaCO3 ≥ 50 g/kg, pH(H2O) ≥ 7.
"""
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

SORTIE = Path(settings.BASE_DIR) / "fixtures" / "bloc1" / "lucas_med_calcaire.csv"
COLS = ["pH_in_H2O", "clay", "silt", "sand", "CaCO3", "OC", "CEC", "GPS_LAT", "GPS_LONG"]


def texture_usda(clay, silt, sand):
    """Classe de texture simplifiée (triangle USDA) en libellé du projet."""
    if sand >= 70 and clay < 15:
        return "sableux"
    if clay >= 40:
        return "argileux"
    if clay >= 27:
        return "argilo-limoneux"
    if sand >= 43:
        return "sablo-limoneux"
    return "limoneux"


class Command(BaseCommand):
    help = "Extrait les points LUCAS méditerranéens calcaires vers fixtures/bloc1/."

    def add_arguments(self, parser):
        parser.add_argument("xlsx", help="Chemin de LUCAS_TOPSOIL_v1.xlsx")

    def handle(self, xlsx, **opts):
        df = pd.read_excel(xlsx)
        for c in COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        m = df[(df.GPS_LAT < 41) & (df.CaCO3 >= 50) & (df.pH_in_H2O >= 7)][COLS].dropna()
        m["texture"] = [texture_usda(r.clay, r.silt, r.sand) for r in m.itertuples()]
        m = m.round({"GPS_LAT": 3, "GPS_LONG": 3})  # précision réduite (≈ 100 m)
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        m.to_csv(SORTIE, index=False)
        self.stdout.write(self.style.SUCCESS(f"{len(m)} points -> {SORTIE}"))
        self.stdout.write(str(m.texture.value_counts().to_dict()))
