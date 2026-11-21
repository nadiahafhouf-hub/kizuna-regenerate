"""Image satellite automatique a partir de l'emprise GPS de la parcelle (aucune photo a envoyer).

Emprise : "origine" du diagnostic = coin NORD-OUEST (lat, lon) ; x vers l'est sur largeur_m,
y vers le sud sur longueur_m. Les tuiles XYZ (Web Mercator, 256 px) qui couvrent l'emprise
+ 10 % de marge sont telechargees (4 requetes en parallele au maximum, cache disque),
assemblees en mosaique, recadrees et enregistrees en PNG. La position des 4 coins dans cette
image est renvoyee : le moteur l'utilise ensuite comme un calage {"mode": "coins"} ordinaire.

    from services.irrigation_engine.satellite import image_satellite
    sat = image_satellite(diag, "media/irrigation/tmp", cache="media/tiles_cache")
    sat["image"], sat["coins_px"], sat["resolution_m_px"], sat["zoom"]

Fournisseurs : "esri" (World Imagery, sans cle, par defaut), "mapbox" (MAPBOX_TOKEN),
"google" (Map Tiles API, GOOGLE_MAPS_API_KEY), ou toute URL XYZ {z}/{x}/{y}.
Ce module ne depend pas de Django.
"""

import datetime as dt
import io
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

from .geo import m_vers_lonlat

TAILLE_TUILE = 256
USER_AGENT = "REGEN-irrigation/1.0 (application agricole, Python urllib)"
MAX_PARALLELE = 4
MAX_TUILES = 900  # au-dela on baisse le zoom (parcelle de plusieurs dizaines d'hectares)
SEUIL_RESOLUTION_M_PX = 0.5
MARGE = 0.10

FOURNISSEURS = {
    "esri": {
        "nom": "Esri World Imagery",
        "url": "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        "zoom_max": 20,
    },
    "mapbox": {
        "nom": "Mapbox Satellite",
        "url": "https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}.jpg90?access_token={cle}",
        "attribution": "© Mapbox © OpenStreetMap © Maxar",
        "zoom_max": 22,
        "env": "MAPBOX_TOKEN",
    },
    "google": {
        "nom": "Google Maps (satellite)",
        "url": "https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}?session={session}&key={cle}",
        "attribution": "Imagery © Google",
        "zoom_max": 22,
        "env": "GOOGLE_MAPS_API_KEY",
    },
}


class SatelliteErreur(Exception):
    """Erreur lisible par l'utilisateur (reseau, cle manquante, emprise invalide...)."""


# =========================================================================== Web Mercator
def lonlat_vers_px(lon, lat, z):
    """Coordonnees pixel globales au zoom z (tuiles de 256 px)."""
    n = TAILLE_TUILE * 2**z
    la = math.radians(max(min(lat, 85.05112878), -85.05112878))
    px = (lon + 180.0) / 360.0 * n
    py = (1.0 - math.log(math.tan(la) + 1.0 / math.cos(la)) / math.pi) / 2.0 * n
    return px, py


def resolution_m_px(lat, z):
    """Resolution au sol (m/pixel) d'une tuile Web Mercator au zoom z."""
    return 156543.03 * math.cos(math.radians(lat)) / 2**z


def coins_lonlat(diag):
    """4 coins NO, NE, SE, SO de la parcelle en [lon, lat]."""
    o = diag.get("origine") or {}
    try:
        lat, lon = float(o["lat"]), float(o["lon"])
    except (KeyError, TypeError, ValueError):
        raise SatelliteErreur(
            "Le diagnostic n'a pas d'origine GPS ('origine': {'lat': ..., 'lon': ...}, coin nord-ouest) : "
            "impossible de trouver la parcelle sur l'image satellite."
        )
    if (lat == 0 and lon == 0) or not (-85 < lat < 85 and -180 <= lon <= 180):
        raise SatelliteErreur(
            f"Origine GPS invalide ({lat}, {lon}) : indiquer la latitude/longitude du coin nord-ouest."
        )
    if o.get("point", "coin_nord_ouest") != "coin_nord_ouest":
        raise SatelliteErreur(
            "L'origine GPS doit etre le coin nord-ouest de la parcelle ('point': 'coin_nord_ouest')."
        )
    W, H = float(diag["largeur_m"]), float(diag["longueur_m"])
    return [m_vers_lonlat(o, x, y) for x, y in ((0, 0), (W, 0), (W, H), (0, H))]


