"""Dessin PNG du plan recommande (matplotlib), textes en anglais comme le site. Sans Django.

Zones colorees, symbole de chaque plante, lignes de goutte-a-goutte, UNE vanne par zone,
reservoir, pompe, panneaux solaires.
"""
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

FOND = {"ROUGE": "#f4c7c3", "ORANGE": "#fde0b5", "VERT": "#d4edc9"}
VIF = {"ROUGE": "#c0392b", "ORANGE": "#e67e22", "VERT": "#27ae60"}
COULEUR_EN = {"ROUGE": "RED", "ORANGE": "ORANGE", "VERT": "GREEN"}
TEXTURE_EN = {"sablo-limoneux": "sandy loam", "sableux": "sandy", "sable": "sandy", "limoneux": "loamy",
              "limono-argileux": "clay loam", "argileux": "clay", "argile": "clay"}


def _texture(t):
    return TEXTURE_EN.get((t or "").lower(), t or "?")


def _source(c):
    return (c.get("detail_source") or c["source"]).replace("table de secours", "fallback table").replace("region la plus proche", "nearest region")
TUYAU = "#1f4e9c"
GOUTTE = "#3a7bd5"
MAX_LIGNES_PAR_CASE = 5


def dessiner_plan(reco, sortie, **_):
    t = reco["taille_case_m"]
    cases = reco["cases"]
    ncol = max((c["col"] for c in cases), default=0) + 1
    nlig = max((c["ligne"] for c in cases), default=0) + 1
    L = reco.get("largeur_m") or ncol * t
    H = reco.get("longueur_m") or nlig * t
    zones = {z["id"]: z for z in reco["zones"]}

    fig = Figure(figsize=(16, 9.5))
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.03, 0.12, 0.55, 0.80])
    ax.set_xlim(-10, L + 1.5)
    ax.set_ylim(-4, H + 1.5)
    ax.set_aspect("equal")
    ax.axis("off")

    # --- cases : fond, plantes, goutte-a-goutte ---
    lignes_goutte = []
    points = {zid: ([], []) for zid in zones}
    for c in cases:
        z = zones.get(c["zone_id"])
        x0, y0 = c["col"] * t, H - (c["ligne"] + 1) * t
        ax.add_patch(Rectangle((x0, y0), t, t, fc=FOND.get(c["couleur"], "#eee"), ec="#555", lw=1.2))
        ax.text(x0 + t - 0.3, y0 + t - 0.4, c["id"], ha="right", va="top", fontsize=9, color="#333")
        if not z:
            continue
        # Le plan reste lisible, le nombre réel figure dans la légende.
        n = min(MAX_LIGNES_PAR_CASE, max(1, int(t // z["espacement_m"])))
        xs, ys = points[z["id"]]
        for i in range(n):
            y = y0 + t / n * (i + 0.5)
            lignes_goutte.append([(x0 + 0.8, y), (x0 + t - 0.3, y)])
            for j in range(n):
                xs.append(x0 + 0.5 + (t - 0.5) / n * (j + 0.5))
                ys.append(y)
        # rampe d'alimentation de la case (bord ouest), couleur de la vanne de sa zone
        ax.add_patch(Rectangle((x0 + 0.1, y0 + 0.2), 0.5, t - 0.4, fc=VIF[z["couleur"]], ec="none", zorder=2))
        ax.text(x0 + 0.9, y0 + t / 2, f"V-{z['id']}", rotation=90, va="center", fontsize=7,
                color=VIF[z["couleur"]], weight="bold", zorder=6,
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.4))
        if z["collecte_drainage"]:
            ax.plot([x0 + 0.8, x0 + t - 0.2], [y0 + 0.7, y0 + 0.7], color="#6b3e1f", lw=3, ls="--", zorder=4)

    ax.add_collection(LineCollection(lignes_goutte, colors=GOUTTE, linewidths=0.8, zorder=2))
    for zid, (xs, ys) in points.items():
        z = zones[zid]
        taille = min(80, 7200 / max(1, len(cases)))
        ax.scatter(xs, ys, marker=z["marqueur"], s=taille, color=z["couleur_plante"],
                   edgecolor="white", linewidth=0.4, zorder=3)

    # --- conduite principale + une vanne par zone (nourrice sur la conduite) ---
    xm = -1.5
    ax.plot([xm, xm], [0, H], color=TUYAU, lw=4, zorder=4)
    pas_v = min(2.0, (H - 8) / max(1, len(reco["zones"])))
    for k, z in enumerate(reco["zones"]):
        yv = H - 6.5 - k * pas_v          # sous l'arrivee du reservoir (H - 4)
        ax.add_patch(Rectangle((xm - 0.45, yv - 0.45), 0.9, 0.9, fc="#222", ec=VIF[z["couleur"]], lw=2, zorder=6))
        ax.text(xm - 0.7, yv, f"V-{z['id']}", ha="right", va="center", fontsize=8, weight="bold", zorder=7)
    for z in reco["zones"]:
        # etiquette de zone (besoin) au centre de sa premiere case
        l0, c0 = sorted(z["cases"])[0]
        ax.text(c0 * t + t / 2 + 0.4, H - (l0 + 1) * t + 1.6, f"{z['id']} - {z['besoin_litres_jour']} L/day",
                ha="center", fontsize=9, weight="bold", zorder=7,
                bbox=dict(fc="white", ec=VIF[z["couleur"]], alpha=0.9, pad=1.5))

    # --- reservoir, pompe, panneaux solaires ---
    ax.add_patch(Circle((-6, H - 4), 1.8, fc="#9ec9f5", ec=TUYAU, lw=2))
    ax.text(-6, H - 4, "Elevated\ntank", ha="center", va="center", fontsize=7.5)
    ax.plot([-4.2, xm], [H - 4, H - 4], color=TUYAU, lw=3)
    ax.text(-3, H - 3.4, "gravity", fontsize=7, color=TUYAU, ha="center")
    ax.add_patch(FancyBboxPatch((-7.1, H / 2 - 1), 2.2, 2, boxstyle="round,pad=0.1", fc="#ddd", ec="#333"))
    ax.text(-6, H / 2, "Pump\n(groundwater)", ha="center", va="center", fontsize=7.5)
    ax.plot([-6, -6], [H / 2 + 1.1, H - 5.8], color=TUYAU, lw=3)
    for k in range(3):
        ax.add_patch(Rectangle((-9 + k * 1.8, 1), 1.5, 2.6, fc="#24356b", ec="#9ab", lw=1))
    ax.text(-6.5, 0.2, "Solar panels", ha="center", fontsize=8)
    ax.plot([-6, -6], [3.7, H / 2 - 1.1], color="#e0a800", lw=1.5, ls=":")
    ax.text(L / 2, -3.2, f"Parcel {reco['parcelle_id']}: {L} m x {H} m, cells {t} x {t} m, "
            f"{_texture(reco.get('texture_sol'))} soil  -  North up", ha="center", fontsize=9, color="#444")
    ax.set_title(f"Recommended layout (bare land) - {reco['parcelle_id']} - {reco.get('region')} - "
                 f"measured {reco.get('date_mesure')}", fontsize=14, weight="bold", loc="left")

    # --- legende ---
    hdl = []
    for z in reco["zones"]:
        lab = z["culture"] + ("" if z["alimentaire"] else "  (NON-FOOD)")
        if lab not in [h.get_label() for h in hdl]:
            hdl.append(Line2D([], [], marker=z["marqueur"], color=z["couleur_plante"], ls="", ms=9, label=lab))
    hdl += [Line2D([], [], color=GOUTTE, lw=1.5, label="Drip line"),
            Line2D([], [], marker="s", color="#222", ls="", ms=7, label="Valve (1 per zone)"),
            Line2D([], [], color="#6b3e1f", lw=2.5, ls="--", label="Drainage collection (red zone)")]
    ax.legend(handles=hdl, loc="upper left", bbox_to_anchor=(0.0, -0.02), ncol=2, fontsize=8, frameon=False)

    # --- panneau de droite ---
    clim = reco["climat"]
    ax2 = fig.add_axes([0.60, 0.06, 0.38, 0.86])
    ax2.axis("off")
    ax2.text(0, 1.0, f"Climate - {reco.get('region')}", fontsize=13, weight="bold", va="top")
    ax2.text(0.02, 0.955, f"Rain {clim['pluie_mm']} mm/yr  |  winter min {clim['tmin_hiver']} C  |  "
             f"summer max {clim['tmax_ete']} C  |  ET0 {clim['et0_mm_jour']} mm/day", fontsize=8.5, va="top")
    ax2.text(0.02, 0.925, f"Source: {_source(clim)}", fontsize=8, color="#666", va="top")
    ax2.text(0, 0.88, "Recommendation per zone", fontsize=13, weight="bold", va="top")
    y = 0.83
    for z in reco["zones"]:
        ax2.add_patch(Rectangle((0, y - 0.035), 0.025, 0.04, fc=VIF[z["couleur"]], transform=ax2.transAxes))
        titre = f"{z['id']} ({COULEUR_EN.get(z['couleur'], z['couleur'])}, {z['surface_m2']} m2)  {z['culture']}"
        if len(titre) > 58:
            titre = titre[:56] + "..."
        ax2.text(0.04, y, titre, fontsize=9.5, weight="bold", va="top")
        info = f"{z['nb_plants']} plants  |  {z['besoin_litres_jour']} L/day  |  max EC {z['ce_max_dS_m']} dS/m"
        info += "  |  decided by " + z["decide_par"].replace("bloc", "Block")
        ax2.text(0.04, y - 0.03, info, fontsize=8, color="#444", va="top")
        info2 = []
        if z["alternatives"]:
            info2.append("alternatives: " + ", ".join(a["nom"] for a in z["alternatives"]))
        if z["microbes"]:
            info2.append(", ".join(z["microbes"]))
        if not z["alimentaire"]:
            info2.append("DO NOT EAT")
        if z["collecte_drainage"]:
            info2.append("no leaching + drainage collection")
        if info2:
            ax2.text(0.04, y - 0.055, "  |  ".join(info2), fontsize=7.5, color="#444", va="top")
        y -= 0.09
    y -= 0.01
    tex = reco["texture"]
    ax2.text(0, y, "Irrigation", fontsize=12, weight="bold", va="top")
    lignes = [f"Estimated total water need: {reco['besoin_total_litres_jour'] / 1000:.2f} m3/day",
              f"{_texture(reco.get('texture_sol')).capitalize()} soil: {tex['arrosages']} watering(s) per day, at dawn",
              "Groundwater -> tank pumping in sunny hours (solar pump)",
              "Tank -> zones by gravity, one valve per zone",
              "Red zone: no leaching (cadmium must not reach the groundwater)"]
    for i, l in enumerate(lignes):
        ax2.text(0.02, y - 0.04 - i * 0.03, l, fontsize=8.5, va="top")
    ax2.text(0, -0.05, "Simulated data - hackathon prototype - estimates, not measurements",
             fontsize=8, style="italic", color="#888")
    fig.savefig(sortie, dpi=110)
    return dict(png=str(sortie), pdf=None, fond="aucun")
