"""Vision sur photo reelle (drone, satellite, Google Earth, photo oblique redressee).

Etapes :
  1. chargement robuste (JPEG/PNG/GeoTIFF, orientation EXIF, zones sans donnee) ;
  2. redressement par homographie (4 coins de la parcelle) -> vue de dessus a l'echelle ;
  3. segmentation sol / couronnes d'arbres / vegetation basse (adventices, culture basse) ;
  4. separation des couronnes (distance + watershed) -> 1 point par arbre ;
  5. rangs de cultures basses par profil de projection (rangs continus non separables) ;
  6. detection des tuyaux noirs de goutte-a-goutte (seulement si resolution suffisante).
"""

import math
import numpy as np
import cv2
from PIL import Image, ImageOps
from scipy import ndimage
from skimage.feature import peak_local_max
from skimage.segmentation import watershed
from skimage.filters import sato

Image.MAX_IMAGE_PIXELS = 400_000_000


# ------------------------------------------------------------------ chargement
def charger_photo(path):
    """Retourne (rgb uint8, masque_valide bool, resolution_m_par_px ou None)."""
    im = Image.open(path)
    res = None
    try:  # GeoTIFF : ModelPixelScaleTag
        sc = im.tag_v2.get(33550)
        if sc:
            res = float(sc[0])
    except Exception:
        pass
    im = ImageOps.exif_transpose(im)
    alpha = None
    if im.mode in ("RGBA", "LA"):
        alpha = np.array(im.split()[-1]) > 0
    rgb = np.array(im.convert("RGB"))
    valid = ~(
        (rgb.min(2) >= 250) | (rgb.max(2) <= 3)
    )  # blanc / noir pur = pas de donnee
    if alpha is not None:
        valid &= alpha
    return rgb, valid, res


# ------------------------------------------------------------------ redressement
def redresser(rgb, valid, coins_px, largeur_m, longueur_m, ppm):
    """coins_px : [[x,y] NO, NE, SE, SO] dans la photo. Sortie : image vue de dessus, ppm pixels/m."""
    W, H = int(round(largeur_m * ppm)), int(round(longueur_m * ppm))
    src = np.float32(coins_px)
    dst = np.float32([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]])
    Hm = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(
        rgb, Hm, (W, H), flags=cv2.INTER_AREA, borderValue=(255, 255, 255)
    )
    v = (
        cv2.warpPerspective(
            valid.astype(np.uint8), Hm, (W, H), flags=cv2.INTER_NEAREST, borderValue=0
        )
        > 0
    )
    return out, v, Hm


def resolution_native(coins_px, largeur_m, longueur_m):
    c = np.float32(coins_px)
    top = np.linalg.norm(c[1] - c[0]) / largeur_m
    left = np.linalg.norm(c[3] - c[0]) / longueur_m
    bot = np.linalg.norm(c[2] - c[3]) / largeur_m
    right = np.linalg.norm(c[2] - c[1]) / longueur_m
    return float(min(top, left, bot, right)), float(max(top, left, bot, right))


# ------------------------------------------------------------------ segmentation
def _features(rgb, ppm):
    sig = max(0.6, 0.08 * ppm)  # lissage ~8 cm
    f = rgb.astype(np.float32)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    s = f.sum(2) + 30.0  # +30 : evite que les pixels tres sombres aient un ExG aberrant
    r, g, b = f[..., 0] / s, f[..., 1] / s, f[..., 2] / s
    exg = 2 * g - r - b
    exr = 1.4 * r - g
    L = cv2.GaussianBlur(lab[..., 0], (0, 0), sig)
    A = cv2.GaussianBlur(lab[..., 1], (0, 0), sig)
    E = cv2.GaussianBlur(exg - exr, (0, 0), sig)  # ExGR (Meyer & Neto 2008)
    return L, A, E


