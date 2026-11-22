"""Tests du volet photovoltaïque : python manage.py test energy (sans réseau)."""
import json
from datetime import date

import numpy as np
from django.test import SimpleTestCase, TestCase

from .services import ia_cause, ia_prevision
from .services.climat import GABES
from .services.dimensionnement import G_RHO, dimensionner, eau_par_plante_l_jour

ZONE = {"id": "Z1", "culture": "Atriplex", "nb_plants": 1000, "kc": 0.65, "couverture": 0.6, "espacement_m": 1.0, "lr": 0.1}


class DimensionnementTests(SimpleTestCase):
    def test_eau_par_plante(self):
        # ET0 7.4 mm × 0.65 × 0.6 × 1 m² ÷ 0.9 (lessivage) ÷ 0.9 (goutte-à-goutte), sans pluie
        self.assertAlmostEqual(eau_par_plante_l_jour(7.4, 0, 31, 0.65, 0.6, 1.0, 0.1), 7.4 * 0.39 / 0.9 / 0.9, places=3)

    def test_plus_de_plantes_plus_de_panneaux(self):
        petit = dimensionner([{**ZONE, "nb_plants": 500}], GABES)
        grand = dimensionner([{**ZONE, "nb_plants": 20000}], GABES)
        self.assertGreater(grand["nb_panneaux"], petit["nb_panneaux"])
        self.assertEqual(grand["mois_dimensionnant"], "Jul")   # mois le plus exigeant à Gabès

    def test_puits_plus_profond_plus_d_energie(self):
        a = dimensionner([ZONE], GABES, profondeur_m=20)
        b = dimensionner([ZONE], GABES, profondeur_m=80)
        self.assertGreater(b["energie_pointe_kwh_jour"], 2 * a["energie_pointe_kwh_jour"])

    def test_energie_physique(self):
        d = dimensionner([ZONE], GABES, profondeur_m=40, rendement_pompe=0.45)
        v = d["eau_pointe_m3_jour"]
        self.assertAlmostEqual(d["energie_pointe_kwh_jour"], round(G_RHO * v * 55.0 / 0.45, 2), places=1)

    def test_panneaux_couvrent_le_mois_de_pointe(self):
        d = dimensionner([{**ZONE, "nb_plants": 30000}], GABES)
        juillet = next(m for m in d["mensuel"] if m["mois"] == "Jul")
        self.assertGreaterEqual(juillet["production_kwh_jour"], juillet["energie_kwh_jour"])


class PrevisionTests(SimpleTestCase):
    def test_jours_avant_seuil(self):
        self.assertEqual(ia_prevision.jours_avant_seuil(0.01, 0.01), 4)
        self.assertEqual(ia_prevision.jours_avant_seuil(0.06, 0.01), 0)

    def test_pluie_nettoie(self):
        prev = [{"date": "2026-11-23", "poussiere_max": 0, "pluie_mm": 12}] + [{"date": "x", "poussiere_max": 0, "pluie_mm": 0}] * 10
        self.assertGreater(ia_prevision.jours_avant_seuil(0.04, 0.005, previsions=prev), 2)

    def test_tempete_puis_nettoyage(self):
        ip = 1 - 0.006 * np.arange(1, 16)
        prev = [{"date": "2026-11-25", "poussiere_max": 250, "pluie_mm": 0}]
        r = ia_prevision.recommander(ip, prev, aujourd_hui=date(2026, 11, 22))
        self.assertEqual(r["action"], "NETTOYER_APRES_TEMPETE")
        self.assertEqual(r["date_conseillee"], "2026-11-26")

    def test_propre_rien(self):
        r = ia_prevision.recommander(np.ones(12), [], aujourd_hui=date(2026, 11, 22))
        self.assertIn(r["action"], ("RIEN", "PREVOIR"))
        self.assertLess(r["perte_pct"], 1)


class CauseTests(SimpleTestCase):
    def test_formes(self):
        rng = np.random.default_rng(0)
        bruit = 1 + rng.normal(0, 0.01, 21)
        poussiere = bruit * (1 - 0.008 * np.arange(1, 22))
        panne = bruit.copy()
        panne[12:] *= 0.7
        self.assertEqual(ia_cause.diagnostiquer(poussiere)["cause"], "POUSSIERE")
        self.assertEqual(ia_cause.diagnostiquer(panne)["cause"], "PANNE")
        self.assertEqual(ia_cause.diagnostiquer(bruit)["cause"], "PROPRE")


class VuesTests(TestCase):
    def test_api_esp32(self):
        from .models import MesurePV
        r = self.client.post("/api/energy/GAB-001/readings/", data=json.dumps(
            {"mesures": [{"t": "2026-11-22T12:00:00", "w": 410.5, "poa": 850, "t_air": 22}]}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(MesurePV.objects.get().puissance_w, 410.5)
        self.assertEqual(self.client.post("/api/energy/GAB-001/readings/", data="{bad", content_type="application/json").status_code, 400)

    def test_analyse_hors_ligne(self):
        from .models import ConfigSolaire
        from .services.projet import analyse
        cfg = ConfigSolaire.objects.create(parcelle_id="GAB-001", plantes={"Z1": 50})
        a = analyse("GAB-001", cfg, reseau=False, surveiller=False)
        self.assertGreaterEqual(a["dim"]["nb_panneaux"], 1)
        self.assertEqual(next(z for z in a["dim"]["zones"] if z["id"] == "Z1")["nb_plants"], 50)

    def test_nettoyage(self):
        from .models import Nettoyage
        r = self.client.post("/p/GAB-001/solar/clean/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Nettoyage.objects.filter(parcelle_id="GAB-001", date=date.today()).exists())


class SansModeleTests(SimpleTestCase):
    """Chez un coéquipier qui n'a pas lancé `energy_train` : replis (règles, formule physique)."""

    def test_replis(self):
        from unittest import mock

        from .services import ia_production
        with mock.patch.dict(ia_cause._CACHE, {"m": None}), mock.patch.dict(ia_production._CACHE, {"m": None}):
            ip = 1 - 0.008 * np.arange(1, 22)
            self.assertEqual(ia_cause.diagnostiquer(ip)["cause"], "POUSSIERE")
            w = ia_production.attendu_w_par_kwc([800, 0], [25, 10], [60, -5])
            self.assertGreater(w[0], 500)
            self.assertEqual(w[1], 0)
