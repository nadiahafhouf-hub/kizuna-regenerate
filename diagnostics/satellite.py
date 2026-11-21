"""Bloc 1 — couche satellite Sentinel-2 (Copernicus) par case de 10 m.

Source : catalogue STAC public Earth Search (AWS / Element 84), collection « sentinel-2-l2a »
(réflectance de surface corrigée de l'atmosphère). Aucun compte ni clé requis.
Attribution obligatoire : « Contains modified Copernicus Sentinel data <année> ».

Ce que le satellite apporte : vigueur de la végétation (NDVI), humidité de la végétation
(NDMI, stress hydrique) et un indice de sel de surface valable seulement sur sol nu.
Ce qu'il n'apporte PAS : le cadmium ou le plomb (invisibles depuis l'espace).

Indices (réflectances, bandes Sentinel-2) :
- NDVI = (B08 − B04) / (B08 + B04)                      10 m
- NDMI = (B8A − B11) / (B8A + B11)                      20 m  (Gao 1996, « NDWI » SWIR)
- SI   = √(B03 × B04)  — indice de salinité de surface   10 m  (Douaoui et al. 2006), sol nu seulement
- SCL  = classification de scène L2A (nuages, ombres…) → case valide ou non
"""
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
BANDES = {"B03": "green", "B04": "red", "B08": "nir", "B8A": "nir08", "B11": "swir16", "SCL": "scl"}
# SCL : 4 végétation, 5 sol nu, 6 eau, 7 non classé → valides ; 3 ombre, 8-10 nuages, 11 neige → invalides
SCL_VALIDES = {4, 5, 6, 7}
SCL_LIBELLES = {0: "no_data", 1: "saturated", 2: "dark", 3: "cloud_shadow", 4: "vegetation", 5: "bare_soil",
                6: "water", 7: "unclassified", 8: "cloud", 9: "cloud", 10: "cirrus", 11: "snow"}
GDAL_ENV = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
            "GDAL_HTTP_MULTIRANGE": "YES", "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
            "GDAL_HTTP_TIMEOUT": "30", "GDAL_HTTP_MAX_RETRY": "2"}


class SatelliteIndisponible(Exception):
    """Pas d'image exploitable (réseau, nuages, hors couverture)."""


def _centres(origine_lat, origine_lon, nl, nc, taille):
    from .sampling import centre_case
    return [(l, c, *centre_case(origine_lat, origine_lon, l, c, taille)) for l in range(nl) for c in range(nc)]


def _lire_bande(asset, points_lonlat):
    """Lit les pixels sous chaque point (fenêtre englobante, une seule requête HTTP par bande)."""
    import numpy as np
    import rasterio
    from rasterio.warp import transform
    from rasterio.windows import Window

    bands = (asset.extra_fields.get("raster:bands") or [{}])[0]
    scale, offset = bands.get("scale", 1.0), bands.get("offset", 0.0)
    with rasterio.Env(**GDAL_ENV), rasterio.open(asset.href) as src:
        xs, ys = transform("EPSG:4326", src.crs, [p[0] for p in points_lonlat], [p[1] for p in points_lonlat])
        rc = [src.index(x, y) for x, y in zip(xs, ys)]
        r0, r1 = min(r for r, _ in rc), max(r for r, _ in rc)
        c0, c1 = min(c for _, c in rc), max(c for _, c in rc)
        arr = src.read(1, window=Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1))
        vals = np.array([arr[r - r0, c - c0] for r, c in rc], dtype=float)
        res = src.res[0]
    return vals, scale, offset, res


def analyser(origine_lat, origine_lon, largeur_m, longueur_m, taille_m=10, jours=120, nuages_max=30,
             essais=4, aujourd_hui=None):
    """Cherche l'image Sentinel-2 récente la plus claire au-dessus de la parcelle et renvoie
    les indices par case. Lève SatelliteIndisponible si aucune image n'est exploitable."""
    try:
        import numpy as np
        from pystac_client import Client
    except ImportError as e:  # pragma: no cover
        raise SatelliteIndisponible("pystac-client / rasterio non installés") from e

    nl, nc = math.ceil(longueur_m / taille_m), math.ceil(largeur_m / taille_m)
    centres = _centres(origine_lat, origine_lon, nl, nc, taille_m)
    pts = [(lon, lat) for _, _, lat, lon in centres]
    lat_c = sum(p[1] for p in pts) / len(pts)
    lon_c = sum(p[0] for p in pts) / len(pts)
    fin = aujourd_hui or date.today()
    try:
        items = list(Client.open(STAC_URL).search(
            collections=[COLLECTION], intersects={"type": "Point", "coordinates": [lon_c, lat_c]},
            datetime=f"{(fin - timedelta(days=jours)).isoformat()}/{fin.isoformat()}",
            query={"eo:cloud_cover": {"lt": nuages_max}},
            sortby=[{"field": "properties.datetime", "direction": "desc"}], max_items=essais).items())
    except Exception as e:
        raise SatelliteIndisponible(f"catalogue inaccessible : {e}") from e
    if not items:
        raise SatelliteIndisponible("aucune image Sentinel-2 récente peu nuageuse")

    for item in items:
        try:
            scl, *_ = _lire_bande(item.assets["scl"], pts)
        except Exception:
            continue
        valides = [int(v) in SCL_VALIDES for v in scl]
        if sum(valides) / len(valides) < 0.8:
            continue  # parcelle nuageuse sur cette image : on essaie la précédente
        with ThreadPoolExecutor(max_workers=5) as ex:
            lus = dict(zip([b for b in BANDES if b != "SCL"],
                           ex.map(lambda b: _lire_bande(item.assets[BANDES[b]], pts), [b for b in BANDES if b != "SCL"])))
        # réflectance = DN × scale + offset ; le décalage (−0,1) peut rendre le rouge très légèrement
        # négatif sur végétation dense : on borne à 0,0001. « Sans donnée » = DN brut 0 uniquement.
        refl = {b: np.maximum(v * s + o, 1e-4) for b, (v, s, o, _) in lus.items()}
        brut_ok = np.all([lus[b][0] > 0 for b in lus], axis=0)
        cases = []
        for i, (l, c, lat, lon) in enumerate(centres):
            b3, b4, b8, b8a, b11 = (float(refl[k][i]) for k in ("B03", "B04", "B08", "B8A", "B11"))
            ok = valides[i] and bool(brut_ok[i])
            ndvi = (b8 - b4) / (b8 + b4) if ok and b8 + b4 > 0 else None
            ndmi = (b8a - b11) / (b8a + b11) if ok and b8a + b11 > 0 else None
            si = math.sqrt(b3 * b4) if ok else None
            cases.append({"ligne": l, "col": c, "valide": bool(ok), "scl": SCL_LIBELLES.get(int(scl[i]), "?"),
                          "ndvi": None if ndvi is None else round(ndvi, 3),
                          "ndmi": None if ndmi is None else round(ndmi, 3),
                          "si": None if si is None else round(si, 3)})
        return {
            "source": "Copernicus Sentinel-2 L2A (Earth Search, AWS)",
            "attribution": f"Contains modified Copernicus Sentinel data {item.datetime.year}",
            "image": item.id,
            "date": item.datetime.date().isoformat(),
            "nuages_scene_pct": round(float(item.properties.get("eo:cloud_cover", 0)), 1),
            "cases_valides_pct": round(100 * sum(valides) / len(valides)),
            "taille_case_m": taille_m,
            "cases": cases,
        }
    raise SatelliteIndisponible("toutes les images récentes sont nuageuses au-dessus de la parcelle")