# =========================================================================== configuration
def configuration(fournisseur=None, url=None, zoom=None, attribution=None, cache=None, **_):
    """Rassemble la configuration (valeurs de settings Django ou par defaut)."""
    f = (fournisseur or "esri").lower()
    base = dict(FOURNISSEURS.get(f, {}))
    if not base and not url:
        raise SatelliteErreur(
            f"Fournisseur d'images inconnu '{fournisseur}' : esri, mapbox, google, ou donner SATELLITE_TILE_URL."
        )
    cfg = {
        "fournisseur": f,
        "nom": base.get("nom", f),
        "url": url or base["url"],
        "attribution": attribution or base.get("attribution", f),
        "zoom": int(zoom or 19),
        "zoom_max": int(base.get("zoom_max", 21)),
        "cache": cache,
        "cle": None,
        "session": None,
    }
    if "{cle}" in cfg["url"]:
        env = base.get("env") or f"{f.upper()}_API_KEY"
        cfg["cle"] = os.environ.get(env)
        if not cfg["cle"]:
            raise SatelliteErreur(
                f"Cle API manquante pour {cfg['nom']} : definir la variable d'environnement {env}."
            )
    if "{session}" in cfg["url"]:
        cfg["session"] = _session_google(cfg["cle"])
    return cfg


def _session_google(cle):
    """Map Tiles API : un jeton de session est obligatoire avant de demander les tuiles."""
    corps = json.dumps({"mapType": "satellite", "language": "fr-FR", "region": "TN"}).encode()
    try:
        rep = _http_post_json(f"https://tile.googleapis.com/v1/createSession?key={cle}", corps)
        return rep["session"]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        raise SatelliteErreur(f"Google Map Tiles : creation de session impossible ({e}).")


