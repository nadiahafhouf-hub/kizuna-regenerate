"""Tests du planning d'irrigation 7 jours (bloc 2). Hors ligne. Lancer : python manage.py test irrigation"""
import datetime
import json
import os
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

os.environ["REGEN_HORS_LIGNE"] = "1"   # jamais d'appel internet dans les tests

from advisor.services.recommandation import recommander_cultures  # noqa: E402
from irrigation.services.automatisme import decider_arrosage, decider_pompage  # noqa: E402
from irrigation.services.meteo import meteo_de_secours  # noqa: E402
from irrigation.services.planning import generer_planning, production_solaire_kw  # noqa: E402

FIX = Path(settings.BASE_DIR) / "fixtures"
PROFILS = [FIX / "land_profile.sample.json", FIX / "demo/land_profiles/GAB-002.json",
           FIX / "demo/land_profiles/GAB-003.json"]
CLIMAT = dict(pluie_mm=180, tmin_hiver=6, tmax_ete=33, et0_mm_jour=4.5, source="table de secours")
DEBUT = datetime.date(2026, 11, 22)


def reco(p=PROFILS[0]):
    return recommander_cultures(json.loads(Path(p).read_text(encoding="utf-8")), climat=CLIMAT)


def meteo(pluies=None, et0=4.5, nuageux=()):
    m = meteo_de_secours(33.88, CLIMAT, DEBUT)
    for i, j in enumerate(m["jours"]):
        j["et0_mm"] = et0
        j["pluie_mm"] = (pluies or {}).get(i, 0)
        if i in nuageux:
            j["rayonnement_w_m2"] = [r * 0.3 for r in j["rayonnement_w_m2"]]
    return m


class PlanningTests(SimpleTestCase):

    def test_plan_7_jours(self):
        plan = generer_planning(reco(), meteo=meteo())
        self.assertEqual(len(plan["jours"]), 7)
        self.assertEqual({e["type"] for e in plan["evenements"]}, {"POMPAGE", "ARROSAGE"})

    # Test 4 : 10 mm de pluie -> arrosage annule avec sa raison
    def test_pluie_annule_arrosage(self):
        for p in PROFILS:
            plan = generer_planning(reco(p), meteo=meteo(pluies={2: 10}))
            jour = [e for e in plan["evenements"] if e["type"] == "ARROSAGE" and e["date"] == plan["jours"][2]["date"]]
            self.assertTrue(jour)
            for e in jour:
                self.assertEqual(e["statut"], "ANNULE")
                self.assertIn("10 mm de pluie", e["raison"])

    # Test 5 : le total pompe ne depasse jamais le quota
    def test_quota_jamais_depasse(self):
        for p in PROFILS:
            for q in (15, 5, 1):
                plan = generer_planning(reco(p), dict(quota_nappe_m3_semaine=q), meteo=meteo(et0=7))
                self.assertLessEqual(sum(e["volume_l"] for e in plan["evenements"] if e["type"] == "POMPAGE"), q * 1000)

    def test_quota_reduit_d_abord_la_depollution(self):
        # Z3 (VERT) demande ~7,3 m3 sur la semaine : le quota de 9 m3 ne suffit pas pour tout
        plan = generer_planning(reco(), dict(quota_nappe_m3_semaine=9), meteo=meteo(et0=6))
        par = lambda zid: [e for e in plan["evenements"] if e["zone_id"] == zid and e["type"] == "ARROSAGE"]
        self.assertFalse(any("quota" in e["raison"] for e in par("Z3")))         # VERT servie d'abord
        self.assertTrue(any("quota de nappe atteint" in e["raison"] for e in par("Z1")))   # ROUGE reduite

    # Test 6 : pompage seulement si la production solaire suffit
    def test_pompage_seulement_au_soleil(self):
        m = meteo(nuageux=(1, 2))
        plan = generer_planning(reco(), meteo=m)
        p = plan["parametres"]
        rad = {j["date"]: j["rayonnement_w_m2"] for j in m["jours"]}
        pompages = [e for e in plan["evenements"] if e["type"] == "POMPAGE"]
        self.assertTrue(pompages)
        for e in pompages:
            kw = production_solaire_kw(rad[e["date"]][int(e["heure"][:2])], p["puissance_crete_kwc"], p["ratio_performance"])
            self.assertGreaterEqual(kw, p["puissance_pompe_kw"])
        plan2 = generer_planning(reco(), dict(puissance_crete_kwc=0.5), meteo=m)
        self.assertFalse([e for e in plan2["evenements"] if e["type"] == "POMPAGE"])

    # Test 7 : le reservoir ne deborde jamais
    def test_reservoir_jamais_au_dessus_de_sa_capacite(self):
        for cap in (5, 2, 1):
            plan = generer_planning(reco(), dict(capacite_reservoir_m3=cap, niveau_initial_m3=cap),
                                    meteo=meteo(et0=6, nuageux=(3,)))
            self.assertTrue(all(0 <= t["niveau_l"] <= cap * 1000 for t in plan["trajectoire_reservoir"]))

    def test_zone_rouge_sans_lessivage_dans_le_planning(self):
        plan = generer_planning(reco(), meteo=meteo())
        r = reco()
        self.assertEqual(next(z for z in r["zones"] if z["couleur"] == "ROUGE")["lr"], 0)
        self.assertGreater(plan["totaux"]["eau_economisee_l"], 0)

    def test_automate(self):
        self.assertEqual(decider_arrosage(300, 8, 10, 5000, 5, 30)[0], "ANNULE")
        self.assertIn("humide", decider_arrosage(300, 0, 35, 5000, 5, 30)[2])
        self.assertEqual(decider_arrosage(300, 0, 10, 5000, 5, 30)[:2], ("FAIT", 300))
        self.assertEqual(decider_pompage(1500, 4000, 5000, 0, 15000)[:2], ("FAIT", 1000))


