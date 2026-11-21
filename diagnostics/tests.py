"""Tests du bloc 1 : python manage.py test diagnostics"""
import json
from pathlib import Path

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TestCase

from .couleur import couleur_case
from .models import LandProfile, SensorReading
from .idw import interpoler_grille, loocv
from .pipeline import construire_land_profile, regrouper_zones
from .sampling import disposition, nb_points_recommande, nb_stations_recommande, plan_capteurs
from .synthetic import generer_parcelle, mesurer

SAMPLE = Path(settings.BASE_DIR) / "fixtures" / "land_profile.sample.json"
GCT = [{"name": "GCT", "lat": 33.9165, "lon": 10.1010, "radius_km": 5}]


def _m(l, c, ce=3.0, ph=7.5, cd=0.5, pb=20.0):
    return {"ligne": l, "col": c, "CE_dS_m": ce, "pH": ph, "Cd_mg_kg": cd, "Pb_mg_kg": pb}


class PlanCapteursTests(SimpleTestCase):
    def test_regle_nombre_de_points(self):
        self.assertEqual(nb_points_recommande(30, 30), 5)        # minimum : 4 coins + centre
        self.assertEqual(nb_points_recommande(100, 100), 25)     # 1 point / 400 m²
        self.assertEqual(nb_stations_recommande(30, 30), 1)
        self.assertEqual(nb_stations_recommande(100, 100), 4)    # 1 station / 2 500 m²

    def test_coins_et_centre(self):
        pts = disposition(3, 3, 5)
        self.assertEqual(set(pts), {(0, 0), (0, 2), (2, 0), (2, 2), (1, 1)})

    def test_disposition_sans_doublon_et_dans_la_grille(self):
        for nl, nc, n in [(3, 4, 6), (5, 5, 7), (10, 10, 25), (2, 3, 5), (1, 4, 5)]:
            pts = disposition(nl, nc, n)
            self.assertEqual(len(pts), len(set(pts)))
            self.assertEqual(len(pts), min(n, nl * nc))
            self.assertTrue(all(0 <= l < nl and 0 <= c < nc for l, c in pts))

    def test_plan_avec_gps(self):
        p = plan_capteurs(30, 30, 33.8828, 10.0683, sources=GCT)
        self.assertEqual(p["nb_cases"], 9)
        self.assertGreaterEqual(len(p["points"]), 5)
        self.assertTrue(all(33.88 < q["lat"] <= 33.8828 and q["lon"] >= 10.0683 for q in p["points"]))
        self.assertIsNotNone(p["renfort"])  # source à ~5 km < 3 × rayon


class IdwTests(SimpleTestCase):
    def test_valeur_mesuree_conservee(self):
        cases, info = interpoler_grille([_m(0, 0, cd=4.0), _m(2, 2, cd=0.4), _m(0, 2, cd=1.0)], 3, 3)
        c00 = next(c for c in cases if (c["ligne"], c["col"]) == (0, 0))
        self.assertEqual(c00["Cd_mg_kg"], 4.0)
        self.assertEqual(c00["source"], "capteur")
        self.assertEqual(c00["confiance"], 1.0)

    def test_interpolation_entre_min_et_max(self):
        cases, _ = interpoler_grille([_m(0, 0, cd=4.0), _m(2, 2, cd=0.4), _m(0, 2, cd=1.0)], 3, 3)
        for c in cases:
            self.assertTrue(0.4 <= c["Cd_mg_kg"] <= 4.0)
        self.assertTrue(all(c["source"] == "idw" for c in cases if (c["ligne"], c["col"]) == (1, 1)))

    def test_confiance_baisse_avec_la_distance(self):
        cases, _ = interpoler_grille([_m(0, 0), _m(0, 1)], 6, 6)
        pres = next(c for c in cases if (c["ligne"], c["col"]) == (1, 0))
        loin = next(c for c in cases if (c["ligne"], c["col"]) == (5, 5))
        self.assertGreater(pres["confiance"], loin["confiance"])

    def test_loocv_champ_constant_zero_erreur(self):
        r = loocv([_m(0, 0), _m(0, 2), _m(2, 0), _m(2, 2)], "Cd_mg_kg")
        self.assertAlmostEqual(r["rmse"], 0.0)


