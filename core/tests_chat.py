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


@override_settings(QDRANT_PATH=":memory:", QDRANT_URL="", GEMINI_API_KEY="", AZURE_SPEECH_KEY="", VOIX_EDGE_TTS=False, VOIX_LAHGTNA=False,
                   WHISPER_DERJA_MODEL="")
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

    # ───────────── voix (tounsi) : Azure et Gemini simulés ─────────────

    def test_azure_ecoute_et_voix_tunisienne(self):
        from services.rag import voix
        cfg = {"azure_cle": "k", "azure_region": "westeurope", "voix": "ar-TN-HediNeural", "langue": "ar-TN"}
        vu = {}

        def http(url, data, entetes, timeout=30):
            vu.setdefault("urls", []).append(url)
            vu["data"], vu["entetes"] = data, entetes
            if "stt" in url:
                return json.dumps({"RecognitionStatus": "Success", "DisplayText": "كيفاش نسقي اليوم؟"}).encode()
            return b"ID3-mp3"
        texte, moteur = voix.transcrire(b"RIFF" + b"\0" * 4000, cfg, http=http)
        self.assertEqual((texte, moteur), ("كيفاش نسقي اليوم؟", "azure"))
        self.assertIn("language=ar-TN", vu["urls"][0])
        self.assertEqual(voix.azure_tts("• Lyoum ns9i 🌱\n- zone Z3", cfg, http=http), b"ID3-mp3")
        ssml = vu["data"].decode()
        self.assertIn("ar-TN-HediNeural", ssml)
        self.assertNotIn("🌱", ssml)
        self.assertNotIn("•", ssml)

    def test_secours_gemini_si_azure_echoue(self):
        from services.rag import voix
        cfg = {"azure_cle": "k", "azure_region": "westeurope", "gemini_cle": "g"}

        def http(url, data, entetes, timeout=30):
            raise voix.VoixErreur("Azure HTTP 401")
        texte, moteur = voix.transcrire(b"RIFF" + b"\0" * 4000, cfg, http=http,
                                        appel_gemini=lambda wav, consigne: "شنوة نزرع؟")
        self.assertEqual((texte, moteur), ("شنوة نزرع؟", "gemini"))
        with self.assertRaises(voix.VoixErreur):
            voix.transcrire(b"RIFF" + b"\0" * 4000, {})          # rien de configuré

    def test_vue_voix(self):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        appels = {}

        def faux_repondre(q, pid=None, historique=None, **kw):
            appels.update(q=q, pid=pid, **kw)
            return {"reponse": "اليوم تسقي الزونة Z3 مع الستة الصباح.", "actions": [], "sources": [], "mode": "gemini"}
        with mock.patch("services.rag.voix.transcrire", return_value=("كيفاش نسقي؟", "azure")), \
                mock.patch("services.rag.assistant.repondre", side_effect=faux_repondre), \
                mock.patch("services.rag.voix.synthese", return_value=(b"mp3", "audio/mpeg")):
            r = self.client.post(reverse("core:chat_voice"), {
                "audio": SimpleUploadedFile("voix.wav", b"RIFF" + b"\0" * 4000, content_type="audio/wav"),
                "pid": PID, "historique": "[]"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["transcription"], "كيفاش نسقي؟")
        self.assertEqual(d["audio"], "bXAz")                    # base64 de b"mp3"
        self.assertTrue(appels["voix"])                         # réponse courte, en lettres arabes
        self.assertEqual(appels["pid"], PID)

    def test_ecoute_gratuite_whisper_derja_avant_gemini(self):
        from services.rag import voix
        cfg = {"whisper": "modele-test", "gemini_cle": "g"}
        texte, moteur = voix.transcrire(b"RIFF" + b"\0" * 4000, cfg, whisper=lambda wav, c: "كيفاش نسقي",
                                        appel_gemini=lambda wav, consigne: "jamais appelé")
        self.assertEqual((texte, moteur), ("كيفاش نسقي", "whisper-derja"))

        def whisper_en_panne(wav, c):
            raise voix.VoixErreur("modèle absent")
        texte, moteur = voix.transcrire(b"RIFF" + b"\0" * 4000, cfg, whisper=whisper_en_panne,
                                        appel_gemini=lambda wav, consigne: "شنوة نزرع؟")
        self.assertEqual(moteur, "gemini")                       # secours

    def test_voix_gratuite_edge_si_pas_de_cle_azure(self):
        from unittest import mock
        from services.rag import voix
        with mock.patch.object(voix, "edge_tts_mp3", return_value=b"mp3-edge") as edge:
            self.assertEqual(voix.synthese("Aslema", {"edge": True, "voix": "ar-TN-HediNeural"}), (b"mp3-edge", "audio/mpeg"))
            edge.assert_called_once_with("Aslema", "ar-TN-HediNeural")
            # Azure en panne -> edge-tts prend le relais
            def http(url, data, entetes, timeout=30):
                raise voix.VoixErreur("Azure HTTP 401")
            cfg = {"azure_cle": "k", "azure_region": "westeurope", "edge": True}
            self.assertEqual(voix.synthese("Aslema", cfg, http=http), (b"mp3-edge", "audio/mpeg"))
        with self.assertRaises(voix.VoixErreur):
            voix.synthese("Aslema", {"edge": False})

    def test_accent_tunisien_lahgtna_puis_secours_hedi(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from services.rag import voix
        dossier = Path(tempfile.mkdtemp())
        cfg = {"lahgtna": True, "edge": True, "voix": "ar-TN-HediNeural", "reference": str(dossier / "ref.mp3")}
        vu = {}

        def faux_lahgtna(t, ref, ref_texte):
            vu.update(t=t, ref=ref, ref_texte=ref_texte)
            return b"RIFF-wav"
        with mock.patch.object(voix, "edge_tts_mp3", return_value=b"mp3-ref"):
            self.assertEqual(voix.lahgtna_tts("اليوم تسقي الزونة", cfg, appel=faux_lahgtna), b"RIFF-wav")
            self.assertTrue((dossier / "ref.mp3").exists())        # référence créée une fois avec Hedi
            self.assertEqual(vu["ref_texte"], voix.REFERENCE_TEXTE_DEFAUT)
            with mock.patch.object(voix, "lahgtna_tts", side_effect=voix.VoixErreur("Space occupé")):
                self.assertEqual(voix.synthese("Aslema", cfg), (b"mp3-ref", "audio/mpeg"))   # secours Hedi
            with mock.patch.object(voix, "lahgtna_tts", return_value=b"RIFF-wav"):
                self.assertEqual(voix.synthese("Aslema", cfg), (b"RIFF-wav", "audio/wav"))

    def test_arabizi_a_l_ecran_et_lettres_arabes_pour_la_voix(self):
        vu = {}

        def faux(cle, modele, prompt):
            vu["prompt"] = prompt
            return json.dumps({"reponse": "Lyoum ns9i el zone Z3 m3a 6 sbe7.", "a_dire": "اليوم نسقي الزونة زد ثلاثة",
                               "question": "Kifech ns9i?", "actions": []})
        r = assistant.repondre("كيفاش نسقي؟", PID, cfg=dict(CFG, cle="t", ecriture="arabizi"), appel=faux, voix=True)
        self.assertIn("3arbizi", vu["prompt"])
        self.assertEqual(r["reponse"], "Lyoum ns9i el zone Z3 m3a 6 sbe7.")
        self.assertEqual(r["a_dire"], "اليوم نسقي الزونة زد ثلاثة")
        self.assertEqual(r["question"], "Kifech ns9i?")
        # relecture 🔊 d'un message en 3arbizi : réécrit en lettres arabes avant la voix
        self.assertEqual(assistant.vers_lettres_arabes("Lyoum ns9i", dict(CFG, cle="t"),
                                                       appel=lambda c, m, p: '{"texte": "اليوم نسقي"}'), "اليوم نسقي")
        self.assertEqual(assistant.vers_lettres_arabes("اليوم نسقي", CFG), "اليوم نسقي")   # déjà en arabe

    def test_relire_sans_azure(self):
        r = self.client.post(reverse("core:chat_tts"), json.dumps({"text": "Aslema"}), content_type="application/json")
        self.assertIsNone(r.json()["audio"])                    # le navigateur lit avec sa voix arabe

    def test_consigne_vocale_dans_le_prompt(self):
        vu = {}

        def faux(cle, modele, prompt):
            vu["prompt"] = prompt
            return json.dumps({"reponse": "باهي", "actions": []})
        assistant.repondre("كيفاش نسقي؟", PID, cfg=dict(CFG, cle="t"), appel=faux, voix=True)
        self.assertIn("MODE VOCAL", vu["prompt"])
        assistant.repondre("kifech ns9i?", PID, cfg=dict(CFG, cle="t"), appel=faux)
        self.assertNotIn("MODE VOCAL", vu["prompt"])

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