# =========================================================================== reseau (remplacable dans les tests)
def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _http_post_json(url, corps, timeout=20):
    req = urllib.request.Request(
        url, data=corps, headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# =========================================================================== tuiles
def _url_tuile(cfg, z, x, y):
    return cfg["url"].format(z=z, x=x, y=y, cle=cfg.get("cle") or "", session=cfg.get("session") or "")


def _chemin_cache(cfg, z, x, y):
    if not cfg.get("cache"):
        return None
    return Path(cfg["cache"]) / cfg["fournisseur"] / str(z) / str(x) / f"{y}.jpg"


def _tuile(cfg, z, x, y):
    """Renvoie (image RGB 256x256 ou None si absente, erreur reseau ou None)."""
    p = _chemin_cache(cfg, z, x, y)
    if p and p.exists() and p.stat().st_size > 0:
        try:
            return _decoder(p.read_bytes()), None
        except Exception:
            p.unlink(missing_ok=True)  # cache abime : on retelecharge
    try:
        data = _http_get(_url_tuile(cfg, z, x, y))
    except urllib.error.HTTPError as e:
        if e.code in (404, 204):  # pas d'image a ce zoom
            return None, None
        return None, f"HTTP {e.code} {e.reason}"
    except (urllib.error.URLError, OSError) as e:
        return None, str(getattr(e, "reason", e))
    if not data:
        return None, None
    try:
        rgb = _decoder(data)
    except Exception:
        return None, "reponse illisible (ce n'est pas une image : cle API ou URL incorrecte ?)"
    if p and not tuile_vide(rgb):  # pas de cache pour les tuiles vides : l'image peut arriver plus tard
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return rgb, None


def _decoder(data):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.size != (TAILLE_TUILE, TAILLE_TUILE):
        im = im.resize((TAILLE_TUILE, TAILLE_TUILE), Image.BILINEAR)  # tuiles @2x (512 px)
    return np.array(im)


def tuile_vide(rgb):
    """Tuile absente ou uniforme (ex. 'Map data not yet available' d'Esri) : une vraie image n'a
    jamais 90 % de pixels de couleur strictement identique, une tuile de remplissage si."""
    if rgb is None:
        return True
    q = rgb.reshape(-1, 3).astype(np.int32)
    code = (q[:, 0] << 16) | (q[:, 1] << 8) | q[:, 2]
    _, n = np.unique(code, return_counts=True)
    return n.max() / code.size > 0.9 or float(rgb.std()) < 2.0


def _emprise_px(coins, z):
    pts = np.array([lonlat_vers_px(lon, lat, z) for lon, lat in coins])
    x0, y0 = pts.min(0)
    x1, y1 = pts.max(0)
    m = MARGE * max(x1 - x0, y1 - y0, 8)
    return pts, (math.floor(x0 - m), math.floor(y0 - m), math.ceil(x1 + m), math.ceil(y1 + m))


def _mosaique(cfg, z, box):
    """Telecharge les tuiles de la boite (pixels globaux) -> (image RGB recadree, part de tuiles vides)."""
    bx0, by0, bx1, by1 = box
    tx0, ty0 = bx0 // TAILLE_TUILE, by0 // TAILLE_TUILE
    tx1, ty1 = (bx1 - 1) // TAILLE_TUILE, (by1 - 1) // TAILLE_TUILE
    liste = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    with ThreadPoolExecutor(max_workers=MAX_PARALLELE) as ex:
        tuiles = list(ex.map(lambda t: _tuile(cfg, z, *t), liste))
    erreurs = [e for _, e in tuiles if e]
    if erreurs and len(erreurs) == len(liste):
        raise SatelliteErreur(
            f"Telechargement de l'image satellite impossible ({cfg['nom']}) : {erreurs[0]}. "
            "Verifier la connexion internet (ou le pare-feu / proxy), puis reessayer."
        )
    if erreurs:
        raise SatelliteErreur(
            f"{len(erreurs)} tuile(s) sur {len(liste)} n'ont pas pu etre telechargees ({erreurs[0]}). "
            "Reessayer dans quelques instants."
        )
    big = np.zeros(((ty1 - ty0 + 1) * TAILLE_TUILE, (tx1 - tx0 + 1) * TAILLE_TUILE, 3), np.uint8)
    vides = 0
    for (x, y), (rgb, _) in zip(liste, tuiles):
        if tuile_vide(rgb):
            vides += 1
        if rgb is not None:
            ox, oy = (x - tx0) * TAILLE_TUILE, (y - ty0) * TAILLE_TUILE
            big[oy : oy + TAILLE_TUILE, ox : ox + TAILLE_TUILE] = rgb
    ox, oy = bx0 - tx0 * TAILLE_TUILE, by0 - ty0 * TAILLE_TUILE
    return big[oy : oy + (by1 - by0), ox : ox + (bx1 - bx0)], vides / len(liste), len(liste)


def _zooms(cfg, zoom_force=None):
    if zoom_force:
        return [int(zoom_force)]
    z = cfg["zoom"]
    hauts = [min(z + 1, cfg["zoom_max"])] if z + 1 <= cfg["zoom_max"] else []
    return list(dict.fromkeys(hauts + [z] + [zz for zz in (z - 1, 18) if zz < z]))


# =========================================================================== date de prise de vue (Esri)
def date_image_esri(lon, lat, timeout=8):
    """Date de prise de vue d'Esri World Imagery au point donne (meilleur effort, None sinon)."""
    base = "https://metadata.maptiles.arcgis.com/arcgis/rest/services"
    try:
        services = json.loads(_http_get(f"{base}?f=json", timeout)).get("services", [])
        noms = sorted(s["name"] for s in services if s["name"].startswith("World_Imagery_Metadata_20"))
        if not noms:
            return None
        q = urllib.parse.urlencode({
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "SRC_DATE2,SRC_RES,NICE_DESC",
            "returnGeometry": "false", "f": "json",
        })
        for couche in range(0, 8):  # de la plus fine (1,9 cm) a la plus grossiere (2,4 m)
            rep = json.loads(_http_get(f"{base}/{noms[-1]}/MapServer/{couche}/query?{q}", timeout))
            for f in rep.get("features", []):
                a = f.get("attributes", {})
                if a.get("SRC_DATE2"):
                    d = dt.datetime.fromtimestamp(a["SRC_DATE2"] / 1000, dt.timezone.utc).date()
                    return {"date": d.isoformat(), "capteur": a.get("NICE_DESC"),
                            "resolution_source_m": a.get("SRC_RES")}
    except Exception:
        return None
    return None


# =========================================================================== image plus nette
def ameliorer(rgb, res_m_px):
    """Rend l'image plus lisible pour la detection (aucun detail n'est invente) :
    agrandissement x2 (Lanczos) si l'image est grossiere (> 0,3 m/px), contraste local (CLAHE)
    sur la luminance, puis accentuation des contours (masque flou). Renvoie (image, facteur)."""
    k = 2 if res_m_px > 0.3 else 1
    # 1. enlever les blocs de compression JPEG des tuiles (sinon l'accentuation les amplifie)
    img = cv2.fastNlMeansDenoisingColored(rgb, None, 4, 4, 5, 15)
    if k > 1:
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        img = cv2.bilateralFilter(img, 5, 18, 3)  # lisse les marches d'escalier, garde les bords
    # 2. contraste local doux : couronnes sombres plus visibles sur le sol clair
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(4, 4)).apply(lab[..., 0])
    img = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    # 3. accentuation legere des contours (masque flou)
    flou = cv2.GaussianBlur(img, (0, 0), 1.5 * k)
    img = cv2.addWeighted(img, 1.3, flou, -0.3, 0)
    return img, k


