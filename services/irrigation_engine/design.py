"""Conception du systeme d'irrigation optimal : rangs, rampes, porte-rampes, secteurs, conduite principale."""

import math
import numpy as np
import cv2
from .crops import get_crop, SOLS, PE_TUBES

PRESSION_GOUTTEUR_M = 10.0  # pression nominale d'un goutteur (1 bar)
DH_MAX_RAMPE = 0.20 * PRESSION_GOUTTEUR_M  # regle des 20 % (variation de debit ~10 %)
D_RAMPE_MM = 13.6  # rampe PE 16 mm
PW_CIBLE = 0.33  # fraction de sol humidifie mini en climat aride (Keller)


# ------------------------------------------------------------------ hydraulique
def perte_hw(q_l_h, d_mm, l_m, f=1.0, c=140):
    """Hazen-Williams (Keller) : J (m/100 m) = 1.212e12 (Q/C)^1.852 D^-4.87, Q en L/s, D en mm."""
    if q_l_h <= 0 or l_m <= 0:
        return 0.0
    q = q_l_h / 3600.0
    j = 1.212e12 * (q / c) ** 1.852 * d_mm**-4.87
    return j * l_m / 100.0 * f


def vitesse(q_l_h, d_mm):
    return (q_l_h / 3.6e6) / (math.pi * (d_mm / 1000) ** 2 / 4)


def choisir_tube(q_l_h, l_m, hf_max, f=1.0, d_min=25, v_max=1.5):
    for de, di in PE_TUBES:
        if de < d_min:
            continue
        if vitesse(q_l_h, di) <= v_max and perte_hw(q_l_h, di, l_m, f) <= hf_max:
            return de, di
    return PE_TUBES[-1]


def longueur_max_rampe(q_l_h_par_m, dh_max=DH_MAX_RAMPE):
    """Longueur de rampe 16 mm (alimentee par un bout) pour laquelle la perte <= dh_max."""
    lo, hi = 1.0, 1000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if perte_hw(q_l_h_par_m * mid, D_RAMPE_MM, mid, f=0.36) > dh_max:
            hi = mid
        else:
            lo = mid
    return lo


# ------------------------------------------------------------------ geometrie
def _runs(flags, s_vals):
    segs, start = [], None
    for f, s in zip(flags, s_vals):
        if f and start is None:
            start = s
        if not f and start is not None:
            segs.append((start, prev))
            start = None
        prev = s
    if start is not None:
        segs.append((start, prev))
    return segs


def _orientation_auto(mask_m_pts, pref):
    if pref == "nord_sud":
        return np.array([0.0, 1.0])
    if pref == "est_ouest":
        return np.array([1.0, 0.0])
    rect = cv2.minAreaRect(mask_m_pts.astype(np.float32))
    box = cv2.boxPoints(rect)
    e1, e2 = box[1] - box[0], box[2] - box[1]
    v = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
    v = v / np.linalg.norm(v)
    return v.astype(float)


def _chemin_glouton(pts, u, n, src):
    """Ordonne les points d'alimentation (arbres epars) en partant du plus proche de la source,
    puis toujours vers le plus proche restant : porte-rampe court, sans aller-retour."""
    xy = [np.array(p["s"] * u + p["t"] * n) for p in pts]
    reste = list(range(len(pts)))
    i = min(reste, key=lambda j: float(np.linalg.norm(xy[j] - src)))
    ordre = [i]
    reste.remove(i)
    while reste:
        i = min(reste, key=lambda j: float(np.linalg.norm(xy[j] - xy[ordre[-1]])))
        ordre.append(i)
        reste.remove(i)
    # 2-opt (depart fixe) : on retourne un troncon tant que cela raccourcit le chemin -> plus de croisements
    d = lambda a, b: float(np.linalg.norm(xy[a] - xy[b]))
    ameliore = True
    while ameliore:
        ameliore = False
        for i in range(1, len(ordre) - 1):
            for k in range(i + 1, len(ordre)):
                a, b, c = ordre[i - 1], ordre[i], ordre[k]
                e = ordre[k + 1] if k + 1 < len(ordre) else None
                avant = d(a, b) + (d(c, e) if e is not None else 0.0)
                apres = d(a, c) + (d(b, e) if e is not None else 0.0)
                if apres < avant - 1e-6:
                    ordre[i : k + 1] = ordre[i : k + 1][::-1]
                    ameliore = True
    return [pts[j] for j in ordre]


