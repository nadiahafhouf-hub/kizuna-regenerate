"""Point d'entree pour REGEN : diagnostic JSON de la parcelle (grille de cases + zones) + photo reelle.

from services.irrigation_engine.parcelle import analyser_parcelle
res = analyser_parcelle(diagnostic, photo="drone.jpg",
                        calage={"mode": "coins", "coins_px": [[x,y] NO, NE, SE, SO]},
                        sortie="media/irrigation/GAB-001")
"""

import math
import json
from pathlib import Path

import numpy as np
import cv2

from .crops import (
    get_crop,
    culture_depuis_nom,
    sol_depuis_texture,
    climat_depuis_region,
    CLIMATS,
    ECE_SEUIL,
    ECE_MAX,
    MOIS,
    JOURS_MOIS,
)
from .image_analysis import Terrain
from . import vision as V

COULEURS = {
    "ROUGE": "#d73027",
    "ORANGE": "#fc8d59",
    "JAUNE": "#fee08b",
    "VERT": "#91cf60",
    "VERT_FONCE": "#1a9850",
    "GRIS": "#bdbdbd",
    "BLEU": "#4575b4",
}
SEUILS_METAUX = {
    "Cd_mg_kg": (1.0, 3.0),
    "Pb_mg_kg": (100.0, 300.0),
    "Zn_mg_kg": (200.0, 300.0),
    "Cu_mg_kg": (100.0, 140.0),
    "Ni_mg_kg": (50.0, 75.0),
    "Cr_mg_kg": (100.0, 150.0),
    "Hg_mg_kg": (1.0, 1.5),
}  # (vigilance, critique) - ordres de grandeur sols agricoles (UE 86/278)


def plantation_reguliere(rows):
    """Vraie plantation en rangs : au moins 2 rangs de 3 arbres ou plus, ecartement regulier."""
    pleins = sum(1 for r in rows.get("rows", []) if r["n"] >= 3)
    return pleins >= 2 and rows.get("cv_ecart", 0) < 0.5


def _hex(c):
    if not c:
        return "#bdbdbd"
    return c if str(c).startswith("#") else COULEURS.get(str(c).upper(), "#bdbdbd")


