"""Terre nue ou deja plantee ? Lu dans le LandProfile du bloc 1 (sans Django).

Ordre :
  1. `land_status` du LandProfile ("NUE" / "PLANTEE") si le bloc 1 le donne ;
  2. `etat` des zones (toutes PLANTEE -> PLANTEE, toutes NUE -> NUE) ;
  3. couche satellite Sentinel-2 du diagnostic (cases[].satellite) : NDVI et classe de sol (SCL),
     memes seuils que diagnostics.satellite_fusion (NDVI < 0,20 = sol nu ; >= 0,30 = couvert vegetal).
Si rien n'est decisif : None -> la page demande a l'agriculteur.
"""
NDVI_SOL_NU = 0.20
NDVI_VEGETATION = 0.30
PART_DECISIVE = 0.5          # au moins la moitie des cases


def etat_terre(profile):
    """Renvoie {"etat": "NUE"|"PLANTEE"|None, "source", "couvert_pct", "sol_nu_pct", "date"}."""
    statut = str(profile.get("land_status") or "").upper()
    if statut in ("NUE", "PLANTEE"):
        return {"etat": statut, "source": "land_status", "couvert_pct": None, "sol_nu_pct": None, "date": None}

    etats = {str(z.get("etat") or "").upper() for z in profile.get("zones", [])} - {""}
    if etats in ({"NUE"}, {"PLANTEE"}):
        return {"etat": etats.pop(), "source": "zones", "couvert_pct": None, "sol_nu_pct": None, "date": None}

    sat = [c["satellite"] for c in profile.get("cases", [])
           if isinstance(c.get("satellite"), dict) and c["satellite"].get("valide", True)
           and c["satellite"].get("ndvi") is not None]
    if not sat:
        return {"etat": None, "source": None, "couvert_pct": None, "sol_nu_pct": None, "date": None}
    n = len(sat)
    # categories exclusives : le NDVI decide d'abord, la classe de sol (SCL) tranche entre les deux seuils
    veg = sum(1 for s in sat if s["ndvi"] >= NDVI_VEGETATION
              or (s["ndvi"] >= NDVI_SOL_NU and s.get("scl") == "vegetation")) / n
    nu = sum(1 for s in sat if s["ndvi"] < NDVI_SOL_NU
             or (s["ndvi"] < NDVI_VEGETATION and s.get("scl") == "bare_soil")) / n
    etat = "PLANTEE" if veg >= PART_DECISIVE else "NUE" if nu >= PART_DECISIVE else None
    meta = profile.get("satellite") or {}
    return {"etat": etat, "source": "sentinel2", "couvert_pct": round(100 * veg), "sol_nu_pct": round(100 * nu),
            "date": meta.get("date"), "image": meta.get("image")}
