"""Verification du LandProfile envoye par le bloc 1. Sans Django.

On ne recalcule rien : on verifie seulement que le format est lisible.
Les champs inconnus (geometry, map_image_url, pollution_sources, land_status...) sont ignores.
"""
COULEURS = ("ROUGE", "ORANGE", "VERT")


def _nombre(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def valider_land_profile(lp):
    """Renvoie (erreurs, avertissements). Le profil est utilisable si `erreurs` est vide.

    Corrige seulement la casse des couleurs ('rouge' -> 'ROUGE') : ce n'est pas un recalcul.
    """
    erreurs, avert = [], []
    if not isinstance(lp, dict):
        return ["le corps doit etre un objet JSON"], []
    if not isinstance(lp.get("parcelle_id"), str) or not lp["parcelle_id"].strip():
        erreurs.append("parcelle_id manquant (texte)")
    o = lp.get("origine")
    if not isinstance(o, dict) or not _nombre(o.get("lat")) or not _nombre(o.get("lon")):
        erreurs.append("origine.lat et origine.lon obligatoires (nombres, coin nord-ouest)")
    elif not (-90 <= o["lat"] <= 90 and -180 <= o["lon"] <= 180):
        erreurs.append("origine.lat / origine.lon hors limites")
    t = lp.get("taille_case_m")
    if not _nombre(t) or t <= 0:
        erreurs.append("taille_case_m obligatoire (> 0)")
    for k in ("largeur_m", "longueur_m"):
        if k in lp and (not _nombre(lp[k]) or lp[k] <= 0):
            erreurs.append(f"{k} doit etre un nombre > 0")
    if lp.get("ce_eau_dS_m") is not None and (not _nombre(lp["ce_eau_dS_m"]) or lp["ce_eau_dS_m"] < 0):
        erreurs.append("ce_eau_dS_m doit etre un nombre >= 0")
    if not lp.get("region"):
        avert.append("region absente : climat trouve par le GPS, region la plus proche pour le secours")
    if not lp.get("texture_sol"):
        avert.append("texture_sol absente : limon par defaut")

    cases = lp.get("cases")
    positions = set()
    if not isinstance(cases, list) or not cases:
        erreurs.append("cases : liste non vide obligatoire")
        cases = []
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            erreurs.append(f"cases[{i}] doit etre un objet")
            continue
        if not (isinstance(c.get("ligne"), int) and isinstance(c.get("col"), int)) or c["ligne"] < 0 or c["col"] < 0:
            erreurs.append(f"cases[{i}] : ligne et col entiers >= 0 obligatoires")
            continue
        if c["col"] >= 26:
            erreurs.append(f"cases[{i}] : col >= 26 non gere (noms A..Z)")
        pos = (c["ligne"], c["col"])
        if pos in positions:
            erreurs.append(f"cases[{i}] : case ({pos[0]},{pos[1]}) en double")
        positions.add(pos)
        coul = str(c.get("couleur", "")).upper()
        if coul not in COULEURS:
            erreurs.append(f"cases[{i}] : couleur '{c.get('couleur')}' inconnue (ROUGE, ORANGE, VERT)")
        elif c["couleur"] != coul:
            c["couleur"] = coul
        if not _nombre(c.get("CE_dS_m")):
            erreurs.append(f"cases[{i}] : CE_dS_m obligatoire (nombre)")

    zones = lp.get("zones")
    if not isinstance(zones, list) or not zones:
        erreurs.append("zones : liste non vide obligatoire")
        zones = []
    ids, dans_zone = set(), set()
    for i, z in enumerate(zones):
        if not isinstance(z, dict):
            erreurs.append(f"zones[{i}] doit etre un objet")
            continue
        zid = z.get("id")
        if not zid:
            erreurs.append(f"zones[{i}] : id manquant")
        elif zid in ids:
            erreurs.append(f"zones[{i}] : id '{zid}' en double")
        ids.add(zid)
        coul = str(z.get("couleur", "")).upper()
        if coul not in COULEURS:
            erreurs.append(f"zone {zid} : couleur '{z.get('couleur')}' inconnue")
        elif z["couleur"] != coul:
            z["couleur"] = coul
        if not isinstance(z.get("cases"), list) or not z["cases"]:
            erreurs.append(f"zone {zid} : cases obligatoires ([[ligne, col], ...])")
        else:
            for cc in z["cases"]:
                if not (isinstance(cc, list) and len(cc) == 2) or tuple(cc) not in positions:
                    erreurs.append(f"zone {zid} : case {cc} absente de 'cases'")
                elif tuple(cc) in dans_zone:
                    erreurs.append(f"zone {zid} : case {cc} deja dans une autre zone")
                else:
                    dans_zone.add(tuple(cc))
        if not isinstance(z.get("culture_alimentaire_autorisee"), bool):
            avert.append(f"zone {zid} : culture_alimentaire_autorisee absente -> consideree comme FALSE (securite)")
        trait = z.get("traitement")
        if trait is not None and (not isinstance(trait, dict) or not isinstance(trait.get("plantes", []), list)):
            erreurs.append(f"zone {zid} : traitement doit etre null ou un objet avec 'plantes' (liste)")
        if coul in ("ROUGE", "ORANGE") and not (trait and trait.get("plantes")):
            avert.append(f"zone {zid} : pas de traitement du bloc 1 -> regle de secours (Atriplex + hyperaccumulatrice)")
    hors = positions - dans_zone
    if hors and not erreurs:
        avert.append(f"{len(hors)} case(s) hors zone : affichees sans culture")
    return erreurs, avert
