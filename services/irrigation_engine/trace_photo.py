"""Trace le reseau d'irrigation optimal DIRECTEMENT sur la photo d'origine de l'agriculteur.

Le plan est calcule en metres sur la vue redressee, puis chaque point est reprojete dans la photo
par l'homographie inverse : les droites restent droites, la perspective de la photo est respectee.
"""

import math
from pathlib import Path

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

from .drawing import SECT_COLORS

POLICES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _police(taille, gras=False):
    noms = (
        [
            p.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf").replace(
                "arial.ttf", "arialbd.ttf"
            )
            for p in POLICES
        ]
        if gras
        else []
    )
    for p in noms + POLICES:
        if Path(p).exists():
            return ImageFont.truetype(p, taille)
    try:
        return ImageFont.load_default(size=taille)
    except TypeError:
        return ImageFont.load_default()


def _hex_bgr(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (4, 2, 0))


def tracer_sur_photo(T, C, res, path, largeur_max=2000, largeur_min=1000):
    rgb0 = T._rgb0
    h0, w0 = rgb0.shape[:2]
    s = min(1.0, largeur_max / w0)
    if w0 * s < largeur_min:  # petite image (ex. satellite au zoom 18) : agrandie pour rester lisible
        s = largeur_min / w0
    img = cv2.cvtColor(rgb0, cv2.COLOR_RGB2BGR)
    if s != 1:
        img = cv2.resize(img, (int(round(w0 * s)), int(round(h0 * s))),
                         interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    img = (img.astype(np.float32) * 0.82).astype(
        np.uint8
    )  # leger assombrissement : le trace ressort
    H, W = img.shape[:2]
    t = max(2, int(round(min(H, W) / 380)))

    def P(pts):
        return (T.m_vers_px(pts) * s).astype(np.float32)

    def ipt(p):
        return int(round(p[0])), int(round(p[1]))

    def visible(p):
        return -W < p[0] < 2 * W and -H < p[1] < 2 * H

    # limite de la parcelle
    poly = (np.float32(T._coins) * s).astype(np.int32)
    cv2.polylines(img, [poly], True, (0, 0, 0), t + 3, cv2.LINE_AA)
    cv2.polylines(img, [poly], True, (255, 255, 255), t, cv2.LINE_AA)
    # limites des zones (si plusieurs)
    if len(T.zone_masks) > 1:
        for zc, m in zip(T.cfg["zones"], T.zone_masks):
            cs, _ = cv2.findContours(
                m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for c in cs:
                pts = [[x / T.ppm_x, y / T.ppm_y] for x, y in c[:, 0, :]]
                q = P(pts).astype(np.int32)
                cv2.polylines(
                    img, [q], True, _hex_bgr(zc["couleur"]), max(1, t - 1), cv2.LINE_AA
                )

    labels = []  # (x, y, texte, couleur_rgb)
    s_idx = 0
    for z in C.zones:
        if z.get("vide"):
            continue
        sect = []
        for sc in z["secteurs"]:
            col = sc.get("couleur") or SECT_COLORS[s_idx % len(SECT_COLORS)]
            s_idx += 1
            sect.append((sc, col, sc.get("label") or f"S{s_idx}"))
        n = np.array(z.get("n", [0, 1]))
        bornes = []
        for sc, col, lab in sect:
            ts = [np.array(p) @ n for p in sc["porte_rampe"]]
            er = z.get("ecart_rang_m", 1.0)
            bornes.append((min(ts) - 0.5 * er, max(ts) + 0.5 * er, col))
        # rampes
        for l in z.get("rampes", []):
            col = next(
                (c for a, b, c in bornes if a <= l["t"] <= b),
                sect[0][1] if sect else "#1f6feb",
            )
            a, b = P([l["p0"], l["p1"]])
            if visible(a) and visible(b):
                cv2.line(img, ipt(a), ipt(b), (255, 255, 255), t + 2, cv2.LINE_AA)
                cv2.line(img, ipt(a), ipt(b), _hex_bgr(col), t, cv2.LINE_AA)
        # asperseurs (grandes cultures)
        for hx, hy in z.get("asperseurs", []):
            c = P([[hx, hy]])[0]
            cv2.circle(img, ipt(c), 3 * t, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(
                img,
                ipt(c),
                2 * t,
                _hex_bgr(sect[0][1]) if sect else (255, 0, 0),
                -1,
                cv2.LINE_AA,
            )
        # goutteurs autour des arbres
        if z.get("type") in ("arbre", "arbuste") and z.get("rampes"):
            u = np.array(z["u"])
            per_line = max(
                1, int(round(z["goutteurs_par_plante"] / max(z["lignes_par_rang"], 1)))
            )
            se, off = z["espacement_goutteurs_m"], z.get("decalage_rampe_m", 0.0)
            pts = []
            for x, y in list(z.get("plantes_existantes", [])) + list(
                z.get("plantes_a_planter", [])
            ):
                p = np.array([x, y])
                for o in ([-off, off] if z["lignes_par_rang"] == 2 else [0.0]):
                    for e in range(per_line):
                        pts.append(
                            (p + (e - (per_line - 1) / 2) * se * u + o * n).tolist()
                        )
            if pts and len(pts) < 20000:
                for q in P(pts):
                    cv2.circle(img, ipt(q), max(2, t), (40, 20, 10), -1, cv2.LINE_AA)
                    cv2.circle(
                        img, ipt(q), max(1, t - 1), (255, 220, 60), -1, cv2.LINE_AA
                    )
        # porte-rampes + vannes
        for sc, col, lab in sect:
            pr = P(sc["porte_rampe"]).astype(np.int32)
            if len(pr) > 1:
                cv2.polylines(img, [pr], False, (255, 255, 255), 2 * t + 3, cv2.LINE_AA)
                cv2.polylines(img, [pr], False, _hex_bgr(col), 2 * t, cv2.LINE_AA)
        # plantes
        r_pl = max(4, 3 * t)
        for x, y in (
            z.get("plantes_existantes", []) if z.get("type") != "maraichage" else []
        ):
            c = P([[x, y]])[0]
            cv2.circle(img, ipt(c), r_pl, (0, 0, 0), t + 2, cv2.LINE_AA)
            cv2.circle(img, ipt(c), r_pl, (60, 220, 60), t, cv2.LINE_AA)
        for x, y in z.get("plantes_a_planter", []):
            c = P([[x, y]])[0]
            cv2.circle(img, ipt(c), r_pl, (0, 0, 0), t + 2, cv2.LINE_AA)
            cv2.circle(img, ipt(c), r_pl, (0, 140, 255), t, cv2.LINE_AA)
            cv2.line(
                img,
                (ipt(c)[0] - r_pl // 2, ipt(c)[1]),
                (ipt(c)[0] + r_pl // 2, ipt(c)[1]),
                (0, 140, 255),
                t,
            )
            cv2.line(
                img,
                (ipt(c)[0], ipt(c)[1] - r_pl // 2),
                (ipt(c)[0], ipt(c)[1] + r_pl // 2),
                (0, 140, 255),
                t,
            )
        for sc, col, lab in sect:
            v = P([sc["vanne"]])[0]
            k = 3 * t
            cv2.rectangle(
                img,
                (ipt(v)[0] - k, ipt(v)[1] - k),
                (ipt(v)[0] + k, ipt(v)[1] + k),
                (0, 0, 0),
                -1,
            )
            cv2.rectangle(
                img,
                (ipt(v)[0] - k + 2, ipt(v)[1] - k + 2),
                (ipt(v)[0] + k - 2, ipt(v)[1] + k - 2),
                _hex_bgr(col),
                -1,
            )
            labels.append((ipt(v)[0] + k + 4, ipt(v)[1] - 2 * k, f"Vanne {lab}", col))
    # conduite principale
    for seg in C.principal["segments"]:
        q = P(seg).astype(np.int32)
        cv2.polylines(img, [q], False, (255, 255, 255), 3 * t + 4, cv2.LINE_AA)
        cv2.polylines(img, [q], False, (89, 46, 11), 3 * t, cv2.LINE_AA)
    src = P([T.source])[0]
    k = 5 * t
    tri = np.int32(
        [
            [src[0], src[1] - k],
            [src[0] - k, src[1] + k * 0.7],
            [src[0] + k, src[1] + k * 0.7],
        ]
    )
    cv2.fillPoly(img, [tri], (0, 0, 0))
    cv2.fillPoly(
        img,
        [((tri - src.astype(np.int32)) * 0.7 + src.astype(np.int32)).astype(np.int32)],
        (40, 40, 220),
    )
    labels.append((int(src[0]) + k + 4, int(src[1]) - k, "Source + filtre", "#b71c1c"))

    # ------------------------------------------------------------------ texte (PIL, accents)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    dr = ImageDraw.Draw(pil)
    fs = int(np.clip(W / 55, 14, 40))
    f_lab = _police(fs, True)
    for x, y, txt, col in labels:
        x = min(max(x, 2), W - fs * len(txt) // 2)
        y = min(max(y, 2), H - fs - 4)
        dr.text(
            (x, y),
            txt,
            font=f_lab,
            fill=col,
            stroke_width=max(2, fs // 8),
            stroke_fill="white",
        )

    # ------------------------------------------------------------------ legende + conseil
    b = res["bilan"]
    cs = res.get("conseil_simple", [])
    lignes = []
    for c in cs:
        txt = f"{c['zone']} : {c['n_plantes'] or '-'} plantes"
        if c.get("a_replanter"):
            txt += f" (dont {c['a_replanter']} à replanter)"
        txt += (
            f" · {c['goutteurs_par_plante']:g} goutteur(s) de {c['debit_goutteur_l_h']:g} L/h par plante"
            f" · {c['longueur_rampes_m']:.0f} m de rampe"
        )
        lignes.append(txt)
        for cle, nom in (("maintenant", "Ce mois-ci"), ("pointe", "En été")):
            p = c.get(cle)
            if p:
                lignes.append(
                    f"   {nom} ({p['mois']}) : {p['litres_plante_jour']:g} L/plante/jour → arroser "
                    f"{p['duree_min'] // 60} h {p['duree_min'] % 60:02d} min "
                    + ("chaque jour" if p["tous_les_jours"] == 1 else f"tous les {p['tous_les_jours']} jours")
                )
    if b.get("actuel_m3_an"):
        lignes.append(
            f"Économie d'eau estimée : -{b['economie_pct']:.0f} % "
            f"({b['actuel_m3_an']:,.0f} → {b['optimal_m3_an']:,.0f} m³/an)".replace(
                ",", " "
            )
        )
    si = (getattr(T, "photo_info", None) or {}).get("source_image")
    if si:  # attribution du fournisseur d'images (obligatoire) + resolution
        from .satellite import lignes_source

        lignes.extend("   " + l for l in lignes_source(si))
    f_t, f_n = _police(int(fs * 1.15), True), _police(int(fs * 0.85))
    leg_items = [
        ("#0b2e59", "Conduite principale", "line3"),
        (SECT_COLORS[0], "Porte-rampe (1 couleur = 1 secteur)", "line2"),
        (SECT_COLORS[0], "Rampe goutte-à-goutte", "line1"),
        ("#ffdc3c", "Goutteur", "dot"),
        ("#3cdc3c", "Plante existante", "ring"),
        ("#ff8c00", "À replanter", "ring"),
    ]
    lh = int(fs * 1.25)
    cols = 3
    leg_h = int(lh * (2.2 + math.ceil(len(leg_items) / cols) + len(lignes) * 0.95) + fs)
    panel = Image.new("RGB", (W, leg_h), "white")
    d2 = ImageDraw.Draw(panel)
    d2.text((fs // 2, fs // 3), "Réseau goutte-à-goutte proposé", font=f_t, fill="#111")
    y0 = int(lh * 1.5)
    cw = W // cols
    for i, (col, txt, kind) in enumerate(leg_items):
        x = fs // 2 + (i % cols) * cw
        y = y0 + (i // cols) * lh
        cy = y + fs // 2
        if kind.startswith("line"):
            d2.line(
                [(x, cy), (x + 2 * fs, cy)],
                fill=col,
                width={"line3": 3, "line2": 2, "line1": 1}[kind] * t,
            )
        elif kind == "dot":
            d2.ellipse(
                [x + fs - t * 2, cy - t * 2, x + fs + t * 2, cy + t * 2],
                fill=col,
                outline="#28140a",
            )
        else:
            d2.ellipse(
                [x + fs // 2, cy - fs // 2, x + fs + fs // 2, cy + fs // 2],
                outline=col,
                width=max(2, t),
            )
        d2.text((x + int(2.4 * fs), y), txt, font=f_n, fill="#222")
    y = y0 + math.ceil(len(leg_items) / cols) * lh + lh // 2
    for l in lignes:
        d2.text(
            (fs // 2, y),
            l,
            font=f_n,
            fill="#0b2e59" if not l.startswith("   ") else "#333",
        )
        y += int(lh * 0.95)
    out = Image.new("RGB", (W, H + leg_h), "white")
    out.paste(pil, (0, 0))
    out.paste(panel, (0, H))
    out.save(path, quality=92)