# =========================================================================== terrain issu d'une photo
class PhotoTerrain(Terrain):
    """Meme interface que Terrain (utilisee par Conception / diagnostic / dessins), construite a partir
    d'une photo reelle redressee et des zones definies par les cases du diagnostic."""

    def __init__(self, cfg, diag, photo=None, calage=None, ppm=None):
        self.cfg = cfg
        self.diag = diag
        self.warnings = []
        W, H = cfg["dimensions_m"]["largeur"], cfg["dimensions_m"]["longueur"]
        self.photo_info = {"fournie": bool(photo)}
        self.pipes_m = None
        if photo:
            rgb0, valid0, res = V.charger_photo(photo)
            calage = calage or {"mode": "ortho"}
            mode = calage.get("mode", "ortho")
            if mode == "coins":
                coins = calage["coins_px"]
            else:  # l'image couvre exactement la parcelle, nord en haut
                h0, w0 = rgb0.shape[:2]
                coins = [[0, 0], [w0 - 1, 0], [w0 - 1, h0 - 1], [0, h0 - 1]]
            nat_min, nat_max = V.resolution_native(coins, W, H)
            if mode != "coins" and res:
                if abs(1 / res - nat_min) / nat_min > 0.1:
                    self.warnings.append(
                        f"La resolution du GeoTIFF ({res*100:.0f} cm/px) ne correspond pas aux "
                        f"dimensions saisies ({100/nat_min:.0f} cm/px) : verifier largeur/longueur."
                    )
            if nat_max / max(nat_min, 1e-6) > 3:
                self.warnings.append(
                    "Photo tres oblique : la precision diminue loin de l'appareil. "
                    "Preferer une vue verticale (drone a 30-60 m, Google Earth)."
                )
            self.ppm = float(ppm or min(max(nat_min, 4.0), 25.0))
            rgb, valid, Hm = V.redresser(rgb0, valid0, coins, W, H, self.ppm)
            self._coins = [[float(a), float(b)] for a, b in coins]
            self.calage = calage
            self.rgb, self.valid = rgb, valid
            self.photo_info.update(
                mode_calage=mode,
                resolution_native_cm_px=round(100 / nat_min, 1),
                resolution_travail_cm_px=round(100 / self.ppm, 1),
                couverture_pct=round(100 * valid.mean(), 1),
            )
            if valid.mean() < 0.9:
                self.warnings.append(
                    f"La photo ne couvre que {valid.mean()*100:.0f}% de la parcelle."
                )
            if 100 / nat_min > 30:
                self.warnings.append(
                    f"Resolution {100/nat_min:.0f} cm/pixel : les arbres sont detectables mais pas les "
                    "jeunes plants ni les cultures basses. Ideal : 2-5 cm/pixel (drone)."
                )
            self._rgb0, self._valid0, self._Hm, self._nat = rgb0, valid0, Hm, nat_min
        else:
            self.ppm = float(ppm or 10.0)
            self.rgb = np.full((int(H * self.ppm), int(W * self.ppm), 3), 235, np.uint8)
            self.valid = np.ones(self.rgb.shape[:2], bool)
            self.warnings.append(
                "Aucune photo : la disposition existante n'est pas analysee. Le plan suppose une plantation "
                "aux ecartements recommandes ; l'economie annoncee est indicative."
            )
        self.h, self.w = self.rgb.shape[:2]
        self.ppm_x, self.ppm_y = self.w / W, self.h / H
        self.overlay_masks = {}
        self.excl_masks = []
        if not photo:
            self.calage = calage or {}

    def px_vers_m(self, pts):
        """Points cliques sur la photo d'origine -> metres dans la parcelle (via l'homographie)."""
        if not pts or not self.photo_info["fournie"]:
            return []
        q = cv2.perspectiveTransform(
            np.float32(pts).reshape(-1, 1, 2), self._Hm
        ).reshape(-1, 2)
        return [[float(x / self.ppm_x), float(y / self.ppm_y)] for x, y in q]

    def m_vers_px(self, pts):
        """Metres dans la parcelle -> pixels de la photo d'origine (homographie inverse)."""
        q = np.float32([[x * self.ppm_x, y * self.ppm_y] for x, y in pts]).reshape(
            -1, 1, 2
        )
        return cv2.perspectiveTransform(q, np.linalg.inv(self._Hm)).reshape(-1, 2)

    # ------------------------------------------------------------------ zones depuis les cases
    def _zones_depuis_cases(self):
        d = self.diag
        tc = float(d.get("taille_case_m", 10))
        self.zone_masks = []
        assigned = np.zeros((self.h, self.w), bool)
        for z in d.get("zones", []):
            m = np.zeros((self.h, self.w), bool)
            for li, co in z.get("cases", []):
                y0, y1 = int(round(li * tc * self.ppm_y)), int(
                    round((li + 1) * tc * self.ppm_y)
                )
                x0, x1 = int(round(co * tc * self.ppm_x)), int(
                    round((co + 1) * tc * self.ppm_x)
                )
                m[y0:y1, x0:x1] = True
            m &= ~assigned
            assigned |= m
            self.zone_masks.append(m)
        if (~assigned).mean() > 0.01:
            self.warnings.append(
                f"{(~assigned).mean()*100:.0f}% de la parcelle n'appartient a aucune zone du diagnostic : "
                "non irrigue dans le plan."
            )

    # ------------------------------------------------------------------ vision par zone
    def _vision(self):
        cfg = self.cfg
        zones = cfg["zones"]
        has_trees = any(
            get_crop(z["culture"])["type"] in ("arbre", "arbuste") for z in zones
        )
        dmax = max(
            [
                get_crop(z["culture"])["diam_couronne_m"]
                for z in zones
                if get_crop(z["culture"])["type"] in ("arbre", "arbuste")
            ]
            or [4.0]
        )
        self.seg = np.zeros((self.h, self.w), np.uint8)
        self.vision_info = {}
        if not self.photo_info["fournie"]:
            return
        seg_a, info_a = V.segmenter(
            self.rgb, self.valid, self.ppm, diam_max_m=1.6 * dmax, mode="arbres"
        )
        seg_b, info_b = V.segmenter(self.rgb, self.valid, self.ppm, mode="basse")
        self.vision_info = {"arbres": info_a, "basse": info_b}
        self.plants = []
        self.crown_labels = np.zeros((self.h, self.w), np.int32)
        cal = getattr(self, "calage", None) or {}
        source_ia = cal.get("plantes_source") == "ia"  # plantes trouvees par le modele de vision
        dpx = cal.get("plantes_diam_px") or []
        manuels = [(q, dpx[i] if i < len(dpx) else None)
                   for i, q in enumerate(self.px_vers_m(cal.get("plantes_px") or []))]
        W, H = self.cfg["dimensions_m"]["largeur"], self.cfg["dimensions_m"]["longueur"]
        manuels = [(q, d) for q, d in manuels if 0 <= q[0] <= W and 0 <= q[1] <= H]
        self.photo_info["plantes_ia" if source_ia else "plantes_cliquees"] = len(manuels)
        for zid, (z, m) in enumerate(zip(zones, self.zone_masks)):
            crop = get_crop(z["culture"])
            tree = crop["type"] in ("arbre", "arbuste")
            seg = seg_a if tree else seg_b
            self.seg[m] = seg[m]
            vz = m & self.valid
            n_valid = max(vz.sum(), 1)
            cover_main = float(((seg == (3 if tree else 2)) & vz).sum() / n_valid)
            cover_low = float(((seg_a == 2) & vz).sum() / n_valid) if tree else 0.0
            z["_couverture"] = cover_main
            z["_herbe"] = cover_low
            detect = cover_main > (0.02 if tree else 0.06)
            if z.get("plantee") is None:
                z["plantee"] = bool(detect)
                z["_plantee_auto"] = True
            elif z["plantee"] and not detect:
                self.warnings.append(
                    f"Zone {z['nom']} declaree plantee mais presque rien n'est visible sur la photo "
                    f"({cover_main*100:.1f}% de couverture) : jeunes plants ou mauvais calage ?"
                )
            elif not z["plantee"] and detect and cover_main > 0.08:
                self.warnings.append(
                    f"Zone {z['nom']} declaree nue mais {cover_main*100:.0f}% de vegetation "
                    f"{'haute' if tree else ''} visible sur la photo."
                )
            mz = [
                (q, d)
                for q, d in manuels
                if m[
                    min(int(q[1] * self.ppm_y), self.h - 1),
                    min(int(q[0] * self.ppm_x), self.w - 1),
                ]
            ]
            if (
                mz
            ):  # plantes cliquees par l'agriculteur ou trouvees par l'IA : elles remplacent la detection
                z["plantee"] = True
                z["_plantes_cliquees"] = len(mz)
                d_def = crop["diam_couronne_m"] * (
                    min(1.0, max(0.3, z["age_ans"] / 8)) if z.get("age_ans") else 1.0
                )
                for (x, y), d_px in mz:
                    # diametre mesure par l'IA (pixels de la photo d'origine -> metres)
                    d_m = float(np.clip(d_px / self._nat, 0.3, 15.0)) if d_px else d_def
                    self.plants.append({"x": x, "y": y, "zone": zid, "diam_m": d_m})
                continue
            if source_ia:
                if z.get("_plantee_auto"):  # l'IA n'a rien vu ici : zone non plantee
                    z["plantee"] = False
                    continue
                if z["plantee"]:
                    self.warnings.append(
                        f"Zone {z['nom']} declaree plantee mais l'IA n'y a trouve aucune plante : "
                        "detection classique utilisee pour cette zone."
                    )
            if not z["plantee"]:
                continue
            if tree:
                age = z.get("age_ans")
                esp = crop["ecart_plante_m"][0]
                if age:
                    esp *= min(1.0, max(0.4, age / 8))
                sub = seg_a.copy()
                sub[~m] = 0
                crowns, lab = V.couronnes(
                    sub, self.ppm, esp, diam_min_m=0.35 if age and age < 3 else 0.6
                )
                if len(crowns) >= 4 and not (age and age < 3):
                    # morceaux de couronnes voisines coupees par la limite de zone : pas des arbres de la zone
                    med = float(np.median([c["diam_m"] for c in crowns]))
                    garde = [c for c in crowns if c["diam_m"] >= 0.4 * med]
                    for c in crowns:
                        if c not in garde:
                            lab[lab == c["label"]] = 0
                    crowns = garde
                for c in crowns:
                    xm, ym = c["x_px"] / self.ppm_x, c["y_px"] / self.ppm_y
                    # ignorer les taches collees au bord de la zone de donnees (artefacts)
                    self.plants.append(
                        {"x": xm, "y": ym, "zone": zid, "diam_m": c["diam_m"]}
                    )
                self.crown_labels[lab > 0] = lab[lab > 0] + zid * 100000
            else:
                pr = V.rangs_par_projection(
                    seg_b == 2,
                    m & self.valid,
                    self.ppm,
                    crop["ecart_rang_m"][0] * 0.6,
                    crop["ecart_rang_m"][1] * 1.6,
                )
                if not pr or pr["nettete"] < 0.04:
                    self.warnings.append(
                        f"Zone {z['nom']} : rangs non identifiables sur la photo (culture couvrante, "
                        "ou resolution insuffisante) - disposition non evaluee."
                    )
                    continue
                self.plants.extend(
                    self._plants_le_long_des_rangs(zid, m, seg_b == 2, pr, crop)
                )
                z["_rangs_projection"] = pr

    def _plants_le_long_des_rangs(self, zid, m, veg, pr, crop):
        th = math.radians(pr["angle_deg"])
        u = np.array([math.cos(th), math.sin(th)])
        n = np.array([-u[1], u[0]])
        ys, xs = np.nonzero(m)
        P = np.column_stack([xs / self.ppm_x, ys / self.ppm_y])
        t, s = P @ n, P @ u
        vy, vx = np.nonzero(veg & m)
        tv = np.column_stack([vx / self.ppm_x, vy / self.ppm_y]) @ n
        period = pr["ecart_m"]
        # phase : maximise la vegetation sur les lignes
        best = max(
            np.arange(0, period, period / 20),
            key=lambda ph: np.sum(np.cos(2 * np.pi * (tv - ph) / period)),
        )
        sp = crop["ecart_opt"][1]
        out = []
        k0 = math.floor((t.min() - best) / period)
        for k in range(k0, k0 + int((t.max() - t.min()) / period) + 3):
            tk = best + k * period
            for sv in np.arange(s.min(), s.max(), sp):
                xy = sv * u + tk * n
                xi, yi = int(xy[0] * self.ppm_x), int(xy[1] * self.ppm_y)
                r = max(1, int(0.12 * self.ppm))
                if 0 <= xi < self.w and 0 <= yi < self.h and m[yi, xi]:
                    win = veg[max(0, yi - r) : yi + r + 1, max(0, xi - r) : xi + r + 1]
                    if win.mean() > 0.3:
                        out.append(
                            {
                                "x": float(xy[0]),
                                "y": float(xy[1]),
                                "zone": zid,
                                "diam_m": sp,
                                "estime": True,
                            }
                        )
        return out

    # ------------------------------------------------------------------ tuyaux existants
    def _tuyaux(self):
        if not self.photo_info["fournie"]:
            return
        segs = V.tuyaux(self._rgb0, self._valid0, self._nat)
        mask = np.zeros((self.h, self.w), np.uint8)
        if segs is None:
            self.photo_info["tuyaux"] = (
                "resolution insuffisante pour voir les tuyaux (< 4 cm/px requis)"
            )
        else:
            self.photo_info["tuyaux"] = f"{len(segs)} segments detectes"
            th = max(2, int(0.25 * self.ppm))
            for a, b in segs:
                p = cv2.perspectiveTransform(np.float32([[a, b]]), self._Hm)[0]
                cv2.line(
                    mask,
                    tuple(int(v) for v in p[0]),
                    tuple(int(v) for v in p[1]),
                    1,
                    th,
                )
        # irrigation declaree mais invisible : lignes supposees le long des rangs detectes
        for zid, z in enumerate(self.cfg["zones"]):
            irr = z.get("irrigation_actuelle", {})
            if (
                irr.get("type") in ("goutte_a_goutte", "enterre")
                and not (mask > 0)[self.zone_masks[zid]].any()
            ):
                pz = np.array(
                    [[p["x"], p["y"]] for p in self.plants if p["zone"] == zid]
                )
                if len(pz) >= 4:
                    rows = self.analyse_rows(pz)
                    if rows:
                        u, n = np.array(rows["u"]), np.array(rows["n"])
                        th = max(2, int(0.25 * self.ppm))
                        ys, xs = np.nonzero(self.zone_masks[zid])
                        P = np.column_stack([xs / self.ppm_x, ys / self.ppm_y])
                        smin, smax = (P @ u).min(), (P @ u).max()
                        for r in rows["rows"]:
                            a = (smin * u + r["t"] * n) * [self.ppm_x, self.ppm_y]
                            b = (smax * u + r["t"] * n) * [self.ppm_x, self.ppm_y]
                            line = np.zeros_like(mask)
                            cv2.line(
                                line,
                                (int(a[0]), int(a[1])),
                                (int(b[0]), int(b[1])),
                                1,
                                th,
                            )
                            mask |= line & self.zone_masks[zid].astype(np.uint8)
                        z["_lignes_supposees"] = True
        self.overlay_masks["irrigation"] = mask > 0

    # ------------------------------------------------------------------ run
    def run(self):
        self._zones_depuis_cases()
        self.plants = []
        self._vision()
        self._tuyaux()
        self.source = self._source_diag()
        area_px = self.ppm_x * self.ppm_y
        self.zones = []
        for zid, z in enumerate(self.cfg["zones"]):
            m = self.zone_masks[zid]
            pz = [p for p in self.plants if p["zone"] == zid]
            pts = np.array([[p["x"], p["y"]] for p in pz]) if pz else np.zeros((0, 2))
            rows = (
                self.analyse_rows(pts) if (z.get("plantee") and len(pz) >= 4) else None
            )
            if rows and not plantation_reguliere(rows):
                # arbres deja plantes mais epars (oliveraie traditionnelle) : pas de "rangs"
                # ni de "manquants" inventes, le reseau sera concu arbre par arbre
                rows = dict(rows, manquants=[], irreguliere=True)
            info = {
                "id": zid,
                "nom": z["nom"],
                "culture": z["culture"],
                "plantee": bool(z.get("plantee")),
                "surface_m2": float(m.sum() / area_px),
                "n_plantes": len(pz),
                "plantes": pz,
                "rangs": rows,
            }
            for k in (
                "interdire_aspersion",
                "lessivage_interdit",
                "facteur_dose",
                "ru_facteur",
            ):
                if k in z:
                    info[k] = z[k]
            ys, xs = np.nonzero(m)
            info["centre"] = (
                [float(xs.mean() / self.ppm_x), float(ys.mean() / self.ppm_y)]
                if len(xs)
                else None
            )
            irr_type = z.get("irrigation_actuelle", {}).get("type", "aucun")
            if (
                irr_type == "aspersion"
                and not (
                    self.overlay_masks.get("irrigation", np.zeros(1, bool)) & m
                ).any()
            ):
                n = len(pz)
                info["irrigation"] = {
                    "type": "aspersion",
                    "n_plantes_couvertes": n,
                    "couverture_plantes_pct": 100.0,
                    "surface_mouillee_m2": info["surface_m2"],
                    "hors_zone_m2": 0.0,
                    "commentaire": "Asperseurs non visibles : toute la zone est supposee arrosee.",
                }
            else:
                info["irrigation"] = self._analyse_irrigation(zid, z, pz, rows)
            if z.get("_lignes_supposees"):
                info["irrigation"]["commentaire"] = (
                    "Tuyaux non visibles sur la photo : une ligne par rang detecte est "
                    "supposee, sur toute la longueur de la zone."
                )
            self.zones.append(info)
        return self

    def _source_diag(self):
        sp = (getattr(self, "calage", None) or {}).get("source_px")
        if sp and self.photo_info["fournie"]:
            return self.px_vers_m([sp])[0]
        s = self.diag.get("source_eau") or {}
        tc = float(self.diag.get("taille_case_m", 10))
        if "x_m" in s:
            return [float(s["x_m"]), float(s["y_m"])]
        if "ligne" in s:
            return [(s["col"] + 0.5) * tc, (s["ligne"] + 0.5) * tc]
        if "lat" in s and "lon" in s:
            from .geo import lonlat_vers_m

            return list(lonlat_vers_m(self.diag["origine"], s["lon"], s["lat"]))
        self.warnings.append(
            "Source d'eau non indiquee ('source_eau' : ligne/col, x_m/y_m ou lat/lon) : "
            "coin nord-ouest suppose."
        )
        return [0.5, 0.5]


