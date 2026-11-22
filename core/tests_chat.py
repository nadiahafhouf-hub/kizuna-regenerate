"""Tests du chatbot (bloc 4) : Qdrant en mémoire, embeddings locaux, Gemini simulé. Hors ligne."""
import json
import os
from unittest.mock import patch

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
        self.assertContains(r, 'class="chat-fennec-dock"')
        self.assertContains(r, "fennec.glb")
        self.assertContains(r, "fennec-poster.webp")
        self.assertContains(r, "Enable voice")
        self.assertNotContains(r, "Quick access")

    @patch("services.rag.assistant.repondre")
    def test_commande_de_navigation_locale(self, repondre):
        r = self.client.post(reverse("core:chat"), {"q": "Affiche l’irrigation !", "pid": PID},
                             content_type="application/json").json()
        self.assertEqual(r["mode"], "control")
        self.assertEqual(r["actions"][0]["url"], reverse("irrigation:index", args=[PID]))
        repondre.assert_not_called()

    def test_commande_sans_parcelle_propose_de_choisir_une_parcelle(self):
        for pid in (None, "INCONNUE"):
            r = self.client.post(reverse("core:chat"), {"q": "Ouvre les cultures", "pid": pid},
                                 content_type="application/json").json()
            self.assertIn("Pour quelle parcelle", r["reply"])
            self.assertTrue(any(a["kind"] == "parcel" and a["id"] == PID and a["question"] == "Ouvre les cultures"
                                for a in r["actions"]))
            self.assertIsNone(r["navigate"])

    def test_navigation_vocale_vers_une_parcelle_nommee_depuis_l_accueil(self):
        url = reverse("core:chat")
        for question, route in (
            ("Ouvre la parcelle G A B zéro zéro un", "diagnostics:index"),
            ("Peux-tu ouvrir l’irrigation de la parcelle GAB 001 s’il te plaît ?", "irrigation:index"),
        ):
            with self.subTest(question=question):
                reply = self.client.post(url, {"q": question, "voice": True}, content_type="application/json").json()
                self.assertEqual(reply["navigate"], reverse(route, args=[PID]))
                self.assertTrue(reply["reply"].startswith("J’ouvre"))
        reply = self.client.post(url, {"q": "Ouvre la parcelle XYZ 001", "voice": True},
                                 content_type="application/json").json()
        self.assertIsNone(reply["navigate"])

    def test_simulation_exige_un_post_distinct_et_un_plan_actif(self):
        from irrigation.logic import plan_actif

        plan = plan_actif(PID)
        horloge = plan.horloge
        r = self.client.post(reverse("core:chat"), {"q": "Simule la journée suivante", "pid": PID, "voice": True},
                             content_type="application/json").json()
        action = r["actions"][0]
        self.assertEqual(action["kind"], "simulate")
        self.assertIsNone(r["navigate"])
        self.assertIn("confirme", r["reply"])
        plan.refresh_from_db()
        self.assertEqual(plan.horloge, horloge)
        self.assertEqual(self.client.get(action["url"]).status_code, 405)
        self.assertEqual(self.client.post(action["url"]).status_code, 400)
        for nom in ("valider", "automatique"):
            self.client.post(reverse("irrigation:action", args=[PID, nom]))
        response = self.client.post(action["url"]).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["etat"]["jours_ecoules"], 1)

    @patch("services.rag.assistant.repondre")
    @patch("irrigation.services.meteo.prevision_7_jours")
    def test_temperature_et_pompage_repondent_sans_gemini(self, meteo, repondre):
        import datetime

        from django.utils import timezone
        from irrigation.logic import parcelle_db
        from irrigation.models import IrrigationEvent, IrrigationPlan

        today = timezone.localdate()
        plan = IrrigationPlan.objects.create(parcel=parcelle_db(PID), date_debut=today,
                                             statut=IrrigationPlan.Statut.AUTO,
                                             planning={"jours": [{"date": today.isoformat()}]})
        IrrigationEvent.objects.create(plan=plan, date=today, heure=datetime.time(11), type="POMPAGE",
                                       statut="PREVU", volume_l=500)
        meteo.return_value = {"jours": [{"date": today.isoformat(), "tmin_c": 19, "tmax_c": 23}]}
        reply = self.client.post(reverse("core:chat"), {"q": "chnia l temperature lioum oul pmpe wakteh mch tekhdem",
                                                       "pid": PID}, content_type="application/json").json()
        self.assertEqual(reply["mode"], "local")
        self.assertIn("19 à 23 °C", reply["reply"])
        self.assertIn("11:00", reply["reply"])
        repondre.assert_not_called()

        guide = self.client.post(reverse("core:chat"), {"q": "Montre-moi quand la pompe tourne", "pid": PID, "voice": True},
                                 content_type="application/json").json()
        self.assertEqual(guide["navigate"], f"{reverse('irrigation:index', args=[PID])}?chat_focus=pump&date={today}")
        self.assertIn("11:00", guide["reply"])
        plan.programme.update(statut="ANNULE")
        guide = self.client.post(reverse("core:chat"), {"q": "Montre-moi quand la pompe tourne", "pid": PID},
                                 content_type="application/json").json()
        self.assertEqual(guide["reaction"], "concern")
        self.assertNotIn("11:00", guide["reply"])

    def test_le_guide_ouvre_la_carte_des_zones_rouges(self):
        reply = self.client.post(reverse("core:chat"), {"q": "Où est la zone rouge ?", "pid": PID},
                                 content_type="application/json").json()
        self.assertEqual(reply["navigate"], reverse("diagnostics:index", args=[PID]) + "?chat_focus=red-zone")
        self.assertIn("Z1", reply["reply"])
