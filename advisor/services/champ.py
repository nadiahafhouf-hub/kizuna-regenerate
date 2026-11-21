"""Terre déjà plantée : analyse à l'échelle du CHAMP sur l'image satellite (sans Django).

Une parcelle de diagnostic fait 30 m × 30 m : trop petit pour voir les rangs d'arbres et tracer un
chemin d'irrigation qui a du sens. Ici on prend une vue plus large (le champ entier) :

1. image Esri World Imagery (zoom 18, ~0,5 m/pixel) autour du centre de la parcelle ;
2. arbres = taches sombres plus foncées que leur voisinage (couronne + ombre), centre et diamètre ;
3. axe du champ = direction des sillons (tenseur de structure de l'image) ; si les sillons ne sont
   pas nets, direction qui aligne le mieux les arbres en rangs ;
4. rectangle du champ orienté sur cet axe (longueur × largeur, modifiable par l'agriculteur) ;
5. réseau : une rampe goutte-à-goutte par rang d'arbres (le long de l'axe), une conduite principale
   perpendiculaire placée là où il faut le moins de tuyau, des vannes par secteur (débit de la pompe),
   la source au bout de la conduite principale ;
6. eau : Kc × ET0 × surface de la couronne / 0,9 (rendement du goutte-à-goutte), par arbre.

Chiffres INDICATIFS (image satellite, pas de mesure terrain).
"""

import math

import cv2
import numpy as np

from services.irrigation_engine import crops as cultures
from services.irrigation_engine import satellite as sat

ZOOM = 18                 # zoom natif maximal d'Esri à Gabès
R_LAT = 111_320.0
MARGE_ARBRES_M = 4.0      # les arbres de bordure (haies de palmiers) sont gardés
ECART_RANG_M = 3.0        # deux arbres à moins de 3 m (perpendiculairement à l'axe) = même rang
RAMPE_MAX_M = 120.0       # longueur maximale d'une rampe 16 mm sur terrain plat (d'un côté)
RENDEMENT = 0.9           # goutte-à-goutte
DIAMETRES_MM = (32, 40, 50, 63, 75, 90)


class ChampErreur(Exception):
    """Erreur lisible par l'agriculteur."""


# --------------------------------------------------------------------------- image
def _image(lat, lon, rayon_m, cache):
    """Mosaïque carrée centrée sur (lat, lon). Renvoie (rgb, m/px, x0, y0 globaux)."""
    cfg = sat.configuration("esri", cache=cache)
    res = sat.resolution_m_px(lat, ZOOM)
    cx, cy = sat.lonlat_vers_px(lon, lat, ZOOM)
    r = int(math.ceil(rayon_m / res))
    x0, y0 = int(cx) - r, int(cy) - r
    try:
        rgb, vides, _ = sat._mosaique(cfg, ZOOM, (x0, y0, int(cx) + r, int(cy) + r))
    except sat.SatelliteErreur as e:
        raise ChampErreur(str(e))
    if vides > 0.5:
        raise ChampErreur("Esri n'a pas d'image à ce zoom ici : choisir un autre endroit.")
    return rgb, res, cx - x0, cy - y0


def _luminance(rgb):
    f = rgb.astype(np.float32)
    return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]