# =========================================================================== diagnostic -> configuration interne
def _sol_zone(diag, zone):
    tc = {(c["ligne"], c["col"]): c for c in diag.get("cases", [])}
    vals = [tc[tuple(x)] for x in zone.get("cases", []) if tuple(x) in tc]
    out = {"n_cases_mesurees": len(vals), "n_cases": len(zone.get("cases", []))}
    for k in (
        "CE_dS_m",
        "pH",
        "Cd_mg_kg",
        "Pb_mg_kg",
        "Zn_mg_kg",
        "Cu_mg_kg",
        "Ni_mg_kg",
        "Cr_mg_kg",
        "Hg_mg_kg",
    ):
        v = [c[k] for c in vals if c.get(k) is not None]
        if v:
            out[k] = {"moy": float(np.mean(v)), "max": float(np.max(v))}
    return out


def config_depuis_diagnostic(diag, options=None):
    """Transforme le JSON du diagnostic REGEN en configuration du moteur."""
    o = options or {}
    W, H = float(diag["largeur_m"]), float(diag["longueur_m"])
    clim = diag.get("climat") or climat_depuis_region(diag.get("region", ""))
    cfg = {
        "nom_projet": f"Parcelle {diag.get('parcelle_id', '')} - {diag.get('region', '')}",
        "dimensions_m": {"largeur": W, "longueur": H},
        "climat": clim if isinstance(clim, dict) else clim,
        "sol": sol_depuis_texture(diag.get("texture_sol", "limoneux")),
        "prix_eau_dt_m3": o.get("prix_eau_dt_m3", diag.get("prix_eau_dt_m3", 0.20)),
        "pompe": diag.get("pompe")
        or o.get("pompe")
        or {"debit_m3_h": 5, "pression_bar": 2.5, "heures_max_jour": 10},
        "zones": [],
        "zones_exclues": [],
        "avertissements_entree": [],
    }
    ce_eau = (diag.get("eau") or {}).get("CE_dS_m")
    if ce_eau:
        cfg["salinite_eau_dS_m"] = float(ce_eau)
    else:
        cfg["avertissements_entree"].append(
            "Salinite de l'eau d'irrigation inconnue ('eau': {'CE_dS_m': ...}) : "
            "aucune fraction de lessivage calculee. A Gabes l'eau des forages depasse "
            "souvent 3 dS/m - a mesurer."
        )
    sols = []
    for z in diag.get("zones", []):
        tr = z.get("traitement") or {}
        # culture : explicite > plante de traitement > recommandation de l'advisor
        nom_c = (
            z.get("culture")
            or (tr.get("plantes") or [None])[0]
            or (z.get("cultures_recommandees") or [None])[0]
        )
        if not nom_c:
            nom_c = "arbuste_generique"
            cfg["avertissements_entree"].append(
                f"Zone {z['id']} : aucune culture indiquee, arbuste generique suppose."
            )
        key, ok = culture_depuis_nom(nom_c)
        if not ok:
            cfg["avertissements_entree"].append(
                f"Zone {z['id']} : '{nom_c}' inconnue de la base, parametres generiques "
                "utilises (a completer dans crops.py)."
            )
        sol = _sol_zone(diag, z)
        sol["zone"] = z["id"]
        etat = z.get("etat") or diag.get("etat_parcelle")
        plantee = z.get("plantee")
        if plantee is None and etat:
            plantee = str(etat).lower().startswith("plant")
        zc = {
            "nom": z.get("nom") or z["id"] + (f" ({z.get('couleur','')})" if z.get("couleur") else ""),
            "id_regen": z["id"],
            "couleur": _hex(z.get("couleur")),
            "culture": key,
            "culture_nom_saisi": nom_c,
            "plantee": plantee,
            "irrigation_actuelle": z.get("irrigation_actuelle") or {"type": "aucun"},
        }
        for k in ("age_ans", "ecartement_m", "orientation_rangs"):
            if k in z:
                zc[k] = z[k]
        # ---- pollution / salinite -> contraintes d'irrigation
        niveau = "ok"
        for k, (vig, crit) in SEUILS_METAUX.items():
            if k in sol:
                if sol[k]["max"] >= crit:
                    niveau = "critique"
                elif sol[k]["max"] >= vig and niveau == "ok":
                    niveau = "vigilance"
        sol["niveau_metaux"] = niveau
        pollue = (
            niveau == "critique"
            or z.get("culture_alimentaire_autorisee") is False
            or str(z.get("couleur", "")).upper() == "ROUGE"
        )
        sol["pollue"] = pollue
        if pollue:
            zc["interdire_aspersion"] = True
            if niveau == "critique":
                zc["lessivage_interdit"] = (
                    True  # ne pas entrainer les metaux vers la nappe
                )
            if tr.get("strategie", "").startswith("phyto"):
                zc["facteur_dose"] = (
                    0.8  # couvert vivant, percolation minimale (100 % la 1ere annee)
                )
        if "biochar" in [a.lower() for a in tr.get("amendements", [])]:
            zc["ru_facteur"] = 1.15
        ce = sol.get("CE_dS_m", {}).get("moy")
        if ce is not None:
            seuil, mx = ECE_SEUIL.get(key, 2.0), ECE_MAX.get(key, 10.0)
            sol["perte_rendement_sel_pct"] = float(
                np.clip(100 * (ce - seuil) / (mx - seuil), 0, 100)
            )
        sol["culture"] = key
        sol["traitement"] = tr
        sol["mois_avant_sain"] = tr.get("mois_avant_sain")
        sols.append(sol)
        cfg["zones"].append(zc)
    cfg["_sols"] = sols
    return cfg


