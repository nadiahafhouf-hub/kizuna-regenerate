"""Photo redressee annotee : cases, zones, couronnes, herbe, plantes irriguees ou non, trous, tuyaux."""

import numpy as np
import cv2
from .image_analysis import hex_to_rgb


class _Vue:
    """Copie agrandie du terrain pour un dessin lisible (au moins ~1100 px de large)."""

    def __init__(self, T):
        k = max(1, int(np.ceil(1100 / T.w)))
        self.k = k
        rs = lambda a, interp: cv2.resize(a, (T.w * k, T.h * k), interpolation=interp)
        self.rgb = rs(T.rgb, cv2.INTER_CUBIC)
        self.valid = rs(T.valid.astype(np.uint8), cv2.INTER_NEAREST) > 0
        self.seg = rs(
            getattr(T, "seg", np.zeros((T.h, T.w), np.uint8)), cv2.INTER_NEAREST
        )
        lab = getattr(T, "crown_labels", None)
        self.crown_labels = (
            rs(lab.astype(np.float32), cv2.INTER_NEAREST).astype(np.int32)
            if lab is not None
            else None
        )
        self.zone_masks = [
            rs(m.astype(np.uint8), cv2.INTER_NEAREST) > 0 for m in T.zone_masks
        ]
        self.overlay_masks = {
            kk: rs(v.astype(np.uint8), cv2.INTER_NEAREST) > 0
            for kk, v in T.overlay_masks.items()
        }
        self._useless_px = [a * k for a in getattr(T, "_useless_px", [])]
        self.w, self.h = T.w * k, T.h * k
        self.ppm, self.ppm_x, self.ppm_y = T.ppm * k, T.ppm_x * k, T.ppm_y * k
        for a in ("diag", "cfg", "zones", "source"):
            setattr(self, a, getattr(T, a))


