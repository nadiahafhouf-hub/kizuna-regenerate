"""Images : analyse de l'existant (sur la photo/plan) et plan du systeme optimal (en metres)."""

import numpy as np
import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Rectangle, FancyArrow
from matplotlib.lines import Line2D
from .crops import MOIS
from .image_analysis import hex_to_rgb

SECT_COLORS = [
    "#1f6feb",
    "#d1242f",
    "#8250df",
    "#1a7f37",
    "#bf8700",
    "#0a7d8c",
    "#cf222e",
    "#6639ba",
]


def dessin_existant(T, path):
    img = T.rgb.copy()
    out = (img * 0.55 + 255 * 0.45).astype(np.uint8)
    out = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    for m in T.zone_masks:
        cs, _ = cv2.findContours(
            m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(out, cs, -1, (60, 60, 60), 2)
    th = max(1, int(T.ppm / 8))
    im = T.overlay_masks.get("irrigation")
    if im is not None:
        ov = out.copy()
        ov[im] = (230, 120, 20)
        out = cv2.addWeighted(ov, 0.8, out, 0.2, 0)
    # lignes inutiles
    for arr in getattr(T, "_useless_px", []):
        for x, y in arr:
            cv2.circle(out, (int(x), int(y)), th + 1, (200, 0, 200), -1)
    for z in T.zones:
        r = z["rangs"]
        irr = z["irrigation"]
        if irr["type"] == "aspersion":
            for hx, hy in irr.get("asperseurs", []):
                cv2.circle(
                    out,
                    (int(hx * T.ppm_x), int(hy * T.ppm_y)),
                    int(irr["rayon_m"] * T.ppm),
                    (200, 160, 0),
                    th,
                )
        if r:
            u, n = np.array(r["u"]), np.array(r["n"])
            for row in r["rows"]:
                p0 = row["s_min"] * u + row["t"] * n
                p1 = row["s_max"] * u + row["t"] * n
                cv2.line(
                    out,
                    (int(p0[0] * T.ppm_x), int(p0[1] * T.ppm_y)),
                    (int(p1[0] * T.ppm_x), int(p1[1] * T.ppm_y)),
                    (0, 200, 230),
                    th,
                )
            for mx, my in r["manquants"]:
                c = (int(mx * T.ppm_x), int(my * T.ppm_y))
                s = int(max(4, T.ppm * 0.6))
                cv2.line(
                    out,
                    (c[0] - s, c[1] - s),
                    (c[0] + s, c[1] + s),
                    (0, 120, 255),
                    th + 1,
                )
                cv2.line(
                    out,
                    (c[0] - s, c[1] + s),
                    (c[0] + s, c[1] - s),
                    (0, 120, 255),
                    th + 1,
                )
        cov = irr.get("plantes_couvertes")
        for i, p in enumerate(z["plantes"]):
            ok = True if cov is None else cov[i]
            if irr["type"] in ("aucun",):
                ok = False
            col = (40, 170, 40) if ok else (30, 30, 220)
            rad = max(3, int(p["diam_m"] * T.ppm / 2))
            cv2.circle(
                out,
                (int(p["x"] * T.ppm_x), int(p["y"] * T.ppm_y)),
                rad,
                col,
                max(1, th),
            )
        if z["centre"]:
            cx, cy = int(z["centre"][0] * T.ppm_x), int(z["centre"][1] * T.ppm_y)
            fs = max(0.5, T.ppm / 25)
            cv2.putText(
                out,
                z["nom"],
                (cx - int(len(z["nom"]) * 6 * fs), cy),
                cv2.FONT_HERSHEY_SIMPLEX,
                fs,
                (255, 255, 255),
                int(4 * fs) + 2,
                cv2.LINE_AA,
            )
            cv2.putText(
                out,
                z["nom"],
                (cx - int(len(z["nom"]) * 6 * fs), cy),
                cv2.FONT_HERSHEY_SIMPLEX,
                fs,
                (20, 20, 20),
                int(2 * fs) + 1,
                cv2.LINE_AA,
            )
    sx, sy = T.source
    cv2.drawMarker(
        out,
        (int(sx * T.ppm_x), int(sy * T.ppm_y)),
        (180, 0, 0),
        cv2.MARKER_TRIANGLE_UP,
        int(T.ppm * 3),
        th + 2,
    )
    # legende
    h = out.shape[0]
    pad = 10
    leg = np.full((int(max(120, h * 0.12)), out.shape[1], 3), 255, np.uint8)
    items = [
        ((40, 170, 40), "plante irriguee"),
        ((30, 30, 220), "plante NON irriguee"),
        ((0, 120, 255), "X plante manquante"),
        ((0, 200, 230), "rang detecte"),
        ((230, 120, 20), "ligne/asperseur existant"),
        ((200, 0, 200), "ligne sur sol nu (gaspillage)"),
        ((180, 0, 0), "source d'eau"),
    ]
    fs = max(0.45, out.shape[1] / 2400)
    colw = out.shape[1] // 4
    for i, (c, t) in enumerate(items):
        x = pad + (i % 4) * colw
        y = int(30 * fs * 1.6) + (i // 4) * int(40 * fs * 1.6)
        cv2.circle(leg, (x + 10, y - 6), 8, c, -1)
        cv2.putText(
            leg,
            t,
            (x + 26, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            fs,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )
    out = np.vstack([out, leg])
    cv2.imwrite(str(path), out)


def plan_optimal(T, C, path, titre="Plan d'irrigation optimal"):
    W, H = T.cfg["dimensions_m"]["largeur"], T.cfg["dimensions_m"]["longueur"]
    fig_w = 16
    fig, ax = plt.subplots(figsize=(fig_w, fig_w * H / W + 1.6), dpi=150)
    ax.set_xlim(-1, W * 1.08 + 1)
    ax.set_ylim(H + 1, -1)
    ax.set_aspect("equal")
    ax.add_patch(Rectangle((0, 0), W, H, fill=False, lw=1.5, ec="#333"))
    photo = getattr(T, "photo_info", {}).get("fournie")
    if photo:  # photo redressee en fond, attenuee
        fond = (T.rgb.astype(np.float32) * 0.55 + 255 * 0.45).astype(np.uint8)
        ax.imshow(fond, extent=[0, W, H, 0], zorder=0)
    diag = getattr(T, "diag", None)
    if diag:  # grille des cases du diagnostic
        tc = float(diag.get("taille_case_m", 10))
        for x in np.arange(0, W + 0.01, tc):
            ax.axvline(x, color="#777", lw=0.4, ls=":", zorder=1)
        for y in np.arange(0, H + 0.01, tc):
            ax.axhline(y, color="#777", lw=0.4, ls=":", zorder=1)

    def contours(mask):
        cs, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return [
            np.column_stack([c[:, 0, 0] / T.ppm_x, c[:, 0, 1] / T.ppm_y])
            for c in cs
            if len(c) > 2
        ]

    for z, m in zip(T.cfg["zones"], T.zone_masks):
        col = hex_to_rgb(z["couleur"]) / 255
        for c in contours(m):
            ax.add_patch(
                Polygon(
                    c,
                    closed=True,
                    fc=(*col, 0.18 if photo else 0.35),
                    ec=(*col * 0.6, 1),
                    lw=2 if photo else 1,
                    zorder=1,
                )
            )
    for z, m in zip(T.cfg.get("zones_exclues", []), T.excl_masks):
        for c in contours(m):
            ax.add_patch(
                Polygon(c, closed=True, fc="#dddddd", ec="#999", lw=0.8, hatch="//")
            )

    tiny = sum(len(z.get("rampes", [])) for z in C.zones) > 400
    s_idx = 0
    for z in C.zones:
        if z.get("vide"):
            continue
        # plantes
        for x, y in (
            z.get("plantes_existantes", []) if z["type"] != "maraichage" else []
        ):
            ax.add_patch(
                Circle(
                    (x, y),
                    0.45 if z["type"] != "arbre" else 0.9,
                    fc="#2e7d32",
                    ec="#1b5e20",
                    lw=0.5,
                    zorder=4,
                )
            )
        for x, y in z.get("plantes_a_planter", []):
            new = z.get("mode") == "nouvelle_plantation"
            ax.add_patch(
                Circle(
                    (x, y),
                    0.9 if z["type"] == "arbre" else 0.45,
                    fc="#c8e6c9" if new else "#ffe0b2",
                    ec="#43a047" if new else "#ef6c00",
                    lw=1.2,
                    zorder=4,
                )
            )
        for k, s in enumerate(z["secteurs"]):
            col = SECT_COLORS[s_idx % len(SECT_COLORS)]
            s_idx += 1
            s["label"] = f"S{s_idx}"
            s["couleur"] = col
            if z.get("mode") == "aspersion":
                for hx, hy in s["porte_rampe"]:
                    ax.add_patch(
                        Circle(
                            (hx, hy), z["rayon_m"], fc=col, alpha=0.08, ec=col, lw=0.4
                        )
                    )
                    ax.plot(hx, hy, "o", color=col, ms=4, zorder=5)
                pr = np.array(s["porte_rampe"])
                ax.plot(pr[:, 0], pr[:, 1], "-", color=col, lw=1.8, zorder=3)
        if z.get("mode") != "aspersion":
            u, n = np.array(z["u"]), np.array(z["n"])
            sec_t = []
            for s in z["secteurs"]:
                ts = [np.array(p) @ n for p in s["porte_rampe"]]
                sec_t.append(
                    (
                        min(ts) - 0.5 * z["ecart_rang_m"],
                        max(ts) + 0.5 * z["ecart_rang_m"],
                        s["couleur"],
                    )
                )
            for l in z["rampes"]:
                col = next((c for a, b, c in sec_t if a <= l["t"] <= b), "#1f6feb")
                ax.plot(
                    [l["p0"][0], l["p1"][0]],
                    [l["p0"][1], l["p1"][1]],
                    "-",
                    color=col,
                    lw=0.6 if tiny else 0.9,
                    zorder=3,
                )
            for s in z["secteurs"]:
                pr = np.array(s["porte_rampe"])
                if len(pr) > 1:
                    ax.plot(
                        pr[:, 0],
                        pr[:, 1],
                        "-",
                        color=s["couleur"],
                        lw=3,
                        zorder=5,
                        solid_capstyle="round",
                    )
            # goutteurs (arbres) : points autour de chaque arbre
            if z["type"] in ("arbre", "arbuste"):
                per_line = max(
                    1, int(round(z["goutteurs_par_plante"] / z["lignes_par_rang"]))
                )
                se = z["espacement_goutteurs_m"]
                off_m = z.get("decalage_rampe_m", 0.0)
                trees = list(z.get("plantes_existantes", [])) + list(
                    z.get("plantes_a_planter", [])
                )
                xs, ys = [], []
                for x, y in trees:
                    p = np.array([x, y])
                    for o in ([-off_m, off_m] if z["lignes_par_rang"] == 2 else [0.0]):
                        for e in range(per_line):
                            q = p + (e - (per_line - 1) / 2) * se * u + o * n
                            xs.append(q[0])
                            ys.append(q[1])
                ax.plot(xs, ys, ".", color="#0d47a1", ms=1.6, zorder=6)
    # conduite principale
    for seg in C.principal["segments"]:
        a = np.array(seg)
        ax.plot(
            a[:, 0],
            a[:, 1],
            "-",
            color="#0b2e59",
            lw=4.2,
            zorder=7,
            solid_capstyle="round",
        )
    for z in C.zones:
        if z.get("vide"):
            continue
        for s in z["secteurs"]:
            vx, vy = s["vanne"]
            vs = min(1.8, 0.03 * min(W, H) + 0.3)
            ax.add_patch(
                Rectangle(
                    (vx - vs / 2, vy - vs / 2),
                    vs,
                    vs,
                    fc=s["couleur"],
                    ec="black",
                    lw=1,
                    zorder=8,
                )
            )
            ax.annotate(
                s["label"],
                (vx, vy),
                xytext=(6, -6),
                textcoords="offset points",
                fontsize=9,
                weight="bold",
                color=s["couleur"],
                zorder=9,
                bbox=dict(
                    boxstyle="round,pad=0.15", fc="white", ec=s["couleur"], lw=0.8
                ),
            )
    sx, sy = T.source
    ax.plot(sx, sy, marker="^", color="#b71c1c", ms=16, mec="black", zorder=10)
    ax.annotate(
        "Pompe + filtration\n+ fertigation",
        (sx, sy),
        xytext=(-20, -34),
        textcoords="offset points",
        fontsize=8,
        zorder=10,
        bbox=dict(boxstyle="round", fc="white", ec="#b71c1c"),
    )
    for zi in T.zones:
        if zi["centre"]:
            ax.text(
                zi["centre"][0],
                zi["centre"][1],
                zi["nom"],
                ha="center",
                va="center",
                fontsize=10,
                weight="bold",
                color="#222",
                zorder=11,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75),
            )
    # echelle + nord
    L = 10 if W >= 40 else 5
    ax.add_patch(Rectangle((1, H - 2.2), L, 0.6, fc="black", zorder=12))
    ax.text(1 + L / 2, H - 2.6, f"{L} m", ha="center", fontsize=9, zorder=12)
    al = 0.08 * min(W, H) + 1
    ax.add_patch(
        FancyArrow(
            W + 0.04 * W,
            1.2 * al + 1,
            0,
            -al,
            width=al * 0.1,
            head_width=al * 0.4,
            head_length=al * 0.35,
            fc="black",
            zorder=12,
            clip_on=False,
        )
    )
    ax.text(
        W + 0.04 * W,
        1.2 * al + 1 + al * 0.45,
        "N",
        ha="center",
        fontsize=11,
        weight="bold",
        zorder=12,
    )
    handles = [
        Line2D(
            [],
            [],
            color="#0b2e59",
            lw=4,
            label=f"Conduite principale PE {C.principal['diam_mm']} mm",
        ),
        Line2D([], [], color="#1f6feb", lw=3, label="Porte-rampe (couleur = secteur)"),
        Line2D([], [], color="#1f6feb", lw=1, label="Rampe goutte-a-goutte"),
        Line2D(
            [],
            [],
            marker="s",
            color="w",
            mfc="#888",
            mec="k",
            ms=9,
            label="Vanne de secteur",
        ),
        Line2D(
            [], [], marker="o", color="w", mfc="#2e7d32", ms=8, label="Plante existante"
        ),
        Line2D(
            [],
            [],
            marker="o",
            color="w",
            mfc="#ffe0b2",
            mec="#ef6c00",
            ms=8,
            label="A replanter",
        ),
        Line2D(
            [],
            [],
            marker="o",
            color="w",
            mfc="#c8e6c9",
            mec="#43a047",
            ms=8,
            label="Nouvelle plantation",
        ),
        Line2D([], [], marker=".", color="w", mfc="#0d47a1", ms=8, label="Goutteur"),
        Line2D(
            [],
            [],
            marker="^",
            color="w",
            mfc="#b71c1c",
            mec="k",
            ms=10,
            label="Source / station de tete",
        ),
    ]
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.04),
        ncol=5,
        fontsize=8,
        frameon=False,
    )
    ax.set_title(titre, fontsize=14, weight="bold")
    ax.set_xlabel("m")
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def graphique_mensuel(bilan, path):
    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=150)
    x = np.arange(12)
    w = 0.38
    ax.bar(
        x - w / 2, bilan["mensuel_actuel"], w, label="Actuel (estime)", color="#d1242f"
    )
    ax.bar(
        x + w / 2,
        bilan["mensuel_optimal"],
        w,
        label="Optimise (zones existantes)",
        color="#1f6feb",
    )
    ax.plot(
        x + w / 2,
        bilan["mensuel_rdi"],
        "o-",
        color="#1a7f37",
        ms=4,
        lw=1.5,
        label="Optimise + RDI",
    )
    ax.set_xticks(x, MOIS)
    ax.set_ylabel("m3 / mois")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