# =========================================================================== pipeline complet
def analyser_parcelle(
    diag, photo=None, calage=None, sortie="resultats_irrigation", options=None
):
    from .design import Conception
    from .diagnose import analyser
    from .drawing import plan_optimal, graphique_mensuel
    from .report import rapport_html, exports
    from .geo import geojson_plan
    from .dessin_photo import dessin_photo
    from .evenements import pompage

    if not isinstance(diag, dict):
        diag = json.loads(Path(diag).read_text(encoding="utf-8"))
    out = Path(sortie)
    out.mkdir(parents=True, exist_ok=True)
    cfg = config_depuis_diagnostic(diag, options)
    photo, calage, sat = _calage_satellite(diag, photo, calage, out, options)
    calage, det, av_ia = _detection_ia(photo, calage, options)
    T = PhotoTerrain(cfg, diag, photo, calage).run()
    T.warnings = cfg["avertissements_entree"] + (sat or {}).get("avertissements", []) + av_ia + T.warnings
    if det:
        T.photo_info["detection_ia"] = det["info"]
    if sat:
        T.photo_info["mode_calage"] = "satellite"
        T.photo_info["source_image"] = sat["source_image"]
    # terre deja plantee : pas de "nouvelle plantation" inventee dans les zones ou rien n'est vu
    # (seulement si au moins une zone est plantee, sinon il n'y aurait aucun reseau)
    if (options or {}).get("plantees_seulement") and any(z.get("plantee") for z in T.zones):
        cfg["plantees_seulement"] = True
    C = Conception(T).run()
    for zd in C.zones:
        if zd.get("non_plantee"):
            T.warnings.append(
                f"Zone {zd['nom']} : aucune plante detectee, pas de reseau propose "
                "(terre nue : voir l'etape Crops pour choisir quoi planter)."
            )
    res = analyser(cfg, T, C)
    _complements(res, cfg, T, C)
    imgs = {
        "existant": out / "1_photo_analysee.png",
        "plan": out / "2_plan_optimal.png",
        "mensuel": out / "3_besoins_mensuels.png",
    }
    dessin_photo(T, imgs["existant"])
    plan_optimal(
        T,
        C,
        imgs["plan"],
        titre=f"Plan d'irrigation optimal - {diag.get('parcelle_id','')}",
    )
    graphique_mensuel(res["bilan"], imgs["mensuel"])
    res["conseil_simple"] = conseil_simple(res, C)
    if T.photo_info["fournie"]:
        from .trace_photo import tracer_sur_photo

        imgs["trace"] = out / "4_trace_sur_photo.png"
        tracer_sur_photo(T, C, res, imgs["trace"])
    res["geojson"] = geojson_plan(diag, T, C)
    res["pompage"] = pompage(res, C)
    res["photo"] = T.photo_info
    res["vision"] = T.vision_info
    res["avertissements"] = T.warnings
    res["parcelle_id"] = diag.get("parcelle_id")
    res["date_mesure"] = diag.get("date_mesure")
    rapport_html(cfg, T, C, res, imgs, out / "rapport.html", extra_html=_html_sol(res))
    exports(res, C, out)
    (out / "plan.geojson").write_text(
        json.dumps(res["geojson"], ensure_ascii=False), encoding="utf-8"
    )
    res["fichiers"] = {k: str(v) for k, v in imgs.items()}
    res["fichiers"].update(
        rapport=str(out / "rapport.html"), geojson=str(out / "plan.geojson")
    )
    if sat:
        res["satellite"] = {k: v for k, v in sat.items() if k != "avertissements"}
    if det:
        res["detection_ia"] = det  # plantes_px / plantes_diam_px : a garder pour un recalcul sans IA
    res["_conception"] = C  # pour la generation des evenements (non serialise)
    return res


