"""Tests de l'agent d'irrigation (bloc 3). Hors ligne, sans appel à Gemini. python manage.py test irrigation"""
import os
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

os.environ["REGEN_HORS_LIGNE"] = "1"   # jamais d'appel internet dans les tests

from irrigation.services import agent_ia  # noqa: E402
from irrigation.services.consignes import consignes  # noqa: E402
from irrigation.services.planning import generer_planning  # noqa: E402
from irrigation.tests_planning import meteo, reco  # noqa: E402

PID = "GAB-001"


class StockagesTests(SimpleTestCase):
    """Réservoir + bassin : on stocke au soleil l'eau des jours suivants, sans déborder ni dépasser le quota."""

    def plan(self, **p):
        return generer_planning(reco(), dict(dict(bassin_m3=20.0, quota_nappe_m3_semaine=60.0), **p), meteo=meteo())

    def test_stock_total_jamais_depasse(self):
        pl = self.plan()
        cap = pl["totaux"]["capacite_reservoir_l"]
        self.assertEqual(cap, 25000)   # 5 m3 de réservoir + 20 m3 de bassin
        for j in pl["jours"]:
            self.assertLessEqual(j["niveau_soir_l"], cap + 1)
            st = j["stockages_soir"]
            self.assertLessEqual(st["reservoir_l"], 5000)
            self.assertAlmostEqual(st["reservoir_l"] + st["bassin_l"], j["niveau_soir_l"], delta=1)
        self.assertLessEqual(pl["totaux"]["pompe_prevu_l"], pl["totaux"]["quota_l"])

    def test_bassin_permet_de_stocker_plus_au_soleil(self):
        sans = generer_planning(reco(), dict(quota_nappe_m3_semaine=60.0, jours_reserve=3), meteo=meteo())
        avec = self.plan(jours_reserve=3)
        pompe_j1 = lambda pl: pl["jours"][0]["pompe_l"]
        self.assertGreaterEqual(pompe_j1(avec), pompe_j1(sans))
        # la pompe ne tourne qu'au soleil : 0 kWh du réseau, énergie pompe <= production solaire
        for j in avec["jours"]:
            self.assertLessEqual(j["energie_pompe_kwh"], j["energie_solaire_kwh"] + 1e-6)

    def test_comparaison_avec_irrigation_actuelle(self):
        r = reco()
        r["zones"][-1]["irrigation_actuelle"] = "goutte_a_goutte"
        r["zones"][-1]["efficience_actuelle"] = 0.9
        pl = generer_planning(r, dict(quota_nappe_m3_semaine=60.0), meteo=meteo())
        c = {x["zone_id"]: x for x in pl["comparaison"]}
        z = r["zones"][-1]["id"]
        self.assertEqual(c[z]["irrigation_actuelle"], "goutte_a_goutte")
        self.assertEqual(c[z]["efficience"], 0.9)


class ConsignesTests(SimpleTestCase):

    def test_consignes_jour_et_semaine(self):
        m = meteo()
        m["jours"][0]["tmax_c"] = 38
        pl = generer_planning(reco(), dict(bassin_m3=20.0, quota_nappe_m3_semaine=60.0), meteo=m)
        c = consignes(pl, m, [], 0)
        types = {a["type"] for a in c["jour"]["actions"]}
        self.assertIn("arrosage", types)
        self.assertIn("pompage", types)
        self.assertTrue(any("chaleur" in a["texte"] for a in c["alertes"]))
        self.assertEqual(c["semaine"]["reseau_electrique_kwh"], 0)
        self.assertEqual(len(c["semaine"]["par_zone"]), len(pl["zones"]))
        self.assertIn("validez le plan", c["texte"])

    def test_pluie_annule_et_le_dit(self):
        m = meteo(pluies={0: 12})
        pl = generer_planning(reco(), dict(quota_nappe_m3_semaine=60.0), meteo=m)
        c = consignes(pl, m, [], 0)
        self.assertTrue(all(a["type"] in ("annule", "pompage") for a in c["jour"]["actions"]))
        self.assertTrue(any("Pluie" in a["texte"] for a in c["alertes"]))

    def test_gemini_ne_recoit_que_les_chiffres_du_plan(self):
        pl = generer_planning(reco(), dict(quota_nappe_m3_semaine=60.0), meteo=meteo())
        c = consignes(pl, meteo(), [], 0)
        vu = {}

        def faux(cle, modele, prompt):
            vu["prompt"] = prompt
            return "Aujourd'hui : arroser tôt."
        self.assertEqual(agent_ia.rediger(c, "cle-test", "m", appel=faux), "Aujourd'hui : arroser tôt.")
        self.assertIn(str(c["semaine"]["eau_m3"]), vu["prompt"])
        with self.assertRaises(agent_ia.AgentIAErreur):
            agent_ia.rediger(c, "", "m")


