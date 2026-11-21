"""Expérience : erreur de l'IDW selon le nombre de points de relevé.

    python manage.py bloc1_experiment [--champs 150]

Pour chaque taille de parcelle et chaque nombre de points n :
  1. on génère des parcelles « vérité terrain » (diagnostics.synthetic) à 0.5–10 km de la source ;
  2. on place n points (diagnostics.sampling.disposition) et on simule les relevés (erreurs d'appareil) ;
  3. on interpole (diagnostics.idw) et on compare chaque case à la vérité.
Mesures : % de cases avec la bonne couleur, % de cases ROUGES manquées (danger), erreur Cd.
Sortie : fixtures/bloc1/experience_capteurs.json (courbe affichée dans l'interface).
"""
import json
import math
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

from diagnostics.couleur import couleur_case
from diagnostics.idw import interpoler_grille
from diagnostics.sampling import disposition, nb_points_recommande
from diagnostics.synthetic import generer_parcelle, mesurer

SORTIE = Path(settings.BASE_DIR) / "fixtures" / "bloc1" / "experience_capteurs.json"
TAILLES = [(30, 30), (50, 50), (100, 100), (220, 220), (450, 450)]  # 0,09 ha → 20 ha


def evaluer(w, l, n, champs, rng, taille=10):
    nl, nc = math.ceil(l / taille), math.ceil(w / taille)
    ok, total, rouges, rouges_manques, err_cd, err_cd_rel = 0, 0, 0, 0, [], []
    for k in range(champs):
        d = float(rng.uniform(0.5, 10))
        verite = generer_parcelle(nl, nc, taille, distance_km=d, cap=float(rng.uniform(0, 360)),
                                  seed=int(rng.integers(1e9)))
        pts = disposition(nl, nc, n)
        mesures = mesurer(verite, pts, rng)
        cases, _ = interpoler_grille(mesures, nl, nc, taille, puissance=2.0)
        for c in cases:
            li, co = c["ligne"], c["col"]
            vrai = couleur_case(verite["CE_dS_m"][li, co], verite["pH"][li, co],
                                verite["Cd_mg_kg"][li, co], verite["Pb_mg_kg"][li, co])
            pred = couleur_case(c["CE_dS_m"], c["pH"], c["Cd_mg_kg"], c["Pb_mg_kg"])
            total += 1
            ok += vrai == pred
            if vrai == "ROUGE":
                rouges += 1
                rouges_manques += pred != "ROUGE"
            vcd = verite["Cd_mg_kg"][li, co]
            err_cd.append(c["Cd_mg_kg"] - vcd)
            err_cd_rel.append(abs(c["Cd_mg_kg"] - vcd) / vcd)
    err_cd = np.array(err_cd)
    return {
        "n": n,
        "couleur_correcte_pct": round(100 * ok / total, 1),
        "rouges_manques_pct": round(100 * rouges_manques / rouges, 1) if rouges else 0.0,
        "cd_rmse": round(float(np.sqrt(np.mean(err_cd ** 2))), 2),
        "cd_erreur_relative_pct": round(100 * float(np.median(err_cd_rel)), 1),
    }


class Command(BaseCommand):
    help = "Courbe erreur IDW vs nombre de points de releve (justifie le plan de capteurs)."

    def add_arguments(self, parser):
        parser.add_argument("--champs", type=int, default=150, help="parcelles simulees par point de la courbe")
        parser.add_argument("--champs-grandes", type=int, default=30, help="idem pour les parcelles > 1 ha (plus lentes)")
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, champs, seed, **opts):
        champs_grandes = opts.get("champs_grandes", 30)
        rng = np.random.default_rng(seed)
        resultats = []
        for w, l in TAILLES:
            nl, nc = math.ceil(l / 10), math.ceil(w / 10)
            reco = nb_points_recommande(w, l)
            ns = sorted({n for n in [3, 4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 36, 45, 60, 80, 103, 140]
                         if n <= nl * nc} | {reco})
            courbe = []
            self.stdout.write(f"\nParcelle {w} x {l} m ({nl * nc} cases) - recommande : {reco} points")
            self.stdout.write("   n | couleur OK | rouges manques | Cd RMSE | Cd err. rel.")
            for n in ns:
                r = evaluer(w, l, n, champs if w * l <= 10_000 else champs_grandes, rng)
                courbe.append(r)
                mark = "  <- regle" if n == reco else ""
                self.stdout.write(f"{n:4d} | {r['couleur_correcte_pct']:9.1f}% | {r['rouges_manques_pct']:13.1f}% |"
                                  f" {r['cd_rmse']:7.2f} | {r['cd_erreur_relative_pct']:6.1f}%{mark}")
            resultats.append({"largeur_m": w, "longueur_m": l, "nb_cases": nl * nc,
                              "recommande": reco, "courbe": courbe})
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"champs_par_point": champs, "seed": seed, "tailles": resultats},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"\n-> {SORTIE}"))
