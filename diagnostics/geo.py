"""Conversion d'un LandProfile en GeoJSON (une case = un carré) pour Leaflet."""
import math

M_PAR_DEG_LAT = 111_320.0


def _case_polygon(lat0, lon0, ligne, col, taille_m):
    """Origine = coin nord-ouest : ligne vers le sud, colonne vers l'est."""
    dlat = taille_m / M_PAR_DEG_LAT
    dlon = taille_m / (M_PAR_DEG_LAT * math.cos(math.radians(lat0)))
    nord = lat0 - ligne * dlat
    sud = nord - dlat
    ouest = lon0 + col * dlon
    est = ouest + dlon
    return [[ouest, nord], [est, nord], [est, sud], [ouest, sud], [ouest, nord]]


def land_profile_to_geojson(profile: dict) -> dict:
    o = profile["origine"]
    taille = profile["taille_case_m"]
    zone_de = {tuple(c): z["id"] for z in profile.get("zones", []) for c in z["cases"]}
    features = []
    for case in profile["cases"]:
        props = dict(case)
        props["zone"] = zone_de.get((case["ligne"], case["col"]))
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Polygon",
                         "coordinates": [_case_polygon(o["lat"], o["lon"], case["ligne"],
                                                       case["col"], taille)]},
        })
    return {"type": "FeatureCollection", "features": features}
