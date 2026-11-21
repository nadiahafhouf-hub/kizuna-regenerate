"""Bloc 1 — plan des capteurs pour une parcelle rectangulaire.

Deux couches de mesure :
- points de RELEVÉ (P1…Pn) : campagne avec XRF partagé + pH-mètre/CE-mètre portable
  (Cd, Pb, pH, CE). Densité ≈ 1 point pour 4 cases de 10 m (≈ 1 / 400 m²), minimum 5
  (4 coins + centre), + 1 point de renfort sur le bord tourné vers la source de pollution.
- STATIONS fixes (S1…Sk) : ESP32 + sondes bas coût (humidité, CE, température),
  ≈ 1 par 2 500 m² et au moins 1 par secteur ; servent surtout à l'irrigation (bloc 3).

Repère : origine = coin nord-ouest, ligne vers le sud, colonne vers l'est.
Coordonnées en mètres : x = (col + 0.5) · taille, y = (ligne + 0.5) · taille.
"""
import math

M_PAR_DEG_LAT = 111_320.0
AIRE_PAR_POINT_M2 = 400      # 1 point de relevé pour 20 m × 20 m
MIN_POINTS = 5               # 4 coins + centre
AIRE_PAR_STATION_M2 = 2_500  # 1 station pour 0,25 ha


def nb_lignes_colonnes(largeur_m, longueur_m, taille_m=10):
    return math.ceil(longueur_m / taille_m), math.ceil(largeur_m / taille_m)


def nb_points_recommande(largeur_m, longueur_m):
    return max(MIN_POINTS, math.ceil(largeur_m * longueur_m / AIRE_PAR_POINT_M2))


def nb_stations_recommande(largeur_m, longueur_m):
    return max(1, math.ceil(largeur_m * longueur_m / AIRE_PAR_STATION_M2))


def _spread(n, size):
    """n positions (indices de case) réparties de façon régulière sur [0, size-1], bords inclus."""
    if size <= 1 or n <= 1:
        return [size // 2] if n == 1 else [0]
    return sorted({round(i * (size - 1) / (n - 1)) for i in range(n)})


def disposition(nb_lignes, nb_colonnes, n):
    """Choisit n cases bien réparties : grille régulière (coins compris) + centre,
    complétée par les cases les plus éloignées des points déjà placés (échantillonnage
    « farthest point »). Renvoie une liste de (ligne, col) sans doublon."""
    total = nb_lignes * nb_colonnes
    n = min(n, total)
    # grille de départ k_l × k_c proche du ratio de la parcelle
    # au moins 2 × 2 (les 4 coins) dès que la parcelle le permet
    k_c = max(min(2, nb_colonnes), round(math.sqrt(n * nb_colonnes / nb_lignes)))
    k_l = max(min(2, nb_lignes), round(n / k_c))
    while k_l * k_c > n and k_l * k_c > 4:
        if k_l >= k_c:
            k_l -= 1
        else:
            k_c -= 1
    pts = [(l, c) for l in _spread(k_l, nb_lignes) for c in _spread(k_c, nb_colonnes)]
    centre = (nb_lignes // 2, nb_colonnes // 2)
    if centre not in pts:
        pts.append(centre)
    pts = list(dict.fromkeys(pts))[:n]
    toutes = [(l, c) for l in range(nb_lignes) for c in range(nb_colonnes)]
    while len(pts) < n:
        loin = max((p for p in toutes if p not in pts),
                   key=lambda p: min((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for q in pts))
        pts.append(loin)
    return pts


def _deg(lat):
    return 1 / M_PAR_DEG_LAT, 1 / (M_PAR_DEG_LAT * math.cos(math.radians(lat)))


def centre_case(origine_lat, origine_lon, ligne, col, taille_m=10):
    dlat, dlon = _deg(origine_lat)
    return origine_lat - (ligne + 0.5) * taille_m * dlat, origine_lon + (col + 0.5) * taille_m * dlon


def cap_vers(lat1, lon1, lat2, lon2):
    """Cap (degrés, 0 = nord, 90 = est) du point 1 vers le point 2."""
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1)))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def distance_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _case_vers(nb_lignes, nb_colonnes, cap):
    """Case du bord de la parcelle située dans la direction `cap`."""
    dx, dy = math.sin(math.radians(cap)), -math.cos(math.radians(cap))  # y vers le sud
    cl, cc = (nb_lignes - 1) / 2, (nb_colonnes - 1) / 2
    t = min(cc / abs(dx) if abs(dx) > 1e-9 else math.inf, cl / abs(dy) if abs(dy) > 1e-9 else math.inf)
    return round(cl + dy * t), round(cc + dx * t)


def plan_capteurs(largeur_m, longueur_m, origine_lat, origine_lon, taille_m=10, sources=()):
    """Plan complet : points de relevé P1…Pn, stations S1…Sk, avec positions GPS.
    `sources` : sources de pollution {lat, lon, name, radius_km} — un point de renfort
    est ajouté sur le bord tourné vers la plus proche si elle est à moins de 3 × son rayon."""
    nl, nc = nb_lignes_colonnes(largeur_m, longueur_m, taille_m)
    n = nb_points_recommande(largeur_m, longueur_m)
    cases = disposition(nl, nc, n)

    centre_lat, centre_lon = centre_case(origine_lat, origine_lon, (nl - 1) / 2, (nc - 1) / 2, taille_m)
    renfort = None
    if sources:
        src = min(sources, key=lambda s: distance_km(centre_lat, centre_lon, s["lat"], s["lon"]))
        d = distance_km(centre_lat, centre_lon, src["lat"], src["lon"])
        if d <= 3 * src.get("radius_km", 5):
            cap = cap_vers(centre_lat, centre_lon, src["lat"], src["lon"])
            case = _case_vers(nl, nc, cap)
            renfort = {"source": src.get("name", ""), "distance_km": round(d, 2), "cap_deg": round(cap)}
            if case not in cases:
                cases.append(case)

    points = []
    for i, (l, c) in enumerate(cases, 1):
        lat, lon = centre_case(origine_lat, origine_lon, l, c, taille_m)
        points.append({"id": f"P{i}", "ligne": l, "col": c, "lat": lat, "lon": lon,
                       "role": "renfort" if renfort and (l, c) == cases[-1] and i > n else "grille"})

    # stations : centres de bandes horizontales (secteurs d'irrigation)
    k = nb_stations_recommande(largeur_m, longueur_m)
    stations = []
    for j in range(k):
        l = min(nl - 1, int((j + 0.5) * nl / k))
        c = nc // 2
        lat, lon = centre_case(origine_lat, origine_lon, l, c, taille_m)
        stations.append({"id": f"S{j + 1}", "ligne": l, "col": c, "lat": lat, "lon": lon})

    return {
        "largeur_m": largeur_m, "longueur_m": longueur_m, "taille_case_m": taille_m,
        "nb_lignes": nl, "nb_colonnes": nc, "nb_cases": nl * nc,
        "points": points, "stations": stations, "renfort": renfort,
        "regle": {"aire_par_point_m2": AIRE_PAR_POINT_M2, "min_points": MIN_POINTS,
                  "aire_par_station_m2": AIRE_PAR_STATION_M2},
    }