class Conception:
    def __init__(self, terrain):
        self.T = terrain
        self.cfg = terrain.cfg
        self.sol = SOLS[self.cfg.get("sol", "limoneux")]
        pompe = self.cfg.get("pompe", {})
        self.q_pompe_l_h = pompe.get("debit_m3_h", 15.0) * 1000
        self.h_max = pompe.get("heures_max_jour", 12)
        self.zones = []

    def _in_mask(self, mask, x_m, y_m):
        xi = np.clip((np.asarray(x_m) * self.T.ppm_x).astype(int), 0, self.T.w - 1)
        yi = np.clip((np.asarray(y_m) * self.T.ppm_y).astype(int), 0, self.T.h - 1)
        return mask[yi, xi]

    def _clip(self, mask, u, n, t, a, b, min_len=0.5, step=0.1):
        """Decoupe la ligne {s*u + t*n, s in [a,b]} en morceaux situes dans le masque."""
        if b <= a:
            return []
        ss = np.arange(a, b + step / 2, step)
        xy = np.outer(ss, u) + t * n
        W, H = self.T.w / self.T.ppm_x, self.T.h / self.T.ppm_y
        inside = (
            self._in_mask(mask, xy[:, 0], xy[:, 1])
            & (xy[:, 0] >= 0)
            & (xy[:, 1] >= 0)
            & (xy[:, 0] <= W)
            & (xy[:, 1] <= H)
        )
        return [(s0, s1) for s0, s1 in _runs(inside, ss) if s1 - s0 >= min_len]

    def _zone(self, zinfo):
        zc = self.cfg["zones"][zinfo["id"]]
        crop = get_crop(zinfo["culture"])
        if crop["systeme"] == "aspersion" and zinfo.get("interdire_aspersion"):
            # zone polluee : pas d'aspersion (aerosols, ruissellement) -> gaines goutte-a-goutte tous les 0.6 m
            crop = dict(
                crop,
                type="maraichage",
                ecart_opt=(0.6, 0.3),
                ecart_rang_m=(0.5, 0.8),
                ecart_plante_m=(0.2, 0.4),
                debit_goutteur_l_h=1.6,
                ecart_goutteur_m=0.3,
                lignes_par_rang=1,
                systeme="goutte_a_goutte",
            )
        T = self.T
        mask = T.zone_masks[zinfo["id"]]
        tree_like = crop["type"] in ("arbre", "arbuste")
        rows_det = zinfo["rangs"]
        self._crop_eff = getattr(self, "_crop_eff", {})
        self._crop_eff[zinfo["id"]] = crop
        d = {
            "id": zinfo["id"],
            "nom": zinfo["nom"],
            "culture": zinfo["culture"],
            "type": crop["type"],
            "systeme": crop["systeme"],
        }
        if not mask.any():
            d["vide"] = True
            return d
        if self.cfg.get("plantees_seulement") and not zinfo.get("plantee"):
            d["vide"] = d["non_plantee"] = True  # terre deja plantee ailleurs : pas de plantation inventee ici
            return d
        if crop["systeme"] == "aspersion" and not zinfo.get("interdire_aspersion"):
            return self._zone_aspersion(zinfo, crop, mask, d)

        # ---- 1. rangs : existants (zone plantee), arbres existants epars, ou generes
        existing = (rows_det is not None and rows_det["n_rangs"] >= 2
                    and not rows_det.get("irreguliere"))
        isoles = (not existing and tree_like and zinfo.get("plantee")
                  and len(zinfo.get("plantes") or []) > 0)
        L_plante = None  # longueur de rampe par plante (par defaut : l'ecartement sur le rang)
        diam_det = None
        if existing:
            u, n = np.array(rows_det["u"]), np.array(rows_det["n"])
            sr = (
                rows_det["ecart_rang_m"]
                if not math.isnan(rows_det["ecart_rang_m"])
                else crop["ecart_opt"][0]
            )
            sp = rows_det["ecart_plante_m"]
            ext = sp / 2 if tree_like else 0.2
            pts = [(p["x"], p["y"]) for p in zinfo["plantes"]]
            rows = []
            for r in rows_det["rows"]:
                segs = self._clip(
                    mask,
                    u,
                    n,
                    r["t"],
                    r["s_min"] - ext,
                    r["s_max"] + ext,
                    min_len=0.5 if tree_like else 1.0,
                )
                if segs:
                    rows.append({"t": r["t"], "segs": segs})
            new_pts = rows_det["manquants"] if tree_like else []
            d["mode"] = "existant"
        elif isoles:
            # terre deja plantee, arbres epars : on irrigue CHAQUE arbre detecte, sans en ajouter.
            # 2 courtes rampes sous la couronne de chaque arbre ; surface par arbre = surface reelle.
            ys, xs = np.nonzero(mask[::2, ::2])
            mpts = np.column_stack([xs * 2 / T.ppm_x, ys * 2 / T.ppm_y])
            u = _orientation_auto(
                mpts,
                zc.get("orientation_rangs", self.cfg.get("orientation_rangs", "auto")),
            )
            n = np.array([-u[1], u[0]])
            pts = [(p["x"], p["y"]) for p in zinfo["plantes"]]
            surf = float(mask.sum() / (T.ppm_x * T.ppm_y))
            diam_det = float(np.median([p.get("diam_m", crop["diam_couronne_m"]) for p in zinfo["plantes"]]))
            # surface exploitee par un arbre : celle qui lui revient, au plus (2 x couronne)^2
            # (les racines d'un arbre isole n'exploitent pas tout l'espace libre) - a valider
            sr = sp = math.sqrt(min(surf / len(pts), (2 * max(diam_det, 2.0)) ** 2))
            L_plante = min(max(diam_det, 2.0), 8.0)
            rows = []
            for x, y in pts:
                q = np.array([x, y])
                t, s = float(q @ n), float(q @ u)
                segs = self._clip(mask, u, n, t, s - L_plante / 2, s + L_plante / 2, min_len=0.5)
                if segs:
                    rows.append({"t": t, "segs": segs})
            new_pts = []
            d["mode"] = "arbres_existants"
        else:
            ys, xs = np.nonzero(mask[::2, ::2])
            mpts = np.column_stack([xs * 2 / T.ppm_x, ys * 2 / T.ppm_y])
            u = _orientation_auto(
                mpts,
                zc.get("orientation_rangs", self.cfg.get("orientation_rangs", "auto")),
            )
            n = np.array([-u[1], u[0]])
            sr, sp = zc.get("ecartement_m", crop["ecart_opt"])
            margin = max(1.0, sp / 2) if tree_like else 0.5
            k = max(1, int(margin * T.ppm))
            emask = (
                cv2.erode(
                    mask.astype(np.uint8),
                    np.ones((2 * k + 1, 2 * k + 1), np.uint8),
                    borderType=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )
                > 0
            )
            t_all, s_all = mpts @ n, mpts @ u
            t0, t1 = t_all.min() + margin, t_all.max() - margin
            s0, s1 = s_all.min(), s_all.max()
            # centrer les rangs dans la zone
            nr = int(math.floor((t1 - t0) / sr)) + 1
            off = ((t1 - t0) - (nr - 1) * sr) / 2
            rows, new_pts, pts = [], [], []
            step = 0.25
            s_samp = np.arange(s0, s1 + step, step)
            for i in range(max(nr, 0)):
                t = t0 + off + i * sr
                xy = np.outer(s_samp, u) + t * n
                flags = self._in_mask(emask, xy[:, 0], xy[:, 1])
                segs = [
                    sg
                    for sg in _runs(flags, s_samp)
                    if sg[1] - sg[0] >= (sp if tree_like else 1.0)
                ]
                if not segs:
                    continue
                rows.append({"t": t, "segs": segs})
                if tree_like:
                    for a, b in segs:
                        npl = int(math.floor((b - a) / sp)) + 1
                        o2 = ((b - a) - (npl - 1) * sp) / 2
                        for j in range(npl):
                            s = a + o2 + j * sp
                            new_pts.append((s * u + t * n).tolist())
                    # le rang va d'un demi-ecartement avant le 1er arbre a apres le dernier
            if tree_like:
                for r in rows:
                    r["segs"] = [(a, b) for a, b in r["segs"]]
            d["mode"] = (
                "nouvelle_plantation" if not zinfo["plantee"] else "restructuration"
            )
        d.update(
            u=u.tolist(),
            n=n.tolist(),
            ecart_rang_m=float(sr),
            ecart_plante_m=float(sp),
            plantes_existantes=pts,
            plantes_a_planter=new_pts,
        )
        if tree_like:
            n_plants = len(pts) + len(new_pts)
        else:
            n_plants = int(sum((b - a) / sp for r in rows for a, b in r["segs"]))
        d["n_plantes_total"] = n_plants

        # ---- 2. goutteurs
        q_e = zc.get("debit_goutteur_l_h", crop["debit_goutteur_l_h"])
        lines_per_row = crop["lignes_par_rang"]
        crown = diam_det or crop["diam_couronne_m"]  # arbres existants : couronne mesuree
        L_plante = L_plante or sp
        age = zc.get("age_ans")
        if age is not None and tree_like:
            crown *= min(
                1.0,
                max(
                    0.3, age / (10 if zinfo["culture"] in ("olivier", "palmier") else 6)
                ),
            )
        d["gc"] = min(0.9, math.pi * (crown / 2) ** 2 / (sr * sp))
        if tree_like:
            dw = self.sol["diam_mouille_m"] * math.sqrt(q_e / 4.0)
            aw = math.pi * (dw / 2) ** 2
            pw_c = 0.25 if crop.get("tolerance_secheresse") == "elevee" else PW_CIBLE
            ne = max(lines_per_row, math.ceil(pw_c * sr * sp / aw))
            ne = int(math.ceil(ne / lines_per_row) * lines_per_row)
            ne_max = 8 if crop.get("tolerance_secheresse") == "elevee" else 12
            if d.get("mode") == "arbres_existants":
                ne_max *= 2  # gros arbres isoles : sinon plus de 10 h d'arrosage par jour en ete
            ne = min(ne, ne_max)
            d["goutteurs_par_plante"] = ne
            d["pw"] = min(1.0, ne * aw / (sr * sp))
            d["debit_par_plante_l_h"] = ne * q_e
            spacing_e = max(0.6, min(1.0, L_plante / max(ne / lines_per_row, 1)))
            d["espacement_goutteurs_m"] = spacing_e
            lat_off = min(1.5, max(0.5, crown / 4)) if lines_per_row == 2 else 0.0
            d["surface_par_plante_m2"] = sr * sp
            q_per_m_lat = (ne / lines_per_row) * q_e / L_plante
        else:
            se = crop.get("ecart_goutteur_m", 0.3)
            d["espacement_goutteurs_m"] = se
            d["goutteurs_par_plante"] = sp / se
            d["debit_par_plante_l_h"] = q_e * sp / se
            d["pw"] = min(
                1.0, 0.8 * self.sol["diam_mouille_m"] * math.sqrt(q_e / 4.0) / sr
            )
            d["surface_par_plante_m2"] = sr * sp
            lat_off = 0.0
            q_per_m_lat = q_e / se
        d["debit_goutteur_l_h"] = q_e
        d["decalage_rampe_m"] = lat_off
        d["lignes_par_rang"] = lines_per_row
        d["surface_utile_m2"] = n_plants * sr * sp

        # ---- 3. alimentation des rampes : par un bout ou par le milieu
        src = np.array(T.source)
        s_src = src @ u
        lmax = longueur_max_rampe(q_per_m_lat)
        lmax_ac = longueur_max_rampe(
            q_per_m_lat, dh_max=0.5 * PRESSION_GOUTTEUR_M
        )  # autoregulants
        longest = max((b - a) for r in rows for a, b in r["segs"]) if rows else 0
        if longest <= lmax:
            feed = "bout"
        elif longest / 2 <= lmax:
            feed = "milieu"
        else:
            feed = "milieu"
        d["alimentation"] = feed
        d["longueur_max_rampe_m"] = lmax
        d["autoregulant_requis"] = (longest / (2 if feed == "milieu" else 1)) > lmax
        if d["autoregulant_requis"] and longest / 2 > lmax_ac:
            d["alerte_rampe"] = (
                f"Rangs de {longest:.0f} m : meme avec goutteurs autoregulants (max ~{2*lmax_ac:.0f} m "
                "alimente au milieu), couper les rangs en deux secteurs ou utiliser une rampe 20 mm."
            )

        # ---- 4. rampes et points du porte-rampe
        laterals, sub_pts = [], []
        for r in sorted(rows, key=lambda r: r["t"]):
            for a, b in r["segs"]:
                if feed == "bout":
                    s_feed = a if abs(a - s_src) <= abs(b - s_src) else b
                else:
                    s_feed = (a + b) / 2
                offs = [-lat_off, lat_off] if lines_per_row == 2 else [0.0]
                q_row = 0.0
                for o in offs:
                    # chaque rampe est decoupee pour rester dans la zone
                    for a2, b2 in (
                        self._clip(mask, u, n, r["t"] + o, a, b, min_len=0.5) or []
                    ):
                        p0 = (a2 * u + (r["t"] + o) * n).tolist()
                        p1 = (b2 * u + (r["t"] + o) * n).tolist()
                        laterals.append(
                            {
                                "p0": p0,
                                "p1": p1,
                                "L": b2 - a2,
                                "t": r["t"] + o,
                                "q_l_h": q_per_m_lat * (b2 - a2),
                            }
                        )
                        q_row += q_per_m_lat * (b2 - a2)
                if q_row > 0:
                    sub_pts.append({"t": r["t"], "s": s_feed, "q_l_h": q_row})
        d["rampes"] = laterals
        q_zone = sum(l["q_l_h"] for l in laterals)
        d["debit_zone_l_h"] = q_zone
        d["n_goutteurs"] = int(sum(l["L"] for l in laterals) * q_per_m_lat / q_e)

        # ---- 5. secteurs (limite de la pompe)
        k = max(1, math.ceil(q_zone / (0.9 * self.q_pompe_l_h)))
        if d.get("mode") == "arbres_existants" and sub_pts:
            sub_pts = _chemin_glouton(sub_pts, u, n, src)  # d'arbre en arbre, sans zigzag
        else:
            sub_pts.sort(key=lambda p: p["t"])
        target = q_zone / k
        groups, cur, acc = [], [], 0.0
        for p in sub_pts:
            cur.append(p)
            acc += p["q_l_h"]
            if acc >= target * 0.999 and len(groups) < k - 1:
                groups.append(cur)
                cur, acc = [], 0.0
        if cur:
            groups.append(cur)
        secteurs = []
        for g in groups:
            q = sum(p["q_l_h"] for p in g)
            poly = [(p["s"] * u + p["t"] * n).tolist() for p in g]
            # porte-rampe : relie les points d'alimentation, a 0.5 m de la tete des rampes
            L_sub = (
                sum(math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
                if len(poly) > 1
                else 1.0
            )
            de, di = choisir_tube(q, L_sub, hf_max=1.5, f=0.38, d_min=25)
            hf_sub = perte_hw(q, di, L_sub, f=0.38)
            # vanne au point du porte-rampe le plus proche de la source
            j = int(np.argmin([math.dist(pp, src) for pp in poly]))
            Lr = max(l["L"] for l in laterals) / (2 if feed == "milieu" else 1)
            hf_lat = perte_hw(q_per_m_lat * Lr, D_RAMPE_MM, Lr, f=0.36)
            secteurs.append(
                {
                    "debit_l_h": q,
                    "porte_rampe": poly,
                    "L_porte_rampe_m": L_sub,
                    "diam_porte_rampe_mm": de,
                    "hf_porte_rampe_m": hf_sub,
                    "vanne": poly[j],
                    "hf_rampe_m": hf_lat,
                    "n_rangs": len(g),
                }
            )
        d["secteurs"] = secteurs
        return d

    def _zone_aspersion(self, zinfo, crop, mask, d):
        """Grandes cultures : couverture integrale basse pression (asperseurs 12 m x 12 m)."""
        T = self.T
        esp = 12.0
        r = (
            0.65 * esp
        )  # rayon ~7.8 m : recouvrement suffisant pour une bonne uniformite
        ys, xs = np.nonzero(mask)
        x0, x1, y0, y1 = (
            xs.min() / T.ppm_x,
            xs.max() / T.ppm_x,
            ys.min() / T.ppm_y,
            ys.max() / T.ppm_y,
        )
        heads = []
        for yy in np.arange(y0 + esp / 2, y1, esp):
            for xx in np.arange(x0 + esp / 2, x1, esp):
                if self._in_mask(mask, xx, yy):
                    heads.append([float(xx), float(yy)])
        q_head = 1100.0  # L/h, asperseur basse pression 2.5 bar
        q_zone = q_head * len(heads)
        area = mask.sum() / (T.ppm_x * T.ppm_y)
        d.update(
            mode="aspersion",
            asperseurs=heads,
            rayon_m=r,
            debit_zone_l_h=q_zone,
            surface_utile_m2=area,
            gc=1.0,
            pw=1.0,
            n_plantes_total=0,
            surface_par_plante_m2=esp * esp,
            debit_par_plante_l_h=q_head,
            goutteurs_par_plante=1,
            rampes=[],
            plantes_existantes=[],
            plantes_a_planter=[],
        )
        k = max(1, math.ceil(q_zone / (0.9 * self.q_pompe_l_h)))
        per = math.ceil(len(heads) / k)
        secteurs = []
        for i in range(k):
            g = heads[i * per : (i + 1) * per]
            if not g:
                continue
            secteurs.append(
                {
                    "debit_l_h": q_head * len(g),
                    "porte_rampe": g,
                    "L_porte_rampe_m": esp * len(g),
                    "diam_porte_rampe_mm": choisir_tube(
                        q_head * len(g), esp * len(g), 3.0, 0.38
                    )[0],
                    "hf_porte_rampe_m": 0.0,
                    "vanne": g[0],
                    "hf_rampe_m": 0.0,
                    "n_rangs": len(g),
                }
            )
        d["secteurs"] = secteurs
        return d

    # ------------------------------------------------------------------ reseau principal
    def _reseau_principal(self):
        src = list(self.T.source)
        nodes = [src] + [
            s["vanne"] for z in self.zones if not z.get("vide") for s in z["secteurs"]
        ]
        n = len(nodes)
        in_tree, edges = {0}, []
        while len(in_tree) < n:
            best = None
            for i in in_tree:
                for j in range(n):
                    if j in in_tree:
                        continue
                    dd = abs(nodes[i][0] - nodes[j][0]) + abs(nodes[i][1] - nodes[j][1])
                    if best is None or dd < best[0]:
                        best = (dd, i, j)
            in_tree.add(best[2])
            edges.append((best[1], best[2]))
        segs = []
        for i, j in edges:
            a, b = nodes[i], nodes[j]
            corner = [b[0], a[1]]
            segs.append([a, corner, b])
        L = sum(abs(s[0][0] - s[2][0]) + abs(s[0][1] - s[2][1]) for s in segs)
        q_max = max(
            [
                s["debit_l_h"]
                for z in self.zones
                if not z.get("vide")
                for s in z["secteurs"]
            ]
            or [0]
        )
        de, di = choisir_tube(q_max, max(L, 1), hf_max=max(1.0, 0.01 * L), d_min=32)
        # perte jusqu'a la vanne la plus eloignee (chemin dans l'arbre)
        parent = {j: i for i, j in edges}

        def path_len(j):
            tot = 0.0
            while j in parent:
                i = parent[j]
                tot += abs(nodes[i][0] - nodes[j][0]) + abs(nodes[i][1] - nodes[j][1])
                j = i
            return tot

        lfar = max([path_len(j) for j in range(1, n)] or [0])
        self.principal = {
            "segments": segs,
            "longueur_m": L,
            "diam_mm": de,
            "debit_max_l_h": q_max,
            "hf_m": perte_hw(q_max, di, lfar),
            "vitesse_m_s": vitesse(q_max, di),
        }

    def run(self):
        self.zones = [self._zone(z) for z in self.T.zones]
        self._reseau_principal()
        # hauteur manometrique totale
        hmt = []
        for z in self.zones:
            if z.get("vide"):
                continue
            for s in z["secteurs"]:
                base = 25.0 if z.get("mode") == "aspersion" else PRESSION_GOUTTEUR_M
                hmt.append(
                    base
                    + s["hf_rampe_m"]
                    + s["hf_porte_rampe_m"]
                    + self.principal["hf_m"]
                    + 5.0
                    + self.cfg.get("denivele_m", 0.0)
                )
        self.hmt_m = max(hmt) if hmt else 0
        return self

    # ------------------------------------------------------------------ nomenclature
    def nomenclature(self):
        items = {}

        def add(k, qte, unite):
            items.setdefault(k, [0, unite])
            items[k][0] += qte

        n_ramp = 0
        for z in self.zones:
            if z.get("vide"):
                continue
            if z.get("mode") == "aspersion":
                add(
                    "Asperseur basse pression 2.5 bar (~1.1 m3/h)",
                    len(z["asperseurs"]),
                    "u",
                )
            else:
                L = sum(l["L"] for l in z["rampes"])
                kind = (
                    "Gaine/rampe goutte-a-goutte integre 16 mm"
                    if z["type"] == "maraichage"
                    else "Rampe PE 16 mm"
                )
                add(kind, L * 1.03, "m")
                if z["type"] != "maraichage":
                    add(
                        f"Goutteur {'autoregulant ' if z.get('autoregulant_requis') else ''}{z['debit_goutteur_l_h']:.0f} L/h",
                        z["n_goutteurs"],
                        "u",
                    )
                n_ramp += len(z["rampes"])
            for s in z["secteurs"]:
                add(
                    f"Porte-rampe PE {s['diam_porte_rampe_mm']} mm",
                    s["L_porte_rampe_m"] * 1.05,
                    "m",
                )
                add(
                    f"Electrovanne / vanne de secteur {s['diam_porte_rampe_mm']} mm",
                    1,
                    "u",
                )
        add("Raccord de depart de rampe + bouchon de fin", n_ramp, "u")
        add(
            f"Conduite principale PE {self.principal['diam_mm']} mm (enterree 40-60 cm)",
            self.principal["longueur_m"] * 1.05,
            "m",
        )
        add(
            "Station de tete : filtre a disques 120 mesh (+ filtre a sable si eau de bassin/oued)",
            1,
            "u",
        )
        add("Injecteur d'engrais (Venturi) + vanne anti-retour", 1, "u")
        add("Compteur volumetrique + 2 manometres + regulateur de pression", 1, "u")
        add(
            "Programmateur d'irrigation (nombre de secteurs = nombre de vannes)", 1, "u"
        )
        add(
            "Tensiometres / sondes d'humidite (2 par secteur, 30 et 60 cm)",
            2 * sum(len(z["secteurs"]) for z in self.zones if not z.get("vide")),
            "u",
        )
        return [
            {"article": k, "quantite": round(v[0], 1), "unite": v[1]}
            for k, v in items.items()
        ]