class AgentPageTests(TestCase):
    """Page Irrigation : carte de l'agent, zone déclarée plantée dans Crops (réseau), rédaction Gemini simulée."""

    def test_carte_agent_et_json(self):
        r = self.client.get(f"/p/{PID}/irrigation/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Irrigation agent")
        a = self.client.get(f"/p/{PID}/irrigation/agent.json").json()
        self.assertIn("jour", a)
        self.assertTrue(a["semaine"]["par_zone"])

    def test_zone_plantee_dans_crops_prise_en_compte(self):
        from irrigation.agent import zones_agent
        from irrigation.models import DripNetworkPlan
        from services import demo_data
        lp = demo_data.land_profile(PID)
        zid = lp["zones"][-1]["id"]
        zones = [dict(z, etat="PLANTEE", culture="Olivier", irrigation_actuelle={"type": "gravitaire"})
                 if z["id"] == zid else z for z in lp["zones"]]
        DripNetworkPlan.objects.create(
            parcelle_id=PID, land_profile=dict(lp, zones=zones), statut=DripNetworkPlan.Statut.OK,
            resultat={"zones": [{"nom": f"{zid} (VERT)", "conception": {"debit_zone_l_h": 480.0, "n_goutteurs": 96}}],
                      "conseil_simple": [{"zone": f"{zid} (VERT)", "n_plantes": 12, "a_replanter": 0}]})
        za = {z["id"]: z for z in zones_agent(PID)}[zid]
        self.assertEqual((za["etat"], za["nb_plantes"], za["irrigation_actuelle"]), ("PLANTEE", 12, "gravitaire"))
        self.assertEqual(za["kc"], 0.65)          # kc de l'olivier (base du bloc 2)
        self.assertEqual(za["debit_reseau_l_h"], 480.0)
        self.client.post(f"/p/{PID}/irrigation/action/nouveau/")
        a = self.client.get(f"/p/{PID}/irrigation/agent.json").json()
        z = {x["zone"]: x for x in a["semaine"]["par_zone"]}[zid]
        self.assertEqual((z["etat"], z["culture"], z["nb_plantes"]), ("PLANTEE", "Olivier", 12))
        self.assertTrue(z["reseau"])

    @override_settings(GEMINI_API_KEY="cle-test", GEMINI_MODEL="modele-test")
    def test_rediger_avec_gemini_simule_puis_cache(self):
        self.client.get(f"/p/{PID}/irrigation/")
        with mock.patch.object(agent_ia, "_appeler", return_value="Aujourd'hui : rien de spécial.") as appel:
            r = self.client.post(f"/p/{PID}/irrigation/agent/rediger/")
            self.assertContains(r, "Aujourd&#x27;hui : rien de spécial.")
            self.assertEqual(appel.call_count, 1)
        page = self.client.get(f"/p/{PID}/irrigation/")
        self.assertContains(page, "Written by AI")   # texte gardé en cache pour ce plan et ce jour

    @override_settings(GEMINI_API_KEY="")
    def test_sans_cle_texte_automatique(self):
        self.client.get(f"/p/{PID}/irrigation/")
        r = self.client.post(f"/p/{PID}/irrigation/agent/rediger/")
        self.assertContains(r, "AI unavailable")
        self.assertContains(r, "Automatic text")
