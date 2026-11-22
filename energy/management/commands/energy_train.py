"""Entraîne et teste les IA du volet solaire à partir des vraies données NREL versionnées (sans réseau).

    python manage.py energy_train

IA 1 → energy/ml_models/production.joblib + fixtures/energy/ia1_metriques.json
IA 2 → energy/ml_models/cause.joblib      + fixtures/energy/ia2_metriques.json
IA 3 → validation ajoutée à fixtures/energy/ia2_metriques.json (clé « ia3 »)
Sans ces fichiers .joblib, l'application utilise des replis (formule physique, règles simples).
"""
import json

from django.core.management.base import BaseCommand

from energy.services import ia_cause, ia_prevision, ia_production
from energy.services.pvdaq import charger


class Command(BaseCommand):
    help = "Entraine/teste IA 1 (production attendue), IA 2 (cause de baisse), IA 3 (date de nettoyage)."

    def handle(self, **opts):
        df = charger()
        r1 = ia_production.entrainer(df)
        self.stdout.write(f"IA 1 (test 2013) : IA {r1['modele_ia']} | formule {r1['formule_physique_pvwatts']}")
        r2 = ia_cause.entrainer(df)
        self.stdout.write(f"IA 2 (test 2013) : exactitude {r2['exactitude_pct']} %, fausses alertes {r2['fausses_alertes_pct']} %")
        import joblib
        r3 = ia_prevision.valider(joblib.load(ia_cause.MODELE)["ip_2013"])
        r2["ia3"] = r3
        ia_cause.METRIQUES.write_text(json.dumps(r2, ensure_ascii=False, indent=1), encoding="utf-8")
        self.stdout.write(f"IA 3 : erreur mediane {r3['erreur_mediane_jours']} j, p80 {r3['erreur_p80_jours']} j")
        self.stdout.write(self.style.SUCCESS("OK"))
