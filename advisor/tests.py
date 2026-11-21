"""Tests du bloc 2 (terre nue). Hors ligne : climat = table de secours. Lancer : python manage.py test advisor"""
import copy
import json
import os
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

os.environ["REGEN_HORS_LIGNE"] = "1"   # jamais d'appel internet dans les tests

from advisor.services.eau import besoin_eau_jour, fraction_lessivage  # noqa: E402
from advisor.services.recommandation import (ErreurSecurite, charger_plantes,  # noqa: E402
                                             recommander_cultures, verifier_securite)
from advisor.services.validation import valider_land_profile  # noqa: E402

FIX = Path(settings.BASE_DIR) / "fixtures"
PROFILS = [FIX / "land_profile.sample.json", FIX / "demo/land_profiles/GAB-002.json",
           FIX / "demo/land_profiles/GAB-003.json"]
CLIMAT = dict(pluie_mm=180, tmin_hiver=6, tmax_ete=33, et0_mm_jour=4.5, source="table de secours")
CLIMAT_PLUVIEUX = dict(pluie_mm=600, tmin_hiver=8, tmax_ete=31, et0_mm_jour=3.5, source="table de secours")


def charger(p=PROFILS[0]):
    return json.loads(Path(p).read_text(encoding="utf-8"))


class RecommandationTests(SimpleTestCase):

    # Test 1 : securite absolue
    def test_zone_interdite_jamais_de_culture_alimentaire(self):
        plantes = charger_plantes()
        for p in PROFILS:
            for clim in (CLIMAT, CLIMAT_PLUVIEUX, None):
                r = recommander_cultures(charger(p), climat=clim)
                for z in r["zones"]:
                    if not z["culture_alimentaire_autorisee"]:
                        self.assertFalse(z["alimentaire"], z)
                        self.assertTrue(all(not a["alimentaire"] for a in z["alternatives"]))
                        self.assertFalse(plantes.get(z["cle"], {}).get("alimentaire", False))

    def test_zone_verte_interdite_recoit_du_non_alimentaire(self):
        lp = charger()
        vert = next(z for z in lp["zones"] if z["couleur"] == "VERT")
        vert["culture_alimentaire_autorisee"] = False
        z = next(z for z in recommander_cultures(lp, climat=CLIMAT)["zones"] if z["id"] == vert["id"])
        self.assertFalse(z["alimentaire"])

    def test_plante_alimentaire_du_bloc1_retiree(self):
        lp = charger()
        lp["zones"][0]["traitement"]["plantes"] = ["Olea europaea", "Atriplex halimus"]
        r = recommander_cultures(lp, climat=CLIMAT)
        self.assertEqual(r["zones"][0]["culture"], "Atriplex halimus")
        self.assertTrue(any("retiree" in a for a in r["avertissements"]))

    def test_verifier_securite(self):
        r = recommander_cultures(charger(), climat=CLIMAT)
        r["zones"][0]["alimentaire"] = True
        with self.assertRaises(ErreurSecurite):
            verifier_securite(r)

    # Test 2 : zone ROUGE
    def test_zone_rouge_lr_zero_et_collecte(self):
        for p in PROFILS:
            for z in recommander_cultures(charger(p), climat=CLIMAT)["zones"]:
                self.assertEqual(z["collecte_drainage"], z["couleur"] == "ROUGE")
                if z["couleur"] == "ROUGE":
                    self.assertEqual(z["lr"], 0)
        self.assertEqual(fraction_lessivage("ROUGE", 1.0), 0.0)

    # Test 3 : zone VERTE = une seule culture
    def test_zone_verte_une_seule_culture(self):
        for p in PROFILS:
            r = recommander_cultures(charger(p), climat=CLIMAT)
            for z in [z for z in r["zones"] if z["couleur"] == "VERT"]:
                self.assertNotIn(" + ", z["culture"])
                self.assertEqual({c["culture"] for c in r["cases"] if c["zone_id"] == z["id"]}, {z["culture"]})
                self.assertLessEqual(len(z["alternatives"]), 2)

    def test_rouge_orange_reprennent_le_bloc1(self):
        r = recommander_cultures(charger(), climat=CLIMAT)
        for z in r["zones"]:
            if z["couleur"] in ("ROUGE", "ORANGE"):
                self.assertEqual(z["decide_par"], "bloc 1")
                self.assertIn("Atriplex halimus", z["culture"])

    def test_traitement_vide_regle_de_secours(self):
        lp = charger()
        lp["zones"][1]["traitement"] = None
        z = recommander_cultures(lp, climat=CLIMAT)["zones"][1]
        self.assertEqual(z["decide_par"], "bloc 2")
        self.assertIn("Atriplex", z["culture"])

    def test_couleur_jamais_recalculee(self):
        lp = copy.deepcopy(charger())
        lp["cases"][0]["CE_dS_m"] = 0.5
        self.assertEqual(recommander_cultures(lp, climat=CLIMAT)["cases"][0]["couleur"], lp["cases"][0]["couleur"])

    def test_ce_eau_gabes(self):
        r = recommander_cultures(charger(), climat=CLIMAT)
        self.assertEqual(r["ce_eau_dS_m"], 3.5)
        lp = charger()
        lp["ce_eau_dS_m"] = 1.0
        self.assertEqual(recommander_cultures(lp, climat=CLIMAT)["ce_eau_dS_m"], 1.0)

    def test_formule_fao(self):
        e = besoin_eau_jour(1.0, 1.0, 20, "ROUGE", 100, 5, 0, 1.0)
        self.assertEqual(e["net_l"], 500)
        self.assertAlmostEqual(e["brut_l"], 500 / 0.9, places=0)

    def test_validation_land_profile(self):
        for p in PROFILS:
            self.assertEqual(valider_land_profile(charger(p))[0], [])
        bad = charger()
        del bad["origine"]
        self.assertTrue(any("origine" in e for e in valider_land_profile(bad)[0]))


class PageTests(TestCase):
    """La page Crops affiche les vraies recommandations du bloc 2 et ne plante jamais."""

    def test_pages_et_api(self):
        for pid in ("GAB-001", "GAB-002", "GAB-003"):
            self.client.post(f"/p/{pid}/crops/mode/", {"mode": "bare"})
            r = self.client.get(f"/p/{pid}/crops/")
            self.assertEqual(r.status_code, 200)
            self.assertIsNotNone(r.context["bloc2"])
            for rec in r.context["recommendations"]:
                if rec["zone"]["couleur"] == "VERT":
                    self.assertEqual(sum(1 for c in rec["crops"] if c["recommended"]), 1)
                else:
                    self.assertTrue(rec["remediation"])
                    self.assertFalse(rec["crops"])
            j = self.client.get(f"/p/{pid}/crops/recommandation.json").json()
            self.assertEqual(j["etat"], "terre_nue")
        r = self.client.get("/p/GAB-001/crops/plan/")
        self.assertEqual(r["Content-Type"], "image/png")