class PipelineTests(SimpleTestCase):
    def test_contrat_land_profile(self):
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        mesures = [_m(0, 0, ce=9.5, ph=7.9, cd=4.2, pb=120), _m(0, 2, ce=6.9, cd=1.8, pb=60),
                   _m(2, 0, ce=6.2, cd=1.4, pb=52), _m(2, 2, ce=3.9, ph=7.2, cd=0.5, pb=22), _m(1, 1, ce=6.5, cd=1.6, pb=55)]
        lp = construire_land_profile("GAB-001", 30, 30, 33.8828, 10.0683, mesures, "2026-11-22",
                                     texture_sol="sablo-limoneux")
        # mêmes clés que le contrat (+ « interpolation » en plus)
        self.assertTrue(set(sample) <= set(lp))
        self.assertTrue(set(sample["cases"][0]) <= set(lp["cases"][0]))
        self.assertTrue(set(sample["zones"][0]) <= set(lp["zones"][0]))
        self.assertEqual(len(lp["cases"]), 9)
        self.assertTrue(1 <= len(lp["zones"]) <= 3)
        for c in lp["cases"]:  # une seule fonction couleur
            self.assertEqual(c["couleur"], couleur_case(c["CE_dS_m"], c["pH"], c["Cd_mg_kg"], c["Pb_mg_kg"]))
        self.assertEqual(sum(len(z["cases"]) for z in lp["zones"]), 9)

    def test_zones_ordre_et_alimentaire(self):
        cases = [{"ligne": 0, "col": i, "couleur": k, "CE_dS_m": 3, "pH": 7.5, "Cd_mg_kg": cd, "Pb_mg_kg": 20}
                 for i, (k, cd) in enumerate([("VERT", 0.5), ("ROUGE", 5.0), ("ORANGE", 1.5)])]
        zones = regrouper_zones(cases)
        self.assertEqual([z["couleur"] for z in zones], ["ROUGE", "ORANGE", "VERT"])
        self.assertEqual([z["culture_alimentaire_autorisee"] for z in zones], [False, False, True])


class SyntheticTests(SimpleTestCase):
    def test_plus_pollue_pres_de_la_source(self):
        pres = np.mean([generer_parcelle(5, 5, distance_km=0.5, seed=s)["Cd_mg_kg"].mean() for s in range(20)])
        loin = np.mean([generer_parcelle(5, 5, distance_km=9, seed=s)["Cd_mg_kg"].mean() for s in range(20)])
        self.assertGreater(pres, 3 * loin)

    def test_mesures_bout_en_bout(self):
        v = generer_parcelle(3, 3, distance_km=3, seed=1)
        m = mesurer(v, disposition(3, 3, 5), np.random.default_rng(0))
        lp = construire_land_profile("T", 30, 30, 33.88, 10.07, m, "2026-11-22")
        self.assertEqual(len(lp["cases"]), 9)