class PageTests(TestCase):
    """Parcours complet sur la vraie page : planning en base, Valider -> Automatique -> Simuler -> Reprendre la main."""

    def test_contrat_demo_data(self):
        from services import demo_data
        for pid in ("GAB-001", "GAB-002", "GAB-003"):
            plan = demo_data.irrigation_plan(pid)
            self.assertIn("sources", plan)                 # vrai planning, pas la version demo
            self.assertEqual(len(plan["days"]), 7)
            for d in plan["days"]:
                for k in ("index", "weekday", "day", "month", "slots", "pump", "hourly",
                          "irrigation_m3", "flood_m3", "skipped"):
                    self.assertIn(k, d)
            self.assertLessEqual(plan["totals"]["pumped_m3"], plan["totals"]["quota_m3"])

    def test_parcours_complet(self):
        from irrigation.models import IrrigationEvent, IrrigationPlan
        pid = "GAB-001"
        r = self.client.get(f"/p/{pid}/irrigation/")
        self.assertEqual(r.status_code, 200)
        plan = IrrigationPlan.objects.get()
        self.assertEqual(plan.statut, "BROUILLON")
        self.assertEqual(self.client.post(f"/p/{pid}/irrigation/simuler/").status_code, 400)   # pas encore auto
        # modifier un volume -> plan recalcule
        date = plan.date_debut.isoformat()
        self.client.post(f"/p/{pid}/irrigation/modifier/", {"zone_id": "Z3", "date": date, "volume_l": "450"})
        self.assertEqual(sum(e.volume_l for e in plan.programme.filter(zone_id="Z3", date=plan.date_debut)), 450)
        # Valider -> Automatique
        self.client.post(f"/p/{pid}/irrigation/action/valider/")
        self.client.post(f"/p/{pid}/irrigation/action/automatique/")
        plan.refresh_from_db()
        self.assertEqual(plan.statut, "AUTO")
        self.assertEqual(self.client.get(f"/p/{pid}/irrigation/").status_code, 200)
        cap = plan.planning["totaux"]["capacite_reservoir_l"]
        for _ in range(8):                                     # 7 jours + 1 clic de trop
            j = self.client.post(f"/p/{pid}/irrigation/simuler/").json()
            self.assertTrue(j["ok"])
            self.assertTrue(0 <= j["etat"]["reservoir"]["niveau_l"] <= cap)
            self.assertLessEqual(j["etat"]["quota"]["pompe_l"], j["etat"]["quota"]["quota_l"])
        self.assertFalse(plan.programme.filter(statut="PREVU").exists())
        self.assertTrue(j["etat"]["semaine_finie"])
        self.assertTrue(plan.evenements.filter(action="OUVERTURE").exists())        # journal ValveEvent
        ev = self.client.get(f"/p/{pid}/irrigation/passeport.json").json()["evenements"]
        self.assertTrue(ev and all(e["statut"] in ("FAIT", "ANNULE") for e in ev))
        # Reprendre la main -> l'automate ne fait plus rien
        self.client.post(f"/p/{pid}/irrigation/action/nouveau/")
        plan2 = IrrigationPlan.objects.first()
        self.client.post(f"/p/{pid}/irrigation/action/valider/")
        self.client.post(f"/p/{pid}/irrigation/action/automatique/")
        self.client.post(f"/p/{pid}/irrigation/action/manuel/")
        self.client.post(f"/p/{pid}/irrigation/simuler/")
        self.assertFalse(IrrigationEvent.objects.filter(plan=plan2, statut="FAIT").exists())

    def test_pages_des_trois_parcelles(self):
        for pid in ("GAB-001", "GAB-002", "GAB-003"):
            self.assertEqual(self.client.get(f"/p/{pid}/irrigation/").status_code, 200)
            self.assertIn("evenements", self.client.get(f"/p/{pid}/irrigation/plan.json").json())
            self.assertEqual(self.client.get(f"/p/{pid}/irrigation/passeport.json").json()["evenements"], [])
