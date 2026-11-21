"""Analyse de l'image du terrain : zones colorees, plantes, lignes / asperseurs d'irrigation."""

import math
import numpy as np
import cv2
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage.morphology import skeletonize

from .crops import get_crop, SOLS


def hex_to_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.uint8)


def _lab(rgb_img):
    return cv2.cvtColor(rgb_img, cv2.COLOR_RGB2LAB).astype(np.float32)


def load_rgb(path):
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Image introuvable : {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


class Terrain:
    """Resultat de l'analyse d'image, en metres."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.rgb = load_rgb(cfg["image"])
        self.zone_rgb = (
            load_rgb(cfg["image_zones"]) if cfg.get("image_zones") else self.rgb
        )
        if self.zone_rgb.shape[:2] != self.rgb.shape[:2]:
            self.zone_rgb = cv2.resize(
                self.zone_rgb,
                (self.rgb.shape[1], self.rgb.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        self.h, self.w = self.rgb.shape[:2]
        dim = cfg["dimensions_m"]
        self.ppm_x = self.w / dim["largeur"]
        self.ppm_y = self.h / dim["longueur"]
        self.ppm = (self.ppm_x + self.ppm_y) / 2
        self.warnings = []
        if abs(self.ppm_x - self.ppm_y) / self.ppm > 0.03:
            self.warnings.append(
                f"Echelle differente en X ({self.ppm_x:.2f} px/m) et en Y ({self.ppm_y:.2f} px/m) : "
                "l'image est deformee ou les dimensions sont inversees. L'echelle moyenne est utilisee."
            )
        self.tol = cfg.get("tolerance_couleur", 35)

    # ------------------------------------------------------------------ couleurs
    def _classify(self):
        cfg = self.cfg
        classes = []  # (label_name, rgb, kind, index)
        for i, z in enumerate(cfg["zones"]):
            classes.append(("zone", hex_to_rgb(z["couleur"]), i))
        for i, z in enumerate(cfg.get("zones_exclues", [])):
            classes.append(("exclue", hex_to_rgb(z["couleur"]), i))
        overlay = []
        if cfg.get("mode_plantes", "couleur") == "couleur" and cfg.get(
            "couleur_plantes"
        ):
            overlay.append(("plante", hex_to_rgb(cfg["couleur_plantes"]), 0))
        if cfg.get("couleur_irrigation"):
            overlay.append(("irrigation", hex_to_rgb(cfg["couleur_irrigation"]), 0))
        src = cfg.get("source_eau", {})
        if src.get("couleur"):
            overlay.append(("source", hex_to_rgb(src["couleur"]), 0))

        def nearest(img, cls):
            lab = _lab(img)
            ref = _lab(np.array([[c[1] for c in cls]], dtype=np.uint8))[0]
            d = np.stack([np.linalg.norm(lab - r, axis=2) for r in ref], axis=0)
            idx = d.argmin(0)
            ok = d.min(0) < self.tol
            return idx, ok

        # zones (sur l'image des zones)
        idx, ok = nearest(self.zone_rgb, classes + overlay)
        n_base = len(classes)
        base = np.zeros((self.h, self.w), np.int32)  # 0 = non classe ; k+1 = classe k
        is_base = ok & (idx < n_base)
        base[is_base] = idx[is_base] + 1
        # overlays (sur l'image principale)
        if overlay:
            oidx, ook = nearest(self.rgb, overlay)
            self.overlay_masks = {
                o[0]: (ook & (oidx == k)) for k, o in enumerate(overlay)
            }
        else:
            self.overlay_masks = {}
        self.unclassified_pct = 100.0 * float((~ok).sum()) / ok.size
        if self.unclassified_pct > 10:
            self.warnings.append(
                f"{self.unclassified_pct:.0f}% des pixels ne correspondent a aucune couleur de la legende : "
                "verifiez les couleurs ou augmentez 'tolerance_couleur'."
            )
        # remplir les pixels non-zones (plantes, lignes, inconnus) par la zone la plus proche
        if (base == 0).any() and (base > 0).any():
            _, (iy, ix) = ndimage.distance_transform_edt(base == 0, return_indices=True)
            base = base[iy, ix]
        self.classes = classes
        self.base = base

        self.zone_masks = []
        for k, c in enumerate(classes):
            if c[0] == "zone":
                m = base == (k + 1)
                m = (
                    cv2.morphologyEx(
                        m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
                    )
                    > 0
                )
                self.zone_masks.append(m)
        self.excl_masks = [
            base == (k + 1) for k, c in enumerate(classes) if c[0] == "exclue"
        ]

    # ------------------------------------------------------------------ plantes
    def _detect_plants(self):
        cfg = self.cfg
        planted_any = np.zeros((self.h, self.w), bool)
        for z, m in zip(cfg["zones"], self.zone_masks):
            if z.get("plantee", False):
                planted_any |= m
        if cfg.get("mode_plantes", "couleur") == "vegetation":
            f = self.rgb.astype(np.float32) / 255.0
            s = f.sum(2) + 1e-6
            r, g, b = f[..., 0] / s, f[..., 1] / s, f[..., 2] / s
            exg = 2 * g - r - b
            vals = exg[planted_any]
            if vals.size == 0:
                mask = np.zeros_like(planted_any)
            else:
                u8 = np.clip(
                    (exg - vals.min()) / (np.ptp(vals) + 1e-6) * 255, 0, 255
                ).astype(np.uint8)
                thr, _ = cv2.threshold(
                    u8[planted_any], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )
                mask = (u8 > thr) & planted_any
        else:
            mask = (
                self.overlay_masks.get("plante", np.zeros_like(planted_any))
                & planted_any
            )
        raw = mask.astype(bool)
        mask = cv2.morphologyEx(
            raw.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
        )
        # une ligne d'irrigation dessinee par-dessus une plante la coupe en deux : on recolle
        # (pixels de ligne ou de plante situes a l'interieur de la fermeture morphologique des plantes)
        irr = self.overlay_masks.get("irrigation")
        if irr is not None and irr.any():
            k = max(3, int(0.4 * self.ppm)) | 1
            ker = np.ones((k, k), np.uint8)
            closed = cv2.erode(cv2.dilate(mask, ker), ker) > 0
            mask = ((mask > 0) | (closed & (irr | raw) & planted_any)).astype(np.uint8)
        n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
        # regrouper les taches par zone (la taille typique d'une plante depend de la culture)
        by_zone = {}
        for i in range(1, n):
            xi = int(min(max(round(cents[i][0]), 0), self.w - 1))
            yi = int(min(max(round(cents[i][1]), 0), self.h - 1))
            zid = next((k for k, m in enumerate(self.zone_masks) if m[yi, xi]), None)
            if zid is None or not cfg["zones"][zid].get("plantee", False):
                continue
            by_zone.setdefault(zid, []).append(i)
        self.plants = []
        for zid, comps in by_zone.items():
            areas = np.array([stats[i, cv2.CC_STAT_AREA] for i in comps])
            med = float(np.median(areas))
            min_area = max(3, 0.15 * med)
            for i, a in zip(comps, areas):
                if a < min_area:
                    continue
                k = int(round(a / med)) if a > 2.2 * med else 1
                k = min(k, 50)
                if k > 1:  # couronnes qui se touchent : separation par k-means
                    ys, xs = np.nonzero(lab == i)
                    pts = np.column_stack([xs, ys]).astype(np.float32)
                    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
                    _, _, ctr = cv2.kmeans(pts, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
                    found = [(cx, cy, a / k) for cx, cy in ctr]
                else:
                    found = [(cents[i][0], cents[i][1], a)]
                for x, y, ar in found:
                    self.plants.append(
                        {
                            "x": x / self.ppm_x,
                            "y": y / self.ppm_y,
                            "zone": zid,
                            "diam_m": 2 * math.sqrt(ar / math.pi) / self.ppm,
                        }
                    )

    # ------------------------------------------------------------------ rangs
    @staticmethod
    def analyse_rows(pts):
        """pts : (n,2) en metres. Retourne orientation, rangs, ecartements, trous."""
        n = len(pts)
        if n < 4:
            return None
        tree = cKDTree(pts)
        d, j = tree.query(pts, k=2)
        nn = d[:, 1]
        vec = pts[j[:, 1]] - pts
        ang = np.degrees(np.arctan2(vec[:, 1], vec[:, 0])) % 180
        hist, edges = np.histogram(ang, bins=36, range=(0, 180))
        hist = hist + np.roll(hist, 1) + np.roll(hist, -1)
        b = int(hist.argmax())
        center = (edges[b] + edges[b + 1]) / 2
        sel = np.abs(((ang - center + 90) % 180) - 90) < 10
        theta = (
            math.radians(center + np.mean(((ang[sel] - center + 90) % 180) - 90))
            if sel.any()
            else math.radians(center)
        )
        u = np.array([math.cos(theta), math.sin(theta)])
        nrm = np.array([-u[1], u[0]])
        t = pts @ nrm
        s = pts @ u
        nn_med = float(np.median(nn))

        def cluster(t):
            order = np.argsort(t)
            rows, cur = [], [order[0]]
            for a, bb in zip(order[:-1], order[1:]):
                if t[bb] - t[a] > 0.5 * nn_med:
                    rows.append(cur)
                    cur = []
                cur.append(bb)
            rows.append(cur)
            return rows

        rows = cluster(t)
        # affinage de l'orientation : pente commune des rangs (moindres carres groupes)
        for _ in range(3):
            num = den = 0.0
            for r in rows:
                if len(r) < 2:
                    continue
                ss, tt = s[r] - s[r].mean(), t[r] - t[r].mean()
                num += float(ss @ tt)
                den += float(ss @ ss)
            if den <= 0:
                break
            theta += math.atan(num / den)
            u = np.array([math.cos(theta), math.sin(theta)])
            nrm = np.array([-u[1], u[0]])
            t, s = pts @ nrm, pts @ u
            rows = cluster(t)
        row_t = np.array([np.mean(t[r]) for r in rows])
        row_sp = float(np.median(np.diff(row_t))) if len(rows) > 1 else float("nan")
        in_row, gaps, dev, row_info = [], [], [], []
        for r in rows:
            r = np.array(r)
            ss = np.sort(s[r])
            dev.extend(list(t[r] - np.mean(t[r])))
            if len(ss) > 1:
                in_row.extend(list(np.diff(ss)))
            row_info.append(
                {
                    "t": float(np.mean(t[r])),
                    "s_min": float(ss[0]),
                    "s_max": float(ss[-1]),
                    "n": int(len(r)),
                    "idx": [int(i) for i in r],
                }
            )
        in_row = np.array(in_row) if in_row else np.array([nn_med])
        pl_sp = float(np.median(in_row))
        missing = []
        for ri in row_info:
            r = np.array(ri["idx"])
            ss = np.sort(s[r])
            for a, bb in zip(ss[:-1], ss[1:]):
                g = bb - a
                if g > 1.6 * pl_sp:
                    k = int(round(g / pl_sp)) - 1
                    for q in range(1, k + 1):
                        sv = a + q * g / (k + 1)
                        missing.append((sv * u + ri["t"] * nrm).tolist())
        cv = float(np.std(in_row) / np.mean(in_row)) if len(in_row) > 1 else 0.0
        cv = min(cv, 3.0)
        regular = in_row[in_row < 1.6 * pl_sp]
        cv_reg = float(np.std(regular) / np.mean(regular)) if len(regular) > 1 else 0.0
        return {
            "theta_deg": math.degrees(theta) % 180,
            "u": u.tolist(),
            "n": nrm.tolist(),
            "rows": row_info,
            "n_rangs": len(rows),
            "ecart_rang_m": row_sp,
            "ecart_plante_m": pl_sp,
            "cv_ecart": cv_reg,
            "ecart_alignement_m": float(np.std(dev)),
            "manquants": missing,
            "nn_med": nn_med,
        }

    # ------------------------------------------------------------------ irrigation
    def _analyse_irrigation(self, zid, zone, plants_z, rows):
        irr_cfg = zone.get("irrigation_actuelle", {"type": "aucun"})
        typ = irr_cfg.get("type", "aucun")
        crop = get_crop(zone["culture"])
        sol = SOLS[self.cfg.get("sol", "limoneux")]
        zmask = self.zone_masks[zid]
        imask = self.overlay_masks.get("irrigation", np.zeros_like(zmask))
        # pixels d'irrigation dans la zone (dilatation legere pour les lignes en bord)
        zdil = cv2.dilate(zmask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        im = imask & zdil
        res = {"type": typ, "n_plantes_couvertes": 0, "couverture_plantes_pct": 0.0}
        n_pl = len(plants_z)
        if typ == "gravitaire":
            res.update(
                couverture_plantes_pct=100.0 if n_pl else 0.0,
                n_plantes_couvertes=n_pl,
                surface_mouillee_m2=zmask.sum() / (self.ppm_x * self.ppm_y),
                commentaire="Toute la surface est inondee, y compris le sol entre les plantes.",
            )
            return res
        if typ == "aucun" or not im.any():
            if typ not in ("aucun",):
                res["commentaire"] = (
                    "Aucun element d'irrigation detecte dans la zone sur l'image."
                )
            return res
        if typ == "aspersion":
            n, lab, st, ce = cv2.connectedComponentsWithStats(im.astype(np.uint8))
            heads = [
                (ce[i][0] / self.ppm_x, ce[i][1] / self.ppm_y)
                for i in range(1, n)
                if st[i, cv2.CC_STAT_AREA] >= 3
            ]
            R = irr_cfg.get("rayon_m", 10.0)
            cover = np.zeros((self.h, self.w), np.uint8)
            for hx, hy in heads:
                cv2.circle(
                    cover,
                    (int(hx * self.ppm_x), int(hy * self.ppm_y)),
                    int(R * self.ppm),
                    1,
                    -1,
                )
            cov = cover > 0
            area_px = self.ppm_x * self.ppm_y
            covered_pl = sum(
                1
                for p in plants_z
                if cov[
                    min(int(p["y"] * self.ppm_y), self.h - 1),
                    min(int(p["x"] * self.ppm_x), self.w - 1),
                ]
            )
            res.update(
                asperseurs=[list(h) for h in heads],
                rayon_m=R,
                couverture_zone_pct=100.0 * (cov & zmask).sum() / max(zmask.sum(), 1),
                hors_zone_m2=float((cov & ~zmask).sum() / area_px),
                surface_mouillee_m2=float(cov.sum() / area_px),
                n_plantes_couvertes=covered_pl,
                couverture_plantes_pct=100.0 * covered_pl / n_pl if n_pl else 0.0,
            )
            return res
        # goutte-a-goutte : lignes
        sk = skeletonize(im)
        length_m = float(sk.sum() / self.ppm)
        dist_px = ndimage.distance_transform_edt(~im)
        wet_r = sol["diam_mouille_m"] / 2
        thr = max(wet_r + 0.3, 0.4 * crop["diam_couronne_m"])
        covered, plant_dist = [], []
        for p in plants_z:
            xi = min(int(p["x"] * self.ppm_x), self.w - 1)
            yi = min(int(p["y"] * self.ppm_y), self.h - 1)
            dm = dist_px[yi, xi] / self.ppm
            plant_dist.append(dm)
            covered.append(dm <= thr)
        # longueur de ligne loin de toute plante (arrose du sol nu)
        ys, xs = np.nonzero(sk)
        useless = 0.0
        if len(xs) and n_pl:
            pts_m = np.column_stack([xs / self.ppm_x, ys / self.ppm_y])
            tree = cKDTree(np.array([[p["x"], p["y"]] for p in plants_z]))
            dd, _ = tree.query(pts_m)
            exp_sp = rows["ecart_plante_m"] if rows else crop["ecart_opt"][1]
            pp = np.array([[p["x"], p["y"]] for p in plants_z])
            kq = min(4, len(pp))
            _, jj = tree.query(pts_m, k=kq)
            jj = jj.reshape(len(pts_m), -1)
            if rows:
                u = np.array(rows["u"])
                nv = np.array(rows["n"])
            else:
                u = np.array([1.0, 0.0])
                nv = np.array([0.0, 1.0])
            useful = np.zeros(len(pts_m), bool)
            for c in range(jj.shape[1]):
                dv = pts_m - pp[jj[:, c]]
                if rows:
                    ok = (np.abs(dv @ nv) <= thr) & (np.abs(dv @ u) <= exp_sp / 2 + 0.5)
                else:
                    ok = np.hypot(dv[:, 0], dv[:, 1]) <= max(thr, 0.75 * exp_sp)
                useful |= ok
            far = ~useful
            useless = float(far.sum() / self.ppm)
            self._useless_px = getattr(self, "_useless_px", [])
            self._useless_px.append(np.column_stack([xs[far], ys[far]]))
        # orientation des lignes (PCA par composante)
        n, lab = cv2.connectedComponents(sk.astype(np.uint8))
        angs, wts = [], []
        for i in range(1, n):
            yy, xx = np.nonzero(lab == i)
            if len(xx) < 5:
                continue
            c = np.cov(np.vstack([xx / self.ppm_x, yy / self.ppm_y]))
            ev, evec = np.linalg.eigh(c)
            v = evec[:, -1]
            angs.append(math.degrees(math.atan2(v[1], v[0])) % 180)
            wts.append(len(xx))
        line_ang = None
        if angs:
            a2 = np.radians(np.array(angs) * 2)
            line_ang = (
                math.degrees(
                    math.atan2(
                        np.average(np.sin(a2), weights=wts),
                        np.average(np.cos(a2), weights=wts),
                    )
                )
                / 2
            ) % 180
        res.update(
            longueur_lignes_m=length_m,
            n_lignes=len(angs),
            orientation_lignes_deg=line_ang,
            longueur_inutile_m=useless,
            part_inutile_pct=100.0 * useless / length_m if length_m else 0.0,
            seuil_couverture_m=thr,
            n_plantes_couvertes=int(sum(covered)),
            couverture_plantes_pct=100.0 * sum(covered) / n_pl if n_pl else 0.0,
            plantes_couvertes=[bool(c) for c in covered],
            distance_moy_ligne_m=float(np.mean(plant_dist)) if plant_dist else None,
        )
        if rows and line_ang is not None:
            diff = abs(((line_ang - rows["theta_deg"]) + 90) % 180 - 90)
            res["ecart_angle_rangs_deg"] = diff
        return res

    # ------------------------------------------------------------------ source
    def _source(self):
        src = self.cfg.get("source_eau", {})
        if "x_m" in src and "y_m" in src:
            return [float(src["x_m"]), float(src["y_m"])]
        m = self.overlay_masks.get("source")
        if m is not None and m.any():
            n, lab, st, ce = cv2.connectedComponentsWithStats(m.astype(np.uint8))
            i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
            return [ce[i][0] / self.ppm_x, ce[i][1] / self.ppm_y]
        self.warnings.append(
            "Source d'eau non indiquee : coin haut-gauche (0,0) utilise par defaut."
        )
        return [0.0, 0.0]

    # ------------------------------------------------------------------ main
    def run(self):
        self._classify()
        self._detect_plants()
        self.source = self._source()
        area_px = self.ppm_x * self.ppm_y
        self.zones = []
        for zid, z in enumerate(self.cfg["zones"]):
            m = self.zone_masks[zid]
            pz = [p for p in self.plants if p["zone"] == zid]
            pts = np.array([[p["x"], p["y"]] for p in pz]) if pz else np.zeros((0, 2))
            rows = self.analyse_rows(pts) if z.get("plantee") else None
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
            if m.any():
                ys, xs = np.nonzero(m)
                info["centre"] = [
                    float(xs.mean() / self.ppm_x),
                    float(ys.mean() / self.ppm_y),
                ]
            else:
                info["centre"] = None
                self.warnings.append(
                    f"Zone '{z['nom']}' : couleur {z['couleur']} introuvable dans l'image."
                )
            info["irrigation"] = self._analyse_irrigation(zid, z, pz, rows)
            if rows and info["irrigation"]["type"] == "aspersion":
                # une tete d'asperseur dessinee peut masquer des plantes : ces "trous" ne sont pas des manquants
                heads = np.array(
                    info["irrigation"].get("asperseurs", []) or [[-1e9, -1e9]]
                )
                rows["manquants"] = [
                    m
                    for m in rows["manquants"]
                    if np.min(np.hypot(heads[:, 0] - m[0], heads[:, 1] - m[1])) > 1.0
                ]
            self.zones.append(info)
        return self
