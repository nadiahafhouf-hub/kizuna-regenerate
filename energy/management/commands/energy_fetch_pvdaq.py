"""Télécharge les vraies données NREL PVDAQ (système 4) et les agrège à l'heure.

    python manage.py energy_fetch_pvdaq [--debut 2010-01-01] [--fin 2011-12-31]
"""
from datetime import date

from django.core.management.base import BaseCommand

from energy.services.pvdaq import SORTIE, telecharger


class Command(BaseCommand):
    help = "Telecharge NREL PVDAQ systeme 4 (vraies donnees de production PV) vers fixtures/energy/."

    def add_arguments(self, parser):
        parser.add_argument("--debut", default="2010-01-01")
        parser.add_argument("--fin", default="2011-12-31")

    def handle(self, debut, fin, **opts):
        df = telecharger(date.fromisoformat(debut), date.fromisoformat(fin))
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        df.round(2).to_csv(SORTIE, compression="gzip")
        self.stdout.write(self.style.SUCCESS(
            f"{len(df)} heures, {df.index.min()} -> {df.index.max()} -> {SORTIE}"))
        self.stdout.write(str(df.describe().round(1)))
