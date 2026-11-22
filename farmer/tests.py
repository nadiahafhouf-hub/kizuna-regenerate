from django.test import TestCase
from django.urls import reverse


class VueFarmerTests(TestCase):
    """La vue Farmer réutilise la logique existante : chaque page répond, et les actions
    postées depuis /farm/ y reviennent (sans redirection ouverte vers un autre site)."""

    PID = "GAB-001"

    def test_pages_repondent(self):
        self.assertEqual(self.client.get(reverse("farmer:home")).status_code, 200)
        for page in ("water", "soil", "plants", "sun", "certificate"):
            with self.subTest(page=page):
                r = self.client.get(reverse(f"farmer:{page}", args=[self.PID]))
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, reverse({"water": "irrigation:index", "soil": "diagnostics:index",
                                                "plants": "advisor:index", "sun": "energy:index",
                                                "certificate": "passport:index"}[page], args=[self.PID]))

    def test_parcelle_inconnue_404(self):
        self.assertEqual(self.client.get(reverse("farmer:water", args=["NOPE-999"])).status_code, 404)

    def test_action_irrigation_revient_a_la_vue_farmer(self):
        self.client.get(reverse("farmer:water", args=[self.PID]))   # crée le planning (comme la page experte)
        ici = reverse("farmer:water", args=[self.PID])
        r = self.client.post(reverse("irrigation:action", args=[self.PID, "valider"]), {"next": ici})
        self.assertRedirects(r, ici, fetch_redirect_response=False)
        from irrigation.logic import plan_actif
        self.assertEqual(plan_actif(self.PID).statut, "VALIDE")

    def test_next_externe_ignore(self):
        r = self.client.post(reverse("irrigation:action", args=[self.PID, "valider"]), {"next": "https://evil.example/farm/"})
        self.assertRedirects(r, reverse("irrigation:index", args=[self.PID]), fetch_redirect_response=False)

    def test_lien_vue_farmer_sur_la_vue_experte(self):
        r = self.client.get(reverse("irrigation:index", args=[self.PID]))
        self.assertContains(r, reverse("farmer:water", args=[self.PID]))
