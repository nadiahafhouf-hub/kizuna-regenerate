"""Bloc 3 · réseau goutte-à-goutte : python manage.py test irrigation

Aucun accès réseau : un faux serveur de tuiles remplace Esri (sable bruité + oliviers dessinés
exactement sur l'emprise GPS du LandProfile ; tuiles uniformes au zoom 20 pour tester le repli).
"""

import io
import json
import re
import shutil
import tempfile
import urllib.error
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from django.test import TestCase, override_settings
from PIL import Image

from services import demo_data
from services.irrigation_engine import satellite as S
from services.irrigation_engine.parcelle import analyser_parcelle

from .models import DripNetworkPlan

PID = "GAB-001"


class FauxServeurTuiles:
    URL = "http://tuiles.test/{z}/{x}/{y}.png"

    def __init__(self, profil, zoom_vide=20, panne=False, arbres_m=((6, 6), (16, 7), (25, 6), (7, 17), (17, 16),
                                                                     (26, 17), (6, 26), (16, 25), (25, 26))):
        self.profil, self.zoom_vide, self.panne, self.arbres_m, self.appels = profil, zoom_vide, panne, arbres_m, []

    def __call__(self, url, timeout=20):
        self.appels.append(url)
        if self.panne:
            raise urllib.error.URLError("reseau injoignable")
        m = re.search(r"tuiles\.test/(\d+)/(\d+)/(\d+)\.png", url)
        if not m:  # métadonnées Esri, etc.
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        z, x, y = map(int, m.groups())
        if z >= self.zoom_vide:
            arr = np.full((256, 256, 3), 204, np.uint8)
        else:
            arr = np.clip(np.random.default_rng(x * 7919 + y).normal((196, 176, 140), 6, (256, 256, 3)),
                          0, 255).astype(np.uint8)
            o = self.profil["origine"]
            res = S.resolution_m_px(o["lat"], z)
            x0, y0 = S.lonlat_vers_px(o["lon"], o["lat"], z)
            for ax, ay in self.arbres_m:  # oliviers adultes de 4 m de couronne
                cx, cy = int(round(x0 + ax / res - x * 256)), int(round(y0 + ay / res - y * 256))
                cv2.circle(arr, (cx, cy), max(2, int(2.0 / res)), (48, 88, 62), -1)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, "PNG")
        return buf.getvalue()