def _disk(r):
    r = max(1, int(r))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def segmenter(rgb, valid, ppm, diam_max_m=6.0, mode="arbres"):
    """Classes : 0 = sans donnee, 1 = sol nu, 2 = vegetation basse (herbe, adventices, culture basse),
    3 = couronne d'arbre / arbuste.

    mode "arbres" : une couronne est une tache plus SOMBRE que son voisinage (chapeau haut-de-forme noir
      sur la luminance, a l'echelle de la couronne). Independant de la couleur du sol (sable, terre, herbe)
      et de l'eclairage global : marche sur orthophoto drone, satellite, Google Earth.
    mode "basse" : la vegetation est detectee par sa couleur (indice ExGR), seuil d'Otsu.
    Le sol restant est ensuite separe en sol nu / vegetation basse par sa couleur (2 groupes).
    """
    L, A, E = _features(rgb, ppm)
    fill = float(np.median(L[valid])) if valid.any() else 128.0
    Lf = np.where(valid, L, fill).astype(np.float32)
    seg = np.zeros(rgb.shape[:2], np.uint8)
    seg[valid] = 1
    info = {"mode": mode}
    if mode == "arbres":
        r = 0.65 * diam_max_m * ppm
        # fermeture a grande echelle sur image reduite (rapide), puis remise a l'echelle
        f = max(1, int(ppm / 3))
        small = cv2.resize(
            Lf, (Lf.shape[1] // f, Lf.shape[0] // f), interpolation=cv2.INTER_AREA
        )
        clo = cv2.morphologyEx(small, cv2.MORPH_CLOSE, _disk(r / f))
        clo = cv2.resize(
            clo, (Lf.shape[1], Lf.shape[0]), interpolation=cv2.INTER_LINEAR
        )
        th = np.clip(clo - Lf, 0, None)
        v = th[valid]
        u8 = np.clip(v / max(np.percentile(v, 99.5), 1e-3) * 255, 0, 255).astype(
            np.uint8
        )
        t, _ = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr = max(t / 255 * max(np.percentile(v, 99.5), 1e-3), 10.0)
        crown = (th > thr) & valid
        # une couronne est verte (rejette ombres portees sur sol nu et objets sombres non vegetaux)
        ground = valid & ~crown
        a_g = np.median(A[ground]) if ground.any() else 128
        crown &= ~(A > a_g + 2.0)
        info["seuil_contraste"] = float(thr)
    else:
        v = E[valid]
        u8 = np.clip((v - v.min()) / (np.ptp(v) + 1e-6) * 255, 0, 255).astype(np.uint8)
        t, _ = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr = v.min() + t / 255 * np.ptp(v)
        crown = (E > max(thr, -0.02)) & valid
        info["seuil_exgr"] = float(thr)
    k = _disk(0.12 * ppm)
    crown = cv2.morphologyEx(crown.astype(np.uint8), cv2.MORPH_OPEN, k)
    crown = cv2.morphologyEx(crown, cv2.MORPH_CLOSE, k)
    crown = ndimage.binary_fill_holes(crown > 0) & valid
    seg[crown] = 3 if mode == "arbres" else 2
    # sol nu / vegetation basse sur le reste
    ground = valid & ~crown
    if mode == "arbres" and ground.sum() > 200:
        X = np.stack([A[ground], E[ground] * 100, L[ground]], 1).astype(np.float32)
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 1e-3)
        _, lab, C = cv2.kmeans(X, 2, None, crit, 3, cv2.KMEANS_PP_CENTERS)
        green = int(np.argmin(C[:, 0] - C[:, 1] / 10))
        other = 1 - green
        dA = C[other, 0] - C[green, 0]
        info.update(ecart_a_sol_herbe=float(dA))
        if dA > 2.0:  # nettement plus vert : herbe / adventices
            gm = np.zeros_like(ground)
            gm[ground] = lab.ravel() == green
            gm = (
                cv2.morphologyEx(gm.astype(np.uint8), cv2.MORPH_OPEN, _disk(0.25 * ppm))
                > 0
            )
            seg[gm & ground] = 2
    info["part_couronnes"] = float((seg == 3).sum() / max(valid.sum(), 1))
    info["part_vegetation_basse"] = float((seg == 2).sum() / max(valid.sum(), 1))
    return seg, info


