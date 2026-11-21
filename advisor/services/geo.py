"""Plan recommande en GeoJSON pour la vue satellite (Leaflet). Sans Django.

origine = coin NORD-OUEST ; ligne 0 = nord, colonne 0 = ouest.
Conversion metres -> degres (approximation locale, suffisante pour quelques centaines de metres).
"""
import math

M_PAR_DEGRE_LAT = 111320.0
COULEUR_ZONE = {"ROUGE": "#B83227", "ORANGE": "#B85C0E", "VERT": "#23774A"}   # memes couleurs que static/js/map.js
AFFICHAGE_MAX = 5


def convertisseur(lat0, lon0):
    """Renvoie f(est_m, sud_m) -> [lon, lat] (ordre GeoJSON)."""
    m_par_deg_lon = M_PAR_DEGRE_LAT * math.cos(math.radians(lat0))

    def f(est_m, sud_m):
        return [round(lon0 + est_m / m_par_deg_lon, 7), round(lat0 - sud_m / M_PAR_DEGRE_LAT, 7)]
    return f


def _feature(geom_type, coords, **props):
    return {"type": "Feature", "geometry": {"type": geom_type, "coordinates": coords}, "properties": props}


def geojson_plan(reco):
    o = reco.get("origine") or {}
    if o.get("lat") is None or o.get("lon") is None:
        return None
    pt = convertisseur(float(o["lat"]), float(o["lon"]))
    t = reco.get("taille_case_m") or 10
    zones = {z["id"]: z for z in reco["zones"]}
    H = reco.get("longueur_m") or t * (max((c["ligne"] for c in reco["cases"]), default=0) + 1)
    feats = []

    for c in reco["cases"]:
        z = zones.get(c["zone_id"])
        x0, y0 = c["col"] * t, c["ligne"] * t          # est, sud (metres depuis le coin NO)
        feats.append(_feature("Polygon", [[pt(x0, y0), pt(x0 + t, y0), pt(x0 + t, y0 + t), pt(x0, y0 + t), pt(x0, y0)]],
                              kind="case", id=c["id"], zone_id=c["zone_id"], couleur=c["couleur"],
                              hex=COULEUR_ZONE.get(c["couleur"], "#666"), CE_dS_m=c.get("CE_dS_m"),
                              source_mesure=c.get("source_mesure"), culture=c.get("culture"),
                              alimentaire=z["alimentaire"] if z else None))
        if not z:
            continue
        n_reel = max(1, int(t // z["espacement_m"]))
        n = min(n_reel, AFFICHAGE_MAX)       # carte lisible : au plus 5 x 5 symboles par case
        pas = t / n
        for i in range(n):
            y = y0 + pas * (i + 0.5)
            # ligne de goutte-a-goutte (ouest -> est)
            feats.append(_feature("LineString", [pt(x0 + 0.4, y), pt(x0 + t - 0.2, y)], kind="goutte", zone_id=z["id"]))
            for j in range(n):
                feats.append(_feature("Point", pt(x0 + pas * (j + 0.5), y), kind="plante", zone_id=z["id"],
                                      culture=z["culture"], hex=z["couleur_plante"], alimentaire=z["alimentaire"],
                                      arbre=z["espacement_m"] >= 3, couleur=z["couleur"]))
        if z["collecte_drainage"]:
            feats.append(_feature("LineString", [pt(x0 + 0.3, y0 + t - 0.5), pt(x0 + t - 0.3, y0 + t - 0.5)],
                                  kind="drainage", zone_id=z["id"]))

    # equipements a l'ouest de la parcelle : conduite principale, vannes, reservoir, pompe, panneaux
    xm = -1.5
    feats.append(_feature("LineString", [pt(xm, 0), pt(xm, H)], kind="conduite"))
    pas_v = min(2.5, (H - 4) / max(1, len(reco["zones"]) + 1))
    for k, z in enumerate(reco["zones"]):
        feats.append(_feature("Point", pt(xm, 4 + pas_v * (k + 1)), kind="vanne", zone_id=z["id"], couleur=z["couleur"],
                              hex=COULEUR_ZONE.get(z["couleur"], "#666"), besoin_litres_jour=z["besoin_litres_jour"]))
    feats.append(_feature("Point", pt(-7, 2), kind="reservoir", nom="Reservoir sureleve"))
    feats.append(_feature("LineString", [pt(-7, 2), pt(xm, 2)], kind="conduite"))
    feats.append(_feature("Point", pt(-7, H / 2), kind="pompe", nom="Pompe (nappe)"))
    feats.append(_feature("LineString", [pt(-7, H / 2), pt(-7, 2)], kind="conduite"))
    feats.append(_feature("Point", pt(-7, H - 3), kind="panneaux", nom="Panneaux solaires"))

    # etiquettes de zone (centre des cases de la zone)
    for z in reco["zones"]:
        if not z["cases"]:
            continue
        mx = sum((c + 0.5) * t for (_, c) in z["cases"]) / len(z["cases"])
        my = sum((l + 0.5) * t for (l, _) in z["cases"]) / len(z["cases"])
        l0, c0 = min(z["cases"], key=lambda lc: ((lc[1] + 0.5) * t - mx) ** 2 + ((lc[0] + 0.5) * t - my) ** 2)
        cx, cy = (c0 + 0.5) * t, (l0 + 0.5) * t
        feats.append(_feature("Point", pt(cx, cy), kind="etiquette", zone_id=z["id"], couleur=z["couleur"],
                              culture=z["culture"], alimentaire=z["alimentaire"],
                              besoin_litres_jour=z["besoin_litres_jour"]))

    L = reco.get("largeur_m") or t * (max((c["col"] for c in reco["cases"]), default=0) + 1)
    sw, ne = pt(-8, H + 1), pt(L + 1, -1)
    return {"type": "FeatureCollection", "features": feats,
            "bounds": [[sw[1], sw[0]], [ne[1], ne[0]]],          # [[lat, lon], [lat, lon]] pour Leaflet
            "origine": [float(o["lat"]), float(o["lon"])]}
