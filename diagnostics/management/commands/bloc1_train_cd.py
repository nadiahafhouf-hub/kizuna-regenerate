"""Entraîne et teste le modèle « Cd ≥ 1 mg/kg à partir d'un relevé XRF » sur LUCAS Heavy Metals.

    python manage.py bloc1_train_cd "C:/Users/.../HeavyMetals.xlsx"

Sorties : diagnostics/ml_models/cd_xrf.joblib (non versionné)
          fixtures/bloc1/modele_cd_metriques.json (versionné)
"""
import json

from django.core.management.base import BaseCommand

from diagnostics.ml_cd import METRIQUES, MODELE, entrainer


class Command(BaseCommand):
    help = "Entraine/teste le modele Cd (XRF -> risque Cd >= 1 mg/kg) sur LUCAS Heavy Metals."

    def add_arguments(self, parser):
        parser.add_argument("xlsx", help="Chemin de HeavyMetals.xlsx (ESDAC)")

    def handle(self, xlsx, **opts):
        res = entrainer(xlsx)
        METRIQUES.parent.mkdir(parents=True, exist_ok=True)
        METRIQUES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        for nom in ("aleatoire_80_20", "test_mediterranee"):
            r = res[nom]
            t = r["tri_labo"]
            self.stdout.write(f"\n[{nom}] n={r['n']} positifs={r['positifs']} ({r['taux_positifs_pct']}%)")
            self.stdout.write(f"  AUC={r['auc']}  precision moyenne={r['precision_moyenne']}")
            self.stdout.write(f"  Tri labo (garder 90% des sols Cd>=1) : envoyer {t['echantillons_envoyes_au_labo_pct']}%"
                              f" des echantillons -> {t['analyses_economisees_pct']}% d'analyses economisees,"
                              f" {t['precision_des_envoyes_pct']}% des envoyes sont vraiment a risque")
        self.stdout.write(f"\nReference (plomb seul) AUC={res['reference_plomb_seul_auc']}")
        self.stdout.write("Variables les plus utiles : " + ", ".join(
            f"{r['variable']} ({r['baisse_auc']})" for r in res["importance"][:6]))
        self.stdout.write(self.style.SUCCESS(f"\nModele -> {MODELE}\nMetriques -> {METRIQUES}"))