class ParcoursAgriculteurTests(TestCase):
    """Nouvelle parcelle → plan → relevés → diagnostic, puis les autres étapes du parcours."""

    def test_parcours_complet(self):
        r = self.client.post("/parcels/new/", {"nom": "Test", "agriculteur": "A", "region": "Gabes",
                                               "largeur": 40, "longueur": 30, "lat": 33.8843, "lon": 10.0757})
        self.assertEqual(r.status_code, 302)
        pid = r.url.split("/")[2]
        self.assertTrue(pid.startswith("KZ-"))
        # pas encore de diagnostic → redirection vers le plan
        self.assertRedirects(self.client.get(f"/p/{pid}/diagnostic/"), f"/p/{pid}/diagnostic/plan/")
        self.assertEqual(self.client.get(f"/p/{pid}/diagnostic/plan/").status_code, 200)

        sim = self.client.get(f"/p/{pid}/diagnostic/plan/simulate/").json()
        data = {"date": "2026-11-22", "texture": "sablo-limoneux"}
        for point, vals in sim["readings"].items():
            for k in ("CE_dS_m", "pH", "Cd_mg_kg", "Pb_mg_kg", "Cu_mg_kg", "Zn_mg_kg"):
                data[f"{point}_{k}"] = vals[k]
        r = self.client.post(f"/p/{pid}/diagnostic/campaign/", data)
        self.assertRedirects(r, f"/p/{pid}/diagnostic/")
        lp = LandProfile.objects.get(parcel__parcelle_id=pid).data
        self.assertEqual(len(lp["cases"]), 12)
        self.assertEqual(SensorReading.objects.filter(parcel__parcelle_id=pid).count(), len(sim["readings"]))
        for url in (f"/p/{pid}/diagnostic/", f"/p/{pid}/crops/", f"/p/{pid}/irrigation/",
                    f"/p/{pid}/passport/", f"/verify/{pid}-P1/", "/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_releve_invalide(self):
        r = self.client.post("/parcels/new/", {"largeur": 30, "longueur": 30, "lat": 33.88, "lon": 10.07})
        pid = r.url.split("/")[2]
        r = self.client.post(f"/p/{pid}/diagnostic/campaign/", {"P1_CE_dS_m": "abc"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(LandProfile.objects.filter(parcel__parcelle_id=pid).exists())

    def test_parcelle_hors_limites_refusee(self):
        r = self.client.post("/parcels/new/", {"largeur": 5000, "longueur": 30, "lat": 33.88, "lon": 10.07})
        self.assertEqual(r.status_code, 200)


def _sat(nl, nc, f):
    """Couche satellite factice : f(ligne, col) → (ndvi, ndmi, si)."""
    cases = []
    for l in range(nl):
        for c in range(nc):
            ndvi, ndmi, si = f(l, c)
            cases.append({"ligne": l, "col": c, "valide": True, "scl": "vegetation" if ndvi >= 0.3 else "bare_soil",
                          "ndvi": ndvi, "ndmi": ndmi, "si": si})
    return {"source": "test", "attribution": "test", "image": "T", "date": "2026-11-02",
            "nuages_scene_pct": 0, "cases_valides_pct": 100, "taille_case_m": 10, "cases": cases}


class SatelliteFusionTests(SimpleTestCase):
    def _profile(self, ce_de):
        from .sampling import disposition
        pts = disposition(5, 5, 9)
        mesures = [_m(l, c, ce=ce_de(l, c)) for l, c in pts]
        return construire_land_profile("T", 50, 50, 33.88, 10.07, mesures, "2026-11-22")

    def test_fusion_adoptee_si_le_satellite_explique_la_ce(self):
        from .satellite_fusion import appliquer_satellite
        ndmi = lambda l, c: [0.30, -0.20, 0.25, -0.15, 0.10][(l * 3 + c) % 5]  # motif non lisse
        prof = self._profile(lambda l, c: round(4 + 20 * ndmi(l, c), 2))
        prof = appliquer_satellite(prof, _sat(5, 5, lambda l, c: (0.6, ndmi(l, c), 0.1)))
        f = prof["fusion_ce"]
        self.assertTrue(f["adoptee"], f)
        self.assertEqual(f["covariable"], "ndmi")
        self.assertGreater(f["gain_pct"], 10)
        # le contrat est conservé
        self.assertTrue(1 <= len(prof["zones"]) <= 3)
        for c in prof["cases"]:
            self.assertEqual(c["couleur"], couleur_case(c["CE_dS_m"], c["pH"], c["Cd_mg_kg"], c["Pb_mg_kg"]))

    def test_fusion_refusee_si_pas_de_lien(self):
        from .satellite_fusion import appliquer_satellite
        rng = np.random.default_rng(3)
        prof = self._profile(lambda l, c: round(float(rng.uniform(2, 12)), 2))
        avant = [c["CE_dS_m"] for c in prof["cases"]]
        prof = appliquer_satellite(prof, _sat(5, 5, lambda l, c: (0.6, float(rng.uniform(-0.2, 0.3)), 0.1)))
        self.assertFalse(prof["fusion_ce"]["adoptee"])
        self.assertEqual(avant, [c["CE_dS_m"] for c in prof["cases"]])  # IDW conservé

    def test_cd_et_pb_jamais_modifies(self):
        from .satellite_fusion import appliquer_satellite
        prof = self._profile(lambda l, c: 3 + l)
        avant = [(c["Cd_mg_kg"], c["Pb_mg_kg"]) for c in prof["cases"]]
        prof = appliquer_satellite(prof, _sat(5, 5, lambda l, c: (0.5, 0.1 * l, 0.1)))
        self.assertEqual(avant, [(c["Cd_mg_kg"], c["Pb_mg_kg"]) for c in prof["cases"]])

    def test_observations(self):
        from .satellite_fusion import observations_zone
        zone = {"couleur": "ROUGE"}
        cases = [{"ligne": 0, "col": i, "CE_dS_m": 8.0} for i in range(3)]
        pix = {(0, i): {"valide": True, "ndvi": 0.6, "ndmi": -0.1, "si": 0.1} for i in range(3)}
        codes = [o["code"] for o in observations_zone(zone, cases, pix)]
        self.assertIn("stress_hydrique_fort", codes)
        self.assertIn("couvert_utile", codes)
        pix = {(0, i): {"valide": True, "ndvi": 0.1, "ndmi": -0.2, "si": 0.2} for i in range(3)}
        codes = [o["code"] for o in observations_zone(zone, cases, pix)]
        self.assertEqual(codes, ["sol_nu_a_couvrir", "sel_surface_probable"])

    def test_demo_sans_fusion(self):
        from .satellite_fusion import appliquer_satellite
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        avant = [c["CE_dS_m"] for c in sample["cases"]]
        out = appliquer_satellite(sample, _sat(3, 3, lambda l, c: (0.15, -0.1, 0.12)), fusion=False)
        self.assertEqual(avant, [c["CE_dS_m"] for c in out["cases"]])
        self.assertNotIn("fusion_ce", out)
        self.assertTrue(all(z.get("observations") for z in out["zones"]))

    def test_satellite_indisponible_hors_ligne(self):
        from unittest import mock

        from .satellite import SatelliteIndisponible, analyser
        with mock.patch("pystac_client.Client.open", side_effect=OSError("offline")):
            with self.assertRaises(SatelliteIndisponible):
                analyser(33.88, 10.07, 30, 30)
