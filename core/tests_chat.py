"""Tests du chatbot (bloc 4) : Qdrant en mémoire, embeddings locaux, Gemini simulé. Hors ligne."""
import json
import os

from django.test import TestCase, override_settings
from django.urls import reverse

os.environ["REGEN_HORS_LIGNE"] = "1"

from services.rag import assistant, vecteurs  # noqa: E402

PID = "GAB-001"
CFG = {"cle": "", "modele": "m", "modele_embedding": "", "chemin": ":memory:"}


@override_settings(QDRANT_PATH=":memory:", QDRANT_URL="", GEMINI_API_KEY="")
class ChatbotTests(TestCase):

    def setUp(self):
        vecteurs.fermer()   # base vectorielle neuve pour chaque test

    def tearDown(self):
        vecteurs.fermer()

    def test_qdrant_indexe_une_fois_et_retrouve(self):
        docs = assistant.docs_connaissances()
        self.assertGreater(vecteurs.indexer(docs, "connaissances", CFG), 0)
        self.assertEqual(vecteurs.indexer(docs, "connaissances", CFG), 0)   # empreinte identique : rien à refaire
        res = vecteurs.chercher("Atriplex halimus salinity tolerance", CFG)
        self.assertTrue(res)
        self.assertIn("ATRIPLEX", res[0]["titre"].upper())

    def test_donnees_de_la_parcelle_et_derja(self):
        faits, actions = assistant.indexer_tout(PID, CFG)
        self.assertEqual(faits["parcelle"]["id"], PID)
        ids = {a["id"] for a in actions}
        self.assertIn("cultures", ids)
        self.assertIn("concevoir_reseau", ids)          # pas encore de réseau goutte-à-goutte
        res = vecteurs.chercher("cadmium zone Z1 culture alimentaire", CFG, parcelle_id=PID)
        self.assertTrue(any(r.get("parcelle_id") == PID for r in res))
        # une autre parcelle n'apparaît jamais dans les résultats de GAB-001
        self.assertTrue(all(r.get("parcelle_id") in ("", PID) for r in res))

    def test_reponse_de_secours_sans_cle(self):
        r = assistant.repondre("Kifech ns9i lyoum?", PID, cfg=CFG)
        self.assertEqual(r["mode"], "secours")
        self.assertTrue(r["reponse"])
        self.assertTrue(r["sources"])

    def test_gemini_derja_et_actions_fermees(self):
        vu = {}

        def faux(cle, modele, prompt):
            vu["prompt"] = prompt
            return json.dumps({"reponse": "Lyoum ns9i zone Z3 m3a 6 sbe7.", "actions": ["cultures", "inventee"]})
        r = assistant.repondre("Kifech ns9i lyoum?", PID, [{"role": "user", "text": "aslema"}],
                               cfg=dict(CFG, cle="test"), appel=faux)
        self.assertEqual(r["mode"], "gemini")
        self.assertEqual(r["reponse"], "Lyoum ns9i zone Z3 m3a 6 sbe7.")
        self.assertEqual([a["id"] for a in r["actions"]], ["cultures"])   # action inventée écartée
        self.assertIn("derja tounsiya", r and vu["prompt"])
        self.assertIn(PID, vu["prompt"])
        self.assertIn("aslema", vu["prompt"])

    def test_gemini_en_panne_reponse_de_secours(self):
        def panne(cle, modele, prompt):
            raise RuntimeError("503 UNAVAILABLE")
        r = assistant.repondre("wa9tech el pompe tekhdem?", PID, cfg=dict(CFG, cle="test"), appel=panne)
        self.assertEqual(r["mode"], "secours")
        self.assertIn("erreur", r)

    def test_vue_chat(self):
        url = reverse("core:chat")
        r = self.client.post(url, json.dumps({"q": "Chnowa nzra3 fi zone Z1?", "pid": PID}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["reply"])
        self.assertIn(d["mode"], ("secours", "gemini"))
        self.assertTrue(d["sources"])
        r = self.client.post(url, json.dumps({"q": "aslema", "pid": "INCONNUE"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)   # parcelle inconnue : connaissances générales seulement

    def test_panneau_sur_les_pages_avec_parcelle(self):
        r = self.client.get(reverse("irrigation:index", args=[PID]))
        self.assertContains(r, f'"pid": "{PID}"')
        self.assertContains(r, "Kifech ns9i lyoum?")
