"""Analyse Sentinel-2 des parcelles (couche satellite du bloc 1).

    python manage.py bloc1_satellite              # toutes les parcelles (démo + base)
    python manage.py bloc1_satellite GAB-001 KZ-001

- Parcelles de démo : résultat écrit dans fixtures/bloc1/satellite/<id>.json (versionné → démo hors ligne).
- Parcelles en base : le dernier LandProfile est mis à jour (fusion CE testée, observations, points de contrôle).
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from diagnostics.satellite import SatelliteIndisponible

CACHE = Path(settings.BASE_DIR) / "fixtures" / "bloc1" / "satellite"


class Command(BaseCommand):
    help = "Analyse Sentinel-2 (NDVI, NDMI, sel de surface) des parcelles."

    def add_arguments(self, parser):
        parser.add_argument("pids", nargs="*")

    def handle(self, pids, **opts):
        from diagnostics.views import analyser_parcelle
        from services import demo_data

        pids = pids or [p["id"] for p in demo_data._parcel_records(with_profile_only=True)]
        for pid in pids:
            try:
                sat = analyser_parcelle(pid)
            except SatelliteIndisponible as e:
                self.stdout.write(self.style.WARNING(f"{pid}: indisponible ({e})"))
                continue
            if not demo_data.is_db_parcel(pid):
                CACHE.mkdir(parents=True, exist_ok=True)
                (CACHE / f"{pid}.json").write_text(json.dumps(sat, ensure_ascii=False, indent=1), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(
                f"{pid}: image {sat['date']} ({sat['nuages_scene_pct']}% nuages scene, "
                f"{sat['cases_valides_pct']}% cases valides)"))