# ------------------------------------------------------------------ couronnes
def couronnes(seg, ppm, espacement_min_m, diam_min_m=0.6):
    """Separe les couronnes qui se touchent. Retourne liste de dicts (x_px, y_px, diam_m, aire_m2) et labels."""
    crown = seg == 3
    dist = ndimage.distance_transform_edt(crown)
    dist = cv2.GaussianBlur(dist.astype(np.float32), (0, 0), max(1.0, 0.1 * ppm))
    md = max(2, int(0.45 * espacement_min_m * ppm))
    peaks = peak_local_max(
        dist,
        min_distance=md,
        threshold_abs=0.5 * diam_min_m / 2 * ppm,
        labels=ndimage.label(crown)[0],
        exclude_border=False,
    )
    markers = np.zeros(crown.shape, np.int32)
    for i, (y, x) in enumerate(peaks, 1):
        markers[y, x] = i
    labels = watershed(-dist, markers, mask=crown)
    out = []
    for i, (y, x) in enumerate(peaks, 1):
        m = labels == i
        a = m.sum()
        if a < math.pi * (diam_min_m / 2) ** 2 * ppm**2:
            labels[m] = 0
            continue
        ys, xs = np.nonzero(m)
        out.append(
            {
                "x_px": float(xs.mean()),
                "y_px": float(ys.mean()),
                "aire_m2": a / ppm**2,
                "diam_m": 2 * math.sqrt(a / math.pi) / ppm,
                "label": i,
            }
        )
    return out, labels


# ------------------------------------------------------------------ rangs continus (culture basse)
def rangs_par_projection(veg, zone_mask, ppm, ecart_min_m, ecart_max_m):
    """Cultures en rangs continus : cherche l'angle qui maximise le contraste du profil de projection."""
    ys, xs = np.nonzero(zone_mask)
    if len(xs) < 100:
        return None
    vx, vy = np.nonzero(veg & zone_mask)[1], np.nonzero(veg & zone_mask)[0]
    if len(vx) < 50:
        return None
    best = None
    for ang in np.arange(0, 180, 1.0):
        th = math.radians(ang)
        n = np.array([-math.sin(th), math.cos(th)])
        tz = (xs * n[0] + ys * n[1]) / ppm
        tv = (vx * n[0] + vy * n[1]) / ppm
        bins = np.arange(tz.min(), tz.max() + 0.05, 0.05)
        hz, _ = np.histogram(tz, bins)
        hv, _ = np.histogram(tv, bins)
        prof = np.where(hz > 0, hv / np.maximum(hz, 1), 0)
        prof = prof - prof.mean()
        # energie spectrale dans la bande des ecartements plausibles
        F = np.abs(np.fft.rfft(prof))
        fr = np.fft.rfftfreq(len(prof), 0.05)
        band = (fr >= 1 / ecart_max_m) & (fr <= 1 / ecart_min_m)
        if not band.any():
            continue
        j = np.argmax(F * band)
        sc = F[j] / (F[1:].sum() + 1e-6)
        if best is None or sc > best[0]:
            best = (sc, ang, 1 / fr[j], prof, bins)
    if best is None:
        return None
    sc, ang, period, prof, bins = best
    return {"angle_deg": float(ang), "ecart_m": float(period), "nettete": float(sc)}


# ------------------------------------------------------------------ tuyaux goutte-a-goutte
def tuyaux(rgb_native, valid_native, ppm_native, veg_native=None, longueur_min_m=2.0):
    """Lignes sombres fines et rectilignes (PE noir 16-20 mm). Necessite ~3 cm/pixel ou mieux.
    Retourne une liste de segments [[x0,y0],[x1,y1]] en pixels de la photo native."""
    if ppm_native < 25:
        return None  # resolution insuffisante : le tuyau fait moins d'un demi-pixel
    gray = cv2.cvtColor(rgb_native, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    w_px = 0.018 * ppm_native
    rid = sato(gray, sigmas=[max(0.8, w_px / 2), max(1.2, w_px)], black_ridges=True)
    rid[~valid_native] = 0
    if veg_native is not None:
        rid[veg_native] = 0
    thr = np.percentile(rid[valid_native], 99.0)
    bw = ((rid > thr) & (gray < np.percentile(gray[valid_native], 40))).astype(
        np.uint8
    ) * 255
    lines = cv2.HoughLinesP(
        bw,
        1,
        np.pi / 360,
        threshold=int(0.8 * ppm_native),
        minLineLength=int(longueur_min_m * ppm_native),
        maxLineGap=int(0.3 * ppm_native),
    )
    if lines is None:
        return []
    # OpenCV 4 renvoie (N, 1, 4), OpenCV 5 renvoie (N, 4) : on normalise
    return [[[float(a), float(b)], [float(c), float(d)]] for a, b, c, d in np.asarray(lines).reshape(-1, 4)]