def dessin_photo(T, path):
    T = _Vue(T)
    img = T.rgb.copy()
    seg = T.seg
    ov = img.copy()
    ov[seg == 2] = (255, 215, 0)  # vegetation basse (jaune)
    ov[seg == 3] = (0, 200, 90)  # couronnes (vert)
    out = cv2.addWeighted(ov, 0.30, img, 0.70, 0)
    out[~T.valid] = (255, 255, 255)
    out = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    th = max(1, int(T.ppm / 8))
    # contours des couronnes
    lab = getattr(T, "crown_labels", None)
    if lab is not None and lab.any():
        edges = (
            cv2.morphologyEx(
                (lab > 0).astype(np.uint8),
                cv2.MORPH_GRADIENT,
                np.ones((3, 3), np.uint8),
            )
            > 0
        ) | (cv2.Laplacian(lab.astype(np.float32), cv2.CV_32F) != 0) & (lab > 0)
        out[edges] = (40, 120, 40)
    # cases + zones
    d = T.diag
    tc = float(d.get("taille_case_m", 10))
    W, H = T.cfg["dimensions_m"]["largeur"], T.cfg["dimensions_m"]["longueur"]
    fs = float(np.clip(T.ppm * tc / 450, 0.4, 0.9))
    for x in np.arange(0, W + 0.01, tc):
        cv2.line(
            out, (int(x * T.ppm_x), 0), (int(x * T.ppm_x), T.h), (255, 255, 255), 1
        )
    for y in np.arange(0, H + 0.01, tc):
        cv2.line(
            out, (0, int(y * T.ppm_y)), (T.w, int(y * T.ppm_y)), (255, 255, 255), 1
        )
    for zc, m in zip(T.cfg["zones"], T.zone_masks):
        c = hex_to_rgb(zc["couleur"])[::-1].tolist()
        cs, _ = cv2.findContours(
            m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(out, cs, -1, (0, 0, 0), th + 3)
        cv2.drawContours(out, cs, -1, c, th + 1)
    # irrigation existante (tuyaux detectes ou supposes)
    im = T.overlay_masks.get("irrigation")
    if im is not None and im.any():
        o2 = out.copy()
        o2[im] = (230, 120, 20)
        out = cv2.addWeighted(o2, 0.7, out, 0.3, 0)
    for arr in getattr(T, "_useless_px", []):
        for x, y in arr[::2]:
            cv2.circle(out, (int(x), int(y)), th, (200, 0, 200), -1)
    for z in T.zones:
        irr = z["irrigation"]
        cov = irr.get("plantes_couvertes")
        r = z["rangs"]
        if r:
            u, n = np.array(r["u"]), np.array(r["n"])
            for row in r["rows"]:
                p0, p1 = (
                    row["s_min"] * u + row["t"] * n,
                    row["s_max"] * u + row["t"] * n,
                )
                cv2.line(
                    out,
                    (int(p0[0] * T.ppm_x), int(p0[1] * T.ppm_y)),
                    (int(p1[0] * T.ppm_x), int(p1[1] * T.ppm_y)),
                    (0, 220, 255),
                    1,
                )
            for mx, my in r["manquants"]:
                c = (int(mx * T.ppm_x), int(my * T.ppm_y))
                s = int(max(4, T.ppm * 0.7))
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
        for i, p in enumerate(z["plantes"]):
            ok = irr["type"] != "aucun" and (cov is None or cov[i])
            col = (40, 200, 40) if ok else (40, 40, 230)
            rad = max(3, int(min(p["diam_m"], 3) * T.ppm / 6))
            cv2.circle(
                out, (int(p["x"] * T.ppm_x), int(p["y"] * T.ppm_y)), rad, (0, 0, 0), -1
            )
            cv2.circle(
                out,
                (int(p["x"] * T.ppm_x), int(p["y"] * T.ppm_y)),
                max(2, rad - 1),
                col,
                -1,
            )
    for zc, zd in zip(T.cfg["zones"], T.diag.get("zones", [])):
        if zd.get("cases"):
            li, co = zd["cases"][0]
            org = (int(co * tc * T.ppm_x + 6), int(li * tc * T.ppm_y + 28 * fs + 6))
            cv2.putText(
                out,
                zc["nom"],
                org,
                cv2.FONT_HERSHEY_SIMPLEX,
                fs,
                (255, 255, 255),
                int(3 * fs) + 2,
                cv2.LINE_AA,
            )
            cv2.putText(
                out,
                zc["nom"],
                org,
                cv2.FONT_HERSHEY_SIMPLEX,
                fs,
                (20, 20, 20),
                max(1, int(fs)),
                cv2.LINE_AA,
            )
    sx, sy = T.source
    cv2.drawMarker(
        out,
        (int(sx * T.ppm_x), int(sy * T.ppm_y)),
        (0, 0, 200),
        cv2.MARKER_TRIANGLE_UP,
        int(T.ppm * 3),
        th + 2,
    )
    # legende
    wl = max(out.shape[1], 900)
    leg = np.full((70, wl, 3), 255, np.uint8)
    items = [
        ((0, 200, 90), "couronne detectee"),
        ((0, 215, 255), "herbe / vegetation basse"),
        ((40, 200, 40), "plante irriguee"),
        ((40, 40, 230), "plante NON irriguee"),
        ((0, 120, 255), "X manquant"),
        ((230, 120, 20), "tuyau existant"),
        ((200, 0, 200), "tuyau sur sol nu"),
    ]
    for i, (c, t) in enumerate(items):
        x = 10 + (i % 4) * (wl // 4)
        y = 25 + (i // 4) * 30
        cv2.circle(leg, (x + 8, y - 5), 7, c, -1)
        cv2.putText(
            leg,
            t,
            (x + 22, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )
    if out.shape[1] < wl:
        out = cv2.copyMakeBorder(
            out, 0, 0, 0, wl - out.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)
        )
    cv2.imwrite(str(path), np.vstack([out, leg]))