class ReseauSatelliteTests(TestCase):
    CONF = {"SATELLITE_FOURNISSEUR": "test", "SATELLITE_TILE_URL": FauxServeurTuiles.URL,
            "SATELLITE_ZOOM": 19, "SATELLITE_ATTRIBUTION": "Tuiles de test"}

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="kizuna_test_media_")
        self.reglages = override_settings(MEDIA_ROOT=self.media, **self.CONF)
        self.reglages.enable()
        self.profil = demo_data.land_profile(PID)
        self.serveur = FauxServeurTuiles(self.profil)
        self.patch = mock.patch.object(S, "_http_get", self.serveur)
        self.patch.start()
        self.url = f"/p/{PID}/irrigation/network/"

    def tearDown(self):
        self.patch.stop()
        self.reglages.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_formules_web_mercator(self):
        self.assertEqual(S.lonlat_vers_px(0, 0, 0), (128.0, 128.0))
        self.assertAlmostEqual(S.resolution_m_px(0, 0), 156543.03)
        self.assertTrue(S.tuile_vide(np.full((256, 256, 3), 204, np.uint8)))

    def test_mosaique_repli_de_zoom_et_cache(self):
        cache = Path(self.media) / "cache"
        conf = {"url": FauxServeurTuiles.URL, "fournisseur": "test", "cache": cache}
        sat = S.image_satellite(self.profil, Path(self.media) / "sat", **conf)
        self.assertEqual(sat["zoom"], 19)  # zoom 20 vide -> repli
        (x0, _), (x1, _) = sat["coins_px"][0], sat["coins_px"][1]
        self.assertAlmostEqual((x1 - x0) * sat["resolution_m_px"], self.profil["largeur_m"], delta=1)
        self.assertFalse((cache / "test" / "20").exists())  # tuiles vides jamais en cache
        n = len(self.serveur.appels)
        S.image_satellite(self.profil, Path(self.media) / "sat2", zoom_force=19, **conf)
        self.assertEqual(len(self.serveur.appels), n)  # tout vient du cache

    def test_page_et_calcul_satellite(self):
        self.assertContains(self.client.get(f"/p/{PID}/irrigation/"), self.url)  # lien depuis le planning
        self.assertContains(self.client.get(self.url), "Drip network design")
        r = self.client.post(self.url, {"source_image": "satellite"})
        self.assertRedirects(r, self.url)
        plan = DripNetworkPlan.objects.get()
        self.assertEqual(plan.statut, DripNetworkPlan.Statut.OK, plan.message)
        self.assertIn(f"{PID}_satellite", plan.photo.name)
        self.assertEqual(plan.calage["mode"], "satellite")
        self.assertEqual(plan.source_image["zoom"], 19)
        self.assertTrue(plan.image_trace)
        self.assertGreaterEqual(sum(c["n_plantes"] or 0 for c in plan.conseil), 6)
        page = self.client.get(self.url)
        self.assertContains(page, "Tuiles de test")
        self.assertEqual(self.client.get(f"{self.url}geojson/").json()["type"], "FeatureCollection")
        self.assertEqual(self.client.get(f"{self.url}api/").json()["statut"], "OK")
        # recalcul : réutilise l'image enregistrée, sans réseau
        self.serveur.panne = True
        self.client.post(f"{self.url}recompute/")
        plan.refresh_from_db()
        self.assertEqual(plan.statut, DripNetworkPlan.Statut.OK, plan.message)

    def test_apercu_puis_source_cliquee(self):
        d = self.client.post(f"{self.url}preview/").json()
        self.assertEqual(d["zoom"], 19)
        ap = Path(self.media) / d["image"].split("/media/", 1)[1]
        brut = next(ap.parent.glob("satellite_*.png"))
        self.assertAlmostEqual(Image.open(ap).size[0] / d["scale"], Image.open(brut).size[0], delta=1)
        ne = d["coins_px"][1]
        self.client.post(self.url, {"source_image": "satellite", "satellite_zoom": d["zoom"],
                                    "source_px": json.dumps([[ne[0] - 3, ne[1] + 3]])})
        plan = DripNetworkPlan.objects.get()
        self.assertEqual(plan.calage["zoom"], 19)
        src = next(f for f in plan.geojson["features"] if f["properties"]["couche"] == "source")
        self.assertGreater(src["geometry"]["coordinates"][0], self.profil["origine"]["lon"])

    def test_panne_reseau_message_clair(self):
        self.serveur.panne = True
        r = self.client.post(self.url, {"source_image": "satellite"}, follow=True)
        self.assertContains(r, "internet")
        r = self.client.post(f"{self.url}preview/")
        self.assertEqual(r.status_code, 422)


class ArbresEparsTests(TestCase):
    """Terre DÉJÀ plantée d'arbres épars : on irrigue chaque arbre, sans en inventer à replanter."""

    def test_arbres_epars_aucun_a_replanter(self):
        ppm = 5  # 20 cm/px, parcelle 40 x 40 m
        img = np.clip(np.random.default_rng(1).normal((190, 165, 125), 5, (200, 200, 3)), 0, 255).astype(np.uint8)
        for x, y in ((9, 8), (30, 15), (14, 31)):
            cv2.circle(img, (x * ppm, y * ppm), int(3.0 * ppm), (62, 88, 48), -1)
        dossier = Path(tempfile.mkdtemp(prefix="kizuna_test_epars_"))
        try:
            Image.fromarray(img).save(dossier / "epars.png")
            profil = {"parcelle_id": "EPARS", "region": "Sfax", "origine": {"lat": 34.7, "lon": 10.6},
                      "largeur_m": 40, "longueur_m": 40, "taille_case_m": 40, "texture_sol": "limoneux",
                      "cases": [], "source_eau": {"x_m": 1, "y_m": 1}, "eau": {"CE_dS_m": 2},
                      "zones": [{"id": "Z1", "cases": [[0, 0]], "culture": "olivier", "etat": "PLANTEE",
                                 "irrigation_actuelle": {"type": "gravitaire"}}]}
            res = analyser_parcelle(profil, dossier / "epars.png", {"mode": "ortho"}, dossier / "out")
            c = res["conseil_simple"][0]
            self.assertEqual((c["n_plantes"], c["a_replanter"]), (3, 0))
            self.assertEqual(res["_conception"].zones[0]["mode"], "arbres_existants")
        finally:
            shutil.rmtree(dossier, ignore_errors=True)