def _detection_ia(photo, calage, options):
    """Plantes detectees par un modele de vision (options["ia"] = {"cle", "modele"}), sauf si
    l'agriculteur a deja clique ses plantes. En cas d'echec : detection classique + avertissement."""
    ia = (options or {}).get("ia")
    if not (photo and ia and ia.get("cle")) or (calage or {}).get("plantes_px"):
        return calage, None, []
    from PIL import Image
    from .detection_ia import DetectionIAErreur, detecter_plantes

    calage = dict(calage or {"mode": "ortho"})
    coins = calage.get("coins_px")
    if not coins:  # image deja cadree sur la parcelle
        w, h = Image.open(photo).size
        coins = [[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]]
    try:
        det = detecter_plantes(photo, coins, ia["cle"], ia.get("modele") or "gemini-2.5-flash",
                               appel=ia.get("appel"))
    except DetectionIAErreur as e:
        return calage, None, [f"Detection IA indisponible ({e}) : detection classique utilisee."]
    calage.update(plantes_px=det["plantes_px"], plantes_diam_px=det["plantes_diam_px"], plantes_source="ia")
    return calage, det, []


def _calage_satellite(diag, photo, calage, out, options):
    """calage {"mode": "satellite"} : telecharge l'image (ou reprend celle deja enregistree, au
    recalcul) et la transforme en calage {"mode": "coins"} ordinaire pour le reste du moteur."""
    if not calage or calage.get("mode") != "satellite":
        return photo, calage, None
    from . import satellite as S

    extra = {k: calage[k] for k in ("source_px", "plantes_px", "plantes_diam_px", "plantes_source")
             if calage.get(k)}
    if photo and calage.get("coins_px"):  # image deja telechargee (recalcul) : pas de reseau
        si = calage.get("source_image") or {}
        sat = {"image": str(photo), "coins_px": calage["coins_px"], "source_image": si,
               "zoom": si.get("zoom"), "resolution_m_px": si.get("resolution_m_px"), "avertissements": []}
    else:
        conf = dict((options or {}).get("satellite") or {})
        sat = S.image_satellite(diag, out, zoom_force=calage.get("zoom"), **conf)
        sat["source_image"] = S.source_image(sat)
    return sat["image"], {"mode": "coins", "coins_px": sat["coins_px"], **extra}, sat