# =========================================================================== point d'entree
def image_satellite(diag, dossier, zoom_force=None, date=True, nom="satellite.png", ameliorer_image=True,
                    **config):
    """Telecharge, assemble et recadre l'image satellite de la parcelle.

    Renvoie {"image", "coins_px", "resolution_m_px", "zoom", "fournisseur", "attribution",
             "taille_px", "date", "avertissements"}."""
    cfg = configuration(**config)
    coins = coins_lonlat(diag)
    lat_c = sum(c[1] for c in coins) / 4
    essais = []
    choix = None
    for z in _zooms(cfg, zoom_force):
        pts, box = _emprise_px(coins, z)
        n = ((box[2] - 1) // TAILLE_TUILE - box[0] // TAILLE_TUILE + 1) * (
            (box[3] - 1) // TAILLE_TUILE - box[1] // TAILLE_TUILE + 1)
        if n > MAX_TUILES and not zoom_force:
            essais.append(f"zoom {z} : {n} tuiles, trop pour une seule image")
            continue
        img, part_vide, n = _mosaique(cfg, z, box)
        essai = (z, pts, box, img, part_vide)
        if part_vide > 0.10 and not zoom_force:
            essais.append(f"zoom {z} : {part_vide*100:.0f} % de tuiles vides")
            if choix is None or part_vide < choix[4]:
                choix = essai  # on garde le moins mauvais si aucun zoom n'est complet
            continue
        choix = essai
        break
    if choix is None:
        raise SatelliteErreur("Parcelle trop grande pour une image satellite unique : " + "; ".join(essais))
    z, pts, box, img, part_vide = choix
    if part_vide > 0.5:
        raise SatelliteErreur(
            f"{cfg['nom']} n'a pas d'image a cet endroit ({part_vide*100:.0f} % de tuiles vides). "
            "Verifier l'origine GPS du diagnostic ou changer de fournisseur (SATELLITE_FOURNISSEUR)."
        )
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / nom
    res = resolution_m_px(lat_c, z)
    facteur = 1
    if ameliorer_image:
        img, facteur = ameliorer(img, res)
        pts, box = pts * facteur, [v * facteur for v in box]  # coordonnees dans l'image agrandie
    Image.fromarray(img).save(chemin)
    av = []
    if essais:
        av.append("Image satellite : " + "; ".join(essais) + f" -> zoom {z} utilise.")
    if res > SEUIL_RESOLUTION_M_PX:
        av.append(
            f"Image satellite a {res:.2f} m/pixel (> {SEUIL_RESOLUTION_M_PX} m/px) : seuls les arbres "
            "adultes seront detectes. Pour les jeunes plants, envoyer une photo de drone."
        )
    if part_vide > 0:
        av.append(f"Image satellite : {part_vide*100:.0f} % des tuiles sont vides ou uniformes.")
    coins_px = [[round(float(x - box[0]), 2), round(float(y - box[1]), 2)] for x, y in pts]
    info_date = date_image_esri(*coins[0]) if (date and cfg["fournisseur"] == "esri") else None
    return {
        "image": str(chemin),
        "coins_px": coins_px,
        "resolution_m_px": round(res, 4),
        "zoom": z,
        "fournisseur": cfg["nom"],
        "attribution": cfg["attribution"],
        "taille_px": [int(img.shape[1]), int(img.shape[0])],
        "date": (info_date or {}).get("date"),
        "capteur": (info_date or {}).get("capteur"),
        "ameliore": bool(ameliorer_image),
        "agrandissement": facteur,
        "avertissements": av,
    }


def source_image(sat):
    """Resume a stocker dans res["photo"]["source_image"] et dans le calage du plan."""
    return {k: sat.get(k) for k in ("fournisseur", "attribution", "zoom", "resolution_m_px", "date", "capteur",
                                    "ameliore", "agrandissement")}


def lignes_source(si):
    """2 lignes affichees en bas des images : source + resolution (+ date), puis attribution."""
    if not si:
        return []
    t = f"Image : {si.get('fournisseur')} · zoom {si.get('zoom')} · " \
        f"{si.get('resolution_m_px', 0):.2f} m/pixel"
    if si.get("date"):
        t += f" · prise de vue du {si['date']}"
    if si.get("ameliore"):
        t += " · image nettoyee" + (f" (agrandie x{si['agrandissement']})" if (si.get("agrandissement") or 1) > 1 else "")
    return [t, f"© {si.get('attribution')}"]


def legende_source(si):
    return " — ".join(lignes_source(si))


# =========================================================================== apercu (contour + grille des cases)
def apercu(sat, diag, chemin, largeur_min=900):
    """Image satellite avec le contour de la parcelle, la grille des cases et la teinte des zones.

    Les petites images (zoom 18 : 0,5 m/px) sont agrandies pour etre lisibles a l'ecran.
    Renvoie l'echelle appliquee : pixel de l'apercu = echelle x pixel de l'image satellite."""
    from .parcelle import _hex

    img = cv2.cvtColor(np.array(Image.open(sat["image"]).convert("RGB")), cv2.COLOR_RGB2BGR)
    k = max(1.0, largeur_min / img.shape[1])
    if k > 1:
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    c = np.float32(sat["coins_px"]) * k
    W, H = float(diag["largeur_m"]), float(diag["longueur_m"])
    Hinv = cv2.getPerspectiveTransform(np.float32([[0, 0], [W, 0], [W, H], [0, H]]), c)

    def P(pts):
        return cv2.perspectiveTransform(np.float32(pts).reshape(-1, 1, 2), Hinv).reshape(-1, 2)

    t = max(1, int(round(min(img.shape[:2]) / 400)))
    tc = float(diag.get("taille_case_m", 10))
    calque = img.copy()
    for z in diag.get("zones", []):
        col = _hex(z.get("couleur")).lstrip("#")
        bgr = tuple(int(col[i : i + 2], 16) for i in (4, 2, 0))
        for li, co in z.get("cases", []):
            q = P([[co * tc, li * tc], [(co + 1) * tc, li * tc], [(co + 1) * tc, (li + 1) * tc], [co * tc, (li + 1) * tc]])
            cv2.fillPoly(calque, [q.astype(np.int32)], bgr)
    img = cv2.addWeighted(calque, 0.22, img, 0.78, 0)
    for i in range(1, int(math.ceil(W / tc))):
        a, b = P([[i * tc, 0], [i * tc, H]])
        cv2.line(img, tuple(int(v) for v in a), tuple(int(v) for v in b), (255, 255, 255), t, cv2.LINE_AA)
    for i in range(1, int(math.ceil(H / tc))):
        a, b = P([[0, i * tc], [W, i * tc]])
        cv2.line(img, tuple(int(v) for v in a), tuple(int(v) for v in b), (255, 255, 255), t, cv2.LINE_AA)
    cv2.polylines(img, [c.astype(np.int32)], True, (0, 0, 0), t + 3, cv2.LINE_AA)
    cv2.polylines(img, [c.astype(np.int32)], True, (60, 23, 255), t + 1, cv2.LINE_AA)
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(chemin), img)
    return k
