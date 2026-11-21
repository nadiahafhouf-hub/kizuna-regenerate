"""Conversion metres <-> lon/lat (origine = coin nord-ouest) et export GeoJSON du plan."""

import math

R_LAT = 111_320.0


def m_vers_lonlat(origine, x, y):
    """x vers l'est, y vers le sud (comme l'image), en metres depuis l'origine."""
    lat0, lon0 = float(origine["lat"]), float(origine["lon"])
    return [
        round(lon0 + x / (R_LAT * math.cos(math.radians(lat0))), 8),
        round(lat0 - y / R_LAT, 8),
    ]


def lonlat_vers_m(origine, lon, lat):
    lat0, lon0 = float(origine["lat"]), float(origine["lon"])
    return (lon - lon0) * R_LAT * math.cos(math.radians(lat0)), (lat0 - lat) * R_LAT


def _f(geom_type, coords, **props):
    return {
        "type": "Feature",
        "geometry": {"type": geom_type, "coordinates": coords},
        "properties": props,
    }


def geojson_plan(diag, T, C):
    o = diag.get("origine") or {"lat": 0.0, "lon": 0.0}
    if o.get("point", "coin_nord_ouest") != "coin_nord_ouest":
        T.warnings.append(
            "Origine GPS attendue au coin nord-ouest : coordonnees du GeoJSON a verifier."
        )
    P = lambda p: m_vers_lonlat(o, p[0], p[1])
    W, H = T.cfg["dimensions_m"]["largeur"], T.cfg["dimensions_m"]["longueur"]
    F = [
        _f(
            "Polygon",
            [[P((0, 0)), P((W, 0)), P((W, H)), P((0, H)), P((0, 0))]],
            couche="parcelle",
            parcelle_id=diag.get("parcelle_id"),
        )
    ]
    tc = float(diag.get("taille_case_m", 10))
    for z, zc in zip(diag.get("zones", []), T.cfg["zones"]):
        polys = [
            [
                [
                    P((c * tc, l * tc)),
                    P(((c + 1) * tc, l * tc)),
                    P(((c + 1) * tc, (l + 1) * tc)),
                    P((c * tc, (l + 1) * tc)),
                    P((c * tc, l * tc)),
                ]
            ]
            for l, c in z.get("cases", [])
        ]
        F.append(
            _f(
                "MultiPolygon",
                polys,
                couche="zone",
                zone=z["id"],
                couleur=z.get("couleur"),
                culture=zc["culture"],
            )
        )
    for zinfo in T.zones:
        for p in zinfo["plantes"]:
            F.append(
                _f(
                    "Point",
                    P((p["x"], p["y"])),
                    couche="plante_existante",
                    zone=zinfo["nom"],
                    diam_couronne_m=round(p["diam_m"], 2),
                )
            )
    for z in C.zones:
        if z.get("vide"):
            continue
        for p in z.get("plantes_a_planter", []):
            F.append(_f("Point", P(p), couche="plante_a_planter", zone=z["nom"]))
        for l in z.get("rampes", []):
            F.append(
                _f(
                    "LineString",
                    [P(l["p0"]), P(l["p1"])],
                    couche="rampe",
                    zone=z["nom"],
                    longueur_m=round(l["L"], 1),
                    debit_l_h=round(l["q_l_h"], 1),
                )
            )
        for s in z["secteurs"]:
            F.append(
                _f(
                    "LineString",
                    [P(p) for p in s["porte_rampe"]],
                    couche="porte_rampe",
                    zone=z["nom"],
                    secteur=s.get("label"),
                    diametre_mm=s["diam_porte_rampe_mm"],
                )
            )
            F.append(
                _f(
                    "Point",
                    P(s["vanne"]),
                    couche="vanne",
                    zone=z["nom"],
                    secteur=s.get("label"),
                    debit_m3_h=round(s["debit_l_h"] / 1000, 2),
                )
            )
        for h in z.get("asperseurs", []):
            F.append(_f("Point", P(h), couche="asperseur", zone=z["nom"]))
    for seg in C.principal["segments"]:
        F.append(
            _f(
                "LineString",
                [P(p) for p in seg],
                couche="conduite_principale",
                diametre_mm=C.principal["diam_mm"],
            )
        )
    F.append(_f("Point", P(T.source), couche="source"))
    return {"type": "FeatureCollection", "features": F}