def _complements(res, cfg, T, C):
    """Recommandations propres a REGEN : pollution, salinite, adventices, traitement."""
    recos = res["recommandations"]
    prio = {"Haute": 0, "Moyenne": 1, "Basse": 2, "Info": 3}
    clim = cfg["climat"] if isinstance(cfg["climat"], dict) else CLIMATS[cfg["climat"]]
    res["sol_zones"] = cfg["_sols"]
    par_nom = {z["nom"]: z for z in res["zones"]}  # res["zones"] omet les zones sans reseau
    for zc, sol, zinfo in zip(cfg["zones"], cfg["_sols"], T.zones):
        zr = par_nom.get(zinfo["nom"])
        if zr is None:
            continue
        nom = zinfo["nom"]
        zr["sol"] = sol
        zr["couverture_photo_pct"] = round(100 * zc.get("_couverture", 0), 1)
        zr["herbe_photo_pct"] = round(100 * zc.get("_herbe", 0), 1)
        zr["plantee_auto"] = bool(zc.get("_plantee_auto"))
        if sol.get("pollue"):
            recos.append(
                {
                    "priorite": "Haute",
                    "zone": nom,
                    "titre": "Zone polluee : goutte-a-goutte uniquement, secteur isole",
                    "detail": (
                        "Pas d'aspersion (aerosols, ruissellement de terre contaminee vers les zones saines). "
                        "Vanne et porte-rampe dedies ; ne jamais faire passer l'eau de drainage de cette zone vers une zone cultivee."
                        + (
                            " Metaux "
                            + sol["niveau_metaux"]
                            + " : aucune fraction de lessivage pour ne pas entrainer "
                            "Cd/Pb vers la nappe."
                            if sol.get("niveau_metaux") != "ok"
                            else ""
                        )
                    ),
                    "gain_m3_an": 0,
                }
            )
        tr = sol.get("traitement") or {}
        if tr.get("strategie"):
            recos.append(
                {
                    "priorite": "Info",
                    "zone": nom,
                    "titre": f"Traitement {tr['strategie']} : programme d'irrigation adapte",
                    "detail": (
                        f"Plantes {', '.join(tr.get('plantes', []))}. Annee 1 : 100 % des besoins pour l'installation, "
                        "puis 80 % (couvert vivant, percolation minimale)."
                        + (
                            " Inoculer "
                            + ", ".join(tr.get("microbes", []))
                            + " au pied des plants, sous les goutteurs : "
                            "les mycorhizes augmentent le volume de sol explore et la tolerance au stress hydrique."
                            if tr.get("microbes")
                            else ""
                        )
                        + (
                            f" Biochar : reserve utile +15 % prise en compte (arrosages plus espaces)."
                            if zc.get("ru_facteur")
                            else ""
                        )
                        + (
                            f" Re-evaluer apres {tr['mois_avant_sain']} mois (zone saine -> culture alimentaire possible)."
                            if tr.get("mois_avant_sain")
                            else ""
                        )
                    ),
                    "gain_m3_an": 0,
                }
            )
        if sol.get("niveau_metaux") == "vigilance" and not sol.get("pollue"):
            recos.append(
                {
                    "priorite": "Moyenne",
                    "zone": nom,
                    "titre": "Metaux proches des seuils : surveiller",
                    "detail": "Teneurs en metaux au-dessus du seuil de vigilance : eviter l'aspersion sur les "
                    "parties consommees, analyser les fruits/feuilles, re-mesurer le sol chaque annee.",
                    "gain_m3_an": 0,
                }
            )
        pr = sol.get("perte_rendement_sel_pct")
        if pr is not None and pr > 10:
            recos.append(
                {
                    "priorite": "Haute" if pr > 30 else "Moyenne",
                    "zone": nom,
                    "titre": f"Salinite du sol trop forte pour {get_crop(zinfo['culture'])['nom']} (~{pr:.0f} % de perte)",
                    "detail": (
                        f"CE du sol {sol['CE_dS_m']['moy']:.1f} dS/m pour un seuil de {ECE_SEUIL.get(zinfo['culture'], 2)} dS/m. "
                        "Irriguer cette culture ici gaspille de l'eau pour un faible rendement : choisir une culture "
                        "tolerante (orge, palmier, olivier, grenadier, atriplex) ou dessaler d'abord."
                    ),
                    "gain_m3_an": 0,
                }
            )
        herbe = zc.get("_herbe", 0)
        if herbe > 0.15 and get_crop(zinfo["culture"])["type"] in ("arbre", "arbuste"):
            # transpiration des adventices sur la surface irriguee (mois irrigues), Kc herbe ~0.6
            irr_frac = (
                1.0
                if zinfo["irrigation"]["type"] in ("gravitaire", "aspersion")
                else 0.35
            )
            m3 = (
                sum(
                    clim["et0"][m] * 0.6 * JOURS_MOIS[m]
                    for m in range(12)
                    if get_crop(zinfo["culture"])["kc"][m] > 0
                )
                / 1000
                * zinfo["surface_m2"]
                * herbe
                * irr_frac
                * 0.5
            )
            recos.append(
                {
                    "priorite": "Moyenne",
                    "zone": nom,
                    "titre": f"Adventices / herbe sur {herbe*100:.0f}% du sol (vu sur la photo)",
                    "detail": "L'herbe entre les arbres consomme l'eau d'irrigation. Desherbage mecanique de la bande "
                    "irriguee au printemps ou paillage ; garder l'herbe seulement hors de la zone humide.",
                    "gain_m3_an": float(m3),
                }
            )
    recos.sort(key=lambda r: (prio[r["priorite"]], -r["gain_m3_an"]))