def detecter_arbres(rgb, res):
    """Arbres = taches sombres (couronne + ombre portée) d'au moins ~2,6 m de diamètre.
    Renvoie (liste de (x, y, rayon_px), masque des arbres)."""
    from skimage.feature import peak_local_max

    lum = _luminance(rgb)
    voisinage = cv2.GaussianBlur(lum, (0, 0), 10 / res)
    masque = ((lum < voisinage - 22) & (lum < 110)).astype(np.uint8)
    masque = cv2.morphologyEx(masque, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    dist = cv2.distanceTransform(masque, cv2.DIST_L2, 5)
    pics = peak_local_max(dist, min_distance=max(2, int(3.0 / res)), threshold_abs=1.3 / res, exclude_border=False)
    return [(float(x), float(y), float(dist[y, x])) for y, x in pics], masque


def _axe_sillons(lum, masque_arbres, cx, cy, rayon_px):
    """Direction dominante des sillons (radians, repère image) et cohérence 0..1."""
    g = cv2.GaussianBlur(lum, (0, 0), 1.0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    yy, xx = np.mgrid[0:lum.shape[0], 0:lum.shape[1]]
    zone = ((xx - cx) ** 2 + (yy - cy) ** 2 < rayon_px ** 2)
    zone &= cv2.dilate(masque_arbres, np.ones((9, 9), np.uint8)) == 0   # pas les bords des arbres
    jxx, jyy, jxy = float((gx[zone] ** 2).sum()), float((gy[zone] ** 2).sum()), float((gx[zone] * gy[zone]).sum())
    if jxx + jyy == 0:
        return 0.0, 0.0
    coherence = math.hypot(jxx - jyy, 2 * jxy) / (jxx + jyy)
    return 0.5 * math.atan2(2 * jxy, jxx - jyy) + math.pi / 2, coherence


def _axe_rangs(points):
    """Direction qui aligne le mieux les arbres en rangs (histogramme le plus « pointu »)."""
    if len(points) < 6:
        return None
    p = np.array(points, dtype=float)
    meilleur, score_max = None, -1.0
    for deg in range(0, 180):
        t = math.radians(deg)
        v = -p[:, 0] * math.sin(t) + p[:, 1] * math.cos(t)
        h, _ = np.histogram(v, bins=max(4, int(np.ptp(v) / 2) + 1))
        score = float((h.astype(float) ** 2).sum())
        if score > score_max:
            meilleur, score_max = t, score
    return meilleur


def _norm_angle(t):
    """Ramène l'angle dans [-90°, 90°[ (une ligne n'a pas de sens)."""
    return (t + math.pi / 2) % math.pi - math.pi / 2


# --------------------------------------------------------------------------- réseau
def _rangs(arbres_uv):
    """Regroupe les arbres (u, v, ...) en rangs parallèles à l'axe."""
    rangs, courant = [], []
    for a in sorted(arbres_uv, key=lambda a: a["v"]):
        if courant and a["v"] - courant[-1]["v"] > ECART_RANG_M:
            rangs.append(courant)
            courant = []
        courant.append(a)
    if courant:
        rangs.append(courant)
    return rangs


def _diametre(debit_l_h, longueur_m):
    """Diamètre PE indicatif : vitesse ≤ 1,5 m/s, un cran de plus au-delà de 150 m."""
    q = debit_l_h / 3600 / 1000
    for d in DIAMETRES_MM:
        di = d * 0.8 / 1000   # diamètre intérieur approx. (PN6)
        if q / (math.pi * di ** 2 / 4) <= 1.5:
            i = DIAMETRES_MM.index(d)
            return DIAMETRES_MM[min(i + (longueur_m > 150), len(DIAMETRES_MM) - 1)]
    return DIAMETRES_MM[-1]


def _goutteurs(diam_m):
    return 2 if diam_m < 3 else 4 if diam_m < 5 else 6 if diam_m < 7 else 8


def concevoir(arbres_uv, L, W, debit_goutteur, debit_pompe_l_h):
    """Réseau dans le repère du champ (u le long de l'axe, v en travers, centre = 0).
    Renvoie rampes, conduite principale, vannes, source et secteurs."""
    rangs = _rangs(arbres_uv)
    if not rangs:
        return None
    spans = [(min(a["u"] for a in r), max(a["u"] for a in r)) for r in rangs]
    # position de la conduite principale (u = constante) : un bout du champ ou le milieu
    candidats = {"ouest": -L / 2, "est": L / 2, "milieu": float(np.median([a["u"] for a in arbres_uv]))}
    choix = None
    for nom, um in candidats.items():
        runs = [max(abs(a - um), abs(b - um)) for a, b in spans]
        longueur = sum(max(b, um) - min(a, um) for a, b in spans)
        cout = longueur + 1000 * sum(max(0.0, r - RAMPE_MAX_M) for r in runs)
        if choix is None or cout < choix[0]:
            choix = (cout, nom, um, longueur)
    _, position, um, long_rampes = choix
    vs = [float(np.median([a["v"] for a in r])) for r in rangs]
    # source sur le grand côté le plus proche des rangs (conduite principale la plus courte)
    vsrc = -W / 2 if abs(min(vs) + W / 2) <= abs(W / 2 - max(vs)) else W / 2
    ordre = sorted(range(len(rangs)), key=lambda i: abs(vs[i] - vsrc))
    rampes, secteurs, debit_secteur = [], [], debit_pompe_l_h + 1
    for i in ordre:
        r, (a, b) = rangs[i], spans[i]
        debit = sum(t["goutteurs"] * debit_goutteur for t in r)
        if debit_secteur + debit > debit_pompe_l_h:   # nouvelle vanne
            secteurs.append({"numero": len(secteurs) + 1, "v": vs[i], "debit_l_h": 0.0, "arbres": 0, "eau_l_jour": 0.0})
            debit_secteur = 0.0
        debit_secteur += debit
        s = secteurs[-1]
        s["debit_l_h"] += debit
        s["arbres"] += len(r)
        s["eau_l_jour"] += sum(t["l_jour"] for t in r)
        rampes.append({"v": vs[i], "u0": min(a, um), "u1": max(b, um), "secteur": s["numero"],
                       "arbres": len(r), "debit_l_h": debit})
    vfin = max((abs(v - vsrc), v) for v in vs)[1]
    principale = {"u": um, "v0": vsrc, "v1": vfin, "longueur_m": abs(vfin - vsrc),
                  "debit_l_h": max(s["debit_l_h"] for s in secteurs)}
    principale["diametre_mm"] = _diametre(principale["debit_l_h"], principale["longueur_m"])
    for s in secteurs:
        s["heures"] = round(s["eau_l_jour"] / s["debit_l_h"], 1) if s["debit_l_h"] else 0
    return {"rampes": rampes, "principale": principale, "secteurs": secteurs, "position": position,
            "rangs": len(rangs), "longueur_rampes_m": long_rampes}


# --------------------------------------------------------------------------- point d'entrée
def analyser_champ(lat, lon, longueur_m=140.0, largeur_m=70.0, angle_deg=None, culture="Palmier dattier",
                   et0_mm=5.0, debit_pompe_l_h=1500.0, mois=None, cache=None):
    """Analyse le champ centré sur (lat, lon). angle_deg = direction des rangs en degrés depuis l'est,
    sens horaire (None = détectée sur l'image). Renvoie un dict avec un GeoJSON (couches du bloc 3)."""
    import datetime

    L = float(min(max(longueur_m, 20), 400))
    W = float(min(max(largeur_m, 10), 300))
    rgb, res, cx, cy = _image(lat, lon, 0.5 * math.hypot(L, W) + 15, cache)
    lum = _luminance(rgb)
    arbres_px, masque = detecter_arbres(rgb, res)

    # axe du champ
    if angle_deg is not None:
        t, source_axe, coherence = math.radians(float(angle_deg)), "manuel", None
    else:
        t, coherence = _axe_sillons(lum, masque, cx, cy, min(60.0, max(L, W) / 2) / res)
        source_axe = "sillons"
        if coherence < 0.15:   # sillons peu nets : on aligne les arbres
            proches = [((x - cx) * res, (y - cy) * res) for x, y, _ in arbres_px
                       if math.hypot(x - cx, y - cy) * res < max(L, W) / 2]
            t2 = _axe_rangs(proches)
            if t2 is not None:
                t, source_axe = t2, "rangs d'arbres"
    t = _norm_angle(t)
    cu, su = math.cos(t), math.sin(t)

    def uv(x_m, y_m):
        return x_m * cu + y_m * su, -x_m * su + y_m * cu

    def lonlat(u, v):
        x, y = u * cu - v * su, u * su + v * cu   # mètres est / sud depuis le centre
        return [round(lon + x / (R_LAT * math.cos(math.radians(lat))), 7), round(lat - y / R_LAT, 7)]

    # arbres du champ
    nom_cle, _ = cultures.culture_depuis_nom(culture)
    c = cultures.get_crop(nom_cle)
    mois = mois or datetime.date.today().month
    kc = c["kc"][mois - 1] or 0.5
    q_goutteur = float(c.get("debit_goutteur_l_h", 4.0))
    arbres = []
    for x, y, r in arbres_px:
        u, v = uv((x - cx) * res, (y - cy) * res)
        if abs(u) <= L / 2 + MARGE_ARBRES_M and abs(v) <= W / 2 + MARGE_ARBRES_M:
            d = round(2 * r * res, 1)
            arbres.append({"u": u, "v": v, "diam_m": d, "goutteurs": _goutteurs(d),
                           "l_jour": round(kc * et0_mm * math.pi * (d / 2) ** 2 / RENDEMENT, 1)})

    reseau = concevoir(arbres, L, W, q_goutteur, debit_pompe_l_h) if arbres else None

    F = []

    def f(geom, coords, **props):
        F.append({"type": "Feature", "geometry": {"type": geom, "coordinates": coords}, "properties": props})

    coins = [lonlat(su_ * L / 2, sv * W / 2) for su_, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1))]
    f("Polygon", [coins], couche="champ", longueur_m=round(L), largeur_m=round(W))
    for a in arbres:
        f("Point", lonlat(a["u"], a["v"]), couche="plante_existante", diam_couronne_m=a["diam_m"],
          goutteurs=a["goutteurs"], l_jour=a["l_jour"])
    if reseau:
        p = reseau["principale"]
        for r in reseau["rampes"]:
            f("LineString", [lonlat(r["u0"], r["v"]), lonlat(r["u1"], r["v"])], couche="rampe",
              secteur=r["secteur"], diametre_mm=16, longueur_m=round(r["u1"] - r["u0"], 1), arbres=r["arbres"])
        f("LineString", [lonlat(p["u"], p["v0"]), lonlat(p["u"], p["v1"])], couche="conduite_principale",
          diametre_mm=p["diametre_mm"], longueur_m=round(p["longueur_m"], 1))
        for s in reseau["secteurs"]:
            f("Point", lonlat(p["u"], s["v"]), couche="vanne", secteur=s["numero"],
              debit_m3_h=round(s["debit_l_h"] / 1000, 2), arbres=s["arbres"], heures=s["heures"])
        f("Point", lonlat(p["u"], p["v0"]), couche="source")

    eau = sum(a["l_jour"] for a in arbres)
    secteurs = reseau["secteurs"] if reseau else []
    return {
        "centre": {"lat": lat, "lon": lon},
        "longueur_m": round(L), "largeur_m": round(W),
        "angle_deg": round(math.degrees(t), 1),
        "cap_deg": round((90 + math.degrees(t)) % 180, 0),   # direction des rangs, depuis le nord
        "axe_source": source_axe, "coherence": None if coherence is None else round(coherence, 2),
        "resolution_m_px": round(res, 2), "zoom": ZOOM,
        "culture": c["nom"], "kc": kc, "et0_mm": round(et0_mm, 2),
        "arbres": len(arbres),
        "rangs": reseau["rangs"] if reseau else 0,
        "position_principale": reseau["position"] if reseau else None,
        "longueur_principale_m": round(reseau["principale"]["longueur_m"]) if reseau else 0,
        "diametre_principale_mm": reseau["principale"]["diametre_mm"] if reseau else None,
        "longueur_rampes_m": round(reseau["longueur_rampes_m"]) if reseau else 0,
        "goutteurs": sum(a["goutteurs"] for a in arbres),
        "secteurs": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in s.items() if k != "v"}
                     for s in secteurs],
        "eau_l_jour": round(eau),
        "heures_pompage": round(sum(s["heures"] for s in secteurs), 1),
        "geojson": {"type": "FeatureCollection", "features": F},
    }