def _html_sol(res):
    from html import escape

    h = [
        "<h2>0. Sol, pollution et photo</h2><table><tr><th>Zone</th><th>Culture / traitement</th><th>CE sol (dS/m)</th>"
        "<th>pH</th><th>Cd max</th><th>Pb max</th><th>Metaux</th><th>Perte sel</th><th>Couvert photo</th><th>Herbe</th></tr>"
    ]
    for z in res["zones"]:
        s = z.get("sol", {})
        g = lambda k: f"{s[k]['moy']:.1f}" if k in s else "-"
        gm = lambda k: f"{s[k]['max']:.1f}" if k in s else "-"
        tr = (s.get("traitement") or {}).get("strategie", "")
        h.append(
            f"<tr><td><b>{escape(z['nom'])}</b></td><td>{escape(z['culture'])}{' - ' + escape(tr) if tr else ''}</td>"
            f"<td class='n'>{g('CE_dS_m')}</td><td class='n'>{g('pH')}</td><td class='n'>{gm('Cd_mg_kg')}</td>"
            f"<td class='n'>{gm('Pb_mg_kg')}</td><td>{s.get('niveau_metaux','-')}{' (polluee)' if s.get('pollue') else ''}</td>"
            f"<td class='n'>{s.get('perte_rendement_sel_pct', 0):.0f} %</td>"
            f"<td class='n'>{z.get('couverture_photo_pct', 0):.0f} %{' (auto)' if z.get('plantee_auto') else ''}</td>"
            f"<td class='n'>{z.get('herbe_photo_pct', 0):.0f} %</td></tr>"
        )
    p = res.get("photo", {})
    h.append("</table>")
    if p.get("fournie"):
        h.append(
            f"<p class='small'>Photo : calage '{p.get('mode_calage')}', resolution d'origine {p.get('resolution_native_cm_px')} cm/px, "
            f"analyse a {p.get('resolution_travail_cm_px')} cm/px, couverture {p.get('couverture_pct')} %. "
            f"Tuyaux : {escape(str(p.get('tuyaux', '-')))}.</p>"
        )
    if p.get("source_image"):
        from .satellite import legende_source

        h.append(f"<p class='small'>{escape(legende_source(p['source_image']))}</p>")
    pp = res.get("pompage", {})
    if pp:
        h.append(
            f"<p>Pompage : {pp['heures_pointe_j']:.1f} h/jour au mois de pointe, {pp['kwh_an']:,.0f} kWh/an estimes "
            f"(HMT {pp['hmt_m']:.0f} m, rendement 60 %).</p>"
        )
    return "".join(h)


# =========================================================================== petite parcelle
def diagnostic_petite_parcelle(
    largeur_m,
    longueur_m,
    culture,
    region="Gabes",
    texture_sol="limoneux",
    irrigation="aucun",
    age_ans=None,
    ce_eau=None,
    pompe=None,
    nom="PETITE",
    origine=None,
    prix_eau_dt_m3=0.2,
):
    """Diagnostic minimal pour un petit agriculteur : une seule zone, deja plantee, sans analyse de sol."""
    W, H = float(largeur_m), float(longueur_m)
    tc = max(W, H)
    z = {
        "id": "P1",
        "nom": "Parcelle",
        "couleur": "VERT",
        "cases": [[0, 0]],
        "surface_m2": W * H,
        "culture": culture,
        "plantee": True,
        "culture_alimentaire_autorisee": True,
        "irrigation_actuelle": {"type": irrigation},
    }
    if age_ans:
        z["age_ans"] = int(age_ans)
    d = {
        "parcelle_id": nom,
        "region": region,
        "origine": origine or {"lat": 0, "lon": 0, "point": "coin_nord_ouest"},
        "largeur_m": W,
        "longueur_m": H,
        "taille_case_m": tc,
        "texture_sol": texture_sol,
        "cases": [],
        "zones": [z],
        "prix_eau_dt_m3": prix_eau_dt_m3,
        "pompe": pompe
        or {"debit_m3_h": 2.0, "pression_bar": 1.5, "heures_max_jour": 8},
    }
    if ce_eau:
        d["eau"] = {"CE_dS_m": float(ce_eau)}
    return d


def conseil_simple(res, C):
    """Resume en langage simple, par zone : quoi installer et combien arroser (mois de pointe et mois en cours)."""
    import datetime as dt

    m_now = dt.date.today().month - 1
    out = []
    for z, dz in zip(res["zones"], [c for c in C.zones if not c.get("vide")]):
        c = z["conception"]
        prog = z.get("programme") or []
        peak = (
            max(range(12), key=lambda m: prog[m]["l_plante_j"] if prog else 0)
            if prog
            else None
        )

        def ligne(m):
            if not prog or not prog[m]["intervalle_j"]:
                return None
            p = prog[m]
            return {
                "mois": MOIS[m],
                "litres_plante_jour": round(p["l_plante_j"], 1),
                "tous_les_jours": p["intervalle_j"],
                "duree_min": int(round(p["duree_min"])),
            }

        out.append(
            {
                "zone": z["nom"],
                "culture": z["culture"],
                "n_plantes": c.get("n_plantes_total"),
                "a_replanter": z.get("n_plantes_a_planter", 0),
                "goutteurs_par_plante": round(c.get("goutteurs_par_plante") or 0, 1),
                "debit_goutteur_l_h": c.get("debit_goutteur_l_h"),
                "lignes_par_rang": c.get("lignes_par_rang"),
                "longueur_rampes_m": round(
                    sum(l["L"] for l in dz.get("rampes", [])), 1
                ),
                "maintenant": ligne(m_now),
                "pointe": ligne(peak) if peak is not None else None,
            }
        )
    return out
