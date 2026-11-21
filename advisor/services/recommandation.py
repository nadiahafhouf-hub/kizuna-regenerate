"""Recommandation de cultures pour une TERRE NUE (bloc 2). Sans Django.

Regles :
  1. Zones ROUGE/ORANGE : on applique le traitement du bloc 1 (on n'invente rien).
     Si pas de traitement : regle de secours (Atriplex + plante hyperaccumulatrice).
  2. Securite : si culture_alimentaire_autorisee = false -> JAMAIS de plante alimentaire.
  3. Zones VERTES : UNE culture par zone (une vanne = memes besoins en eau),
     evaluee avec la CE MAXIMALE des cases de la zone + le climat. + 2 alternatives.
On ne recalcule jamais la couleur : elle vient du bloc 1.
"""
import datetime
import json
from pathlib import Path

from .climat import charger_regions, obtenir_climat, region_la_plus_proche
from .eau import CE_EAU_DS_M, besoin_eau_jour, texture_info

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LETTRES = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PLUIE_PLUVIALE_MM = 400
PLANTE_PAR_DEFAUT = dict(type="depollution", alimentaire=False, seuil_ce=20, tmin=-99, tmax_ete_min=0,
                         valeur=1, kc=0.60, couverture=0.6, espacement_m=1.5, pluviale=False,
                         couleur="#7a5c3c", marqueur="^", microbes=[])


class ErreurSecurite(Exception):
    """Une plante alimentaire a ete proposee sur une zone interdite."""


def charger_plantes(chemin=None):
    with open(chemin or DATA_DIR / "plantes.json", encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def id_case(ligne, col):
    return f"{LETTRES[col]}{ligne + 1}"   # A1, B1... (colonne = lettre, ligne = chiffre, ligne 0 = nord)


# ---------- Score d'une culture (repris du prototype) ----------
def score_plante(p, ce, clim, alimentaire_ok, couleur):
    """Renvoie (score, raison) ; score None = plante impossible ici."""
    if p["alimentaire"] and not alimentaire_ok:
        return None, "culture alimentaire interdite ici"
    if couleur == "VERT" and p["type"] != "culture":
        return None, "zone saine : on cultive"
    if couleur != "VERT" and p["type"] != "depollution":
        return None, "zone polluee : pas de culture"
    if clim["tmin_hiver"] < p["tmin"]:
        return None, "hiver trop froid"
    if clim["tmax_ete"] < p["tmax_ete_min"]:
        return None, "ete pas assez chaud"
    if ce > p["seuil_ce"] * 1.4:
        return None, "sol trop sale"
    penal = max(0, ce - p["seuil_ce"]) / p["seuil_ce"] * 3     # un peu trop de sel
    marge = max(0, p["seuil_ce"] - ce) / p["seuil_ce"] * 0.5   # bonne marge de securite
    pluie = 0.6 if (clim["pluie_mm"] >= PLUIE_PLUVIALE_MM and p.get("pluviale")) else 0
    return round(p["valeur"] - penal + marge + pluie, 2), "ok"


# ---------- Lecture du LandProfile ----------
def lire_zones(lp):
    """Associe les cases a leur zone. La couleur vient TOUJOURS du bloc 1."""
    cases = {(c["ligne"], c["col"]): c for c in lp.get("cases", [])}
    t = lp.get("taille_case_m", 10)
    zones = []
    for z in lp.get("zones", []):
        couleur = str(z.get("couleur", "")).upper()
        zc = [cases[(l, c)] for (l, c) in z.get("cases", []) if (l, c) in cases]
        ce_max = max((c.get("CE_dS_m") or 0 for c in zc), default=0)
        zones.append(dict(
            id=z["id"], couleur=couleur, cases=[[l, c] for (l, c) in z.get("cases", [])],
            surface_m2=z.get("surface_m2") or len(z.get("cases", [])) * t * t,
            ce_max_dS_m=ce_max,
            # securite : alimentaire seulement si le bloc 1 l'autorise ET zone verte
            alimentaire_ok=bool(z.get("culture_alimentaire_autorisee", False)) and couleur == "VERT",
            culture_alimentaire_autorisee=bool(z.get("culture_alimentaire_autorisee", False)),
            traitement=z.get("traitement") or None,
        ))
    return zones


def trouver_plante(nom, plantes):
    n = nom.strip().lower()
    for cle, p in plantes.items():
        if n == p["nom"].lower() or n in [x.lower() for x in p.get("noms_latins", [])]:
            return cle, p
    return None, None


def plante_du_bloc1(z, plantes, avertissements):
    """Zone ROUGE/ORANGE avec traitement : on applique les plantes du bloc 1 (pas de recalcul).
    Les parametres d'eau viennent de la base si la plante est connue, sinon valeurs par defaut."""
    t = z["traitement"]
    gardees, params = [], []
    for nom in t.get("plantes", []):
        cle, p = trouver_plante(nom, plantes)
        if p and p["alimentaire"] and not z["alimentaire_ok"]:
            avertissements.append(f"{z['id']} : '{nom}' retiree (plante alimentaire interdite ici)")
            continue
        gardees.append(nom)
        params.append(p or PLANTE_PAR_DEFAUT)
    if not gardees:
        return None
    moy = lambda k: sum(p[k] for p in params) / len(params)
    return dict(
        PLANTE_PAR_DEFAUT, nom=" + ".join(gardees), type="depollution", alimentaire=False,
        kc=round(moy("kc"), 2), couverture=round(moy("couverture"), 2),
        espacement_m=round(moy("espacement_m"), 2), seuil_ce=min(p["seuil_ce"] for p in params),
        couleur="#7a5c3c" if z["couleur"] == "ROUGE" else "#8c7a3c",
        marqueur="^" if z["couleur"] == "ROUGE" else "v",
        microbes=list(t.get("microbes") or []),
    )


def choisir_pour_zone(z, clim, plantes, avertissements):
    """Renvoie (cle, plante, alternatives, decide_par, note)."""
    if z["couleur"] in ("ROUGE", "ORANGE"):
        if z["traitement"] and z["traitement"].get("plantes"):
            p = plante_du_bloc1(z, plantes, avertissements)
            if p:
                return "bloc1_" + z["id"], p, [], "bloc 1", "traitement du bloc 1"
        # secours du prototype : Atriplex + plante hyperaccumulatrice
        cle = "atriplex_hyper" if z["ce_max_dS_m"] > 4 else "moutarde_tournesol"
        return cle, plantes[cle], [], "bloc 2", "pas de traitement du bloc 1 : regle de secours"

    # zone VERTE : une seule culture, evaluee avec la CE max de la zone
    notes = []
    for cle, p in plantes.items():
        s, _ = score_plante(p, z["ce_max_dS_m"], clim, z["alimentaire_ok"], "VERT")
        if s is not None:
            notes.append((s, cle))
    notes.sort(key=lambda x: (-x[0], x[1]))
    if not notes:
        # aucune culture possible : couvert vegetal NON alimentaire (toujours sur)
        avertissements.append(f"{z['id']} : aucune culture adaptee, couvert d'Atriplex non alimentaire")
        return "atriplex_halimus", plantes["atriplex_halimus"], [], "bloc 2", "aucune culture adaptee"
    best = notes[0][1]
    alternatives = [dict(cle=c, nom=plantes[c]["nom"], score=s, alimentaire=plantes[c]["alimentaire"])
                    for s, c in notes[1:3]]
    return best, plantes[best], alternatives, "bloc 2", f"score {notes[0][0]}"


def nb_plants(nb_cases, taille_case_m, espacement_m):
    n = max(1, int(taille_case_m // espacement_m))
    return nb_cases * n * n


def ce_eau_irrigation(lp):
    """Salinite de l'eau d'irrigation : mesure du LandProfile > valeur typique de la region > defaut."""
    if lp.get("ce_eau_dS_m") is not None:
        return float(lp["ce_eau_dS_m"]), "mesuree (LandProfile)"
    regions = charger_regions()
    o = lp.get("origine") or {}
    nom = lp.get("region")
    if nom not in regions and o.get("lat") is not None:
        nom = region_la_plus_proche(float(o["lat"]), float(o["lon"]), regions)
    if nom in regions and regions[nom].get("ce_eau_dS_m"):
        return float(regions[nom]["ce_eau_dS_m"]), f"valeur typique de la nappe ({nom}, approx.)"
    return CE_EAU_DS_M, "valeur par defaut"


def recommander_cultures(land_profile, climat=None, plantes=None, cache_dir=None):
    """Fonction principale (bloc 2, terre nue). Renvoie le JSON 'recommandation'."""
    lp = land_profile
    plantes = plantes or charger_plantes()
    if climat is None:
        o = lp.get("origine") or {}
        climat = obtenir_climat(o.get("lat"), o.get("lon"), lp.get("region"), cache_dir=cache_dir)
    tex = texture_info(lp.get("texture_sol"))
    t = lp.get("taille_case_m", 10)
    pluie_jour_moy = climat["pluie_mm"] / 365
    ce_eau, ce_eau_source = ce_eau_irrigation(lp)
    avertissements = []
    zones_out = []
    for z in lire_zones(lp):
        cle, p, alternatives, decide_par, note = choisir_pour_zone(z, climat, plantes, avertissements)
        eau = besoin_eau_jour(p["kc"], p["couverture"], p["seuil_ce"], z["couleur"], z["surface_m2"],
                              climat["et0_mm_jour"], pluie_jour_moy, tex["facteur"], ce_eau=ce_eau)
        microbes = list(z["traitement"].get("microbes") or []) if (z["traitement"] and decide_par == "bloc 1") \
            else list(p.get("microbes") or [])
        zones_out.append(dict(
            id=z["id"], couleur=z["couleur"], cases=z["cases"], surface_m2=z["surface_m2"],
            ce_max_dS_m=z["ce_max_dS_m"],
            culture=p["nom"], cle=cle, alternatives=alternatives, decide_par=decide_par, note=note,
            alimentaire=p["alimentaire"], culture_alimentaire_autorisee=z["culture_alimentaire_autorisee"],
            microbes=microbes,
            amendements=list((z["traitement"] or {}).get("amendements") or []),
            strategie=(z["traitement"] or {}).get("strategie"),
            mois_avant_sain=(z["traitement"] or {}).get("mois_avant_sain"),
            kc=p["kc"], couverture=p["couverture"], seuil_ce=p["seuil_ce"], espacement_m=p["espacement_m"],
            couleur_plante=p["couleur"], marqueur=p["marqueur"],
            nb_plants=nb_plants(len(z["cases"]), t, p["espacement_m"]),
            etc_mm_jour=eau["etc_mm"], lr=eau["lr"], besoin_litres_jour=round(eau["brut_l"]),
            collecte_drainage=(z["couleur"] == "ROUGE"),
            arrosages_par_jour=tex["arrosages"],
        ))

    zone_de = {}
    for z in zones_out:
        for (l, c) in z["cases"]:
            zone_de[(l, c)] = z
    cases_out = []
    for c in lp.get("cases", []):
        z = zone_de.get((c["ligne"], c["col"]))
        cases_out.append(dict(
            id=id_case(c["ligne"], c["col"]), ligne=c["ligne"], col=c["col"],
            couleur=str(c.get("couleur", "")).upper(), source_mesure=c.get("source", "?"),
            CE_dS_m=c.get("CE_dS_m"), zone_id=z["id"] if z else None,
            culture=z["culture"] if z else None))

    reco = dict(
        parcelle_id=lp["parcelle_id"], date_mesure=lp.get("date_mesure"), region=lp.get("region"),
        etat="terre_nue", genere_le=datetime.datetime.now().isoformat(timespec="seconds"),
        climat=climat, ce_eau_dS_m=ce_eau, ce_eau_source=ce_eau_source, texture_sol=lp.get("texture_sol"), texture=tex,
        largeur_m=lp.get("largeur_m"), longueur_m=lp.get("longueur_m"), taille_case_m=t,
        origine=lp.get("origine"),
        zones=zones_out, cases=cases_out,
        besoin_total_litres_jour=sum(z["besoin_litres_jour"] for z in zones_out),
        avertissements=avertissements,
        mention="Estimations - donnees simulees - prototype (pas des mesures reelles)",
    )
    verifier_securite(reco, plantes)
    return reco


def verifier_securite(reco, plantes=None):
    """Derniere barriere : aucune plante alimentaire sur une zone interdite."""
    plantes = plantes or charger_plantes()
    for z in reco["zones"]:
        if z["culture_alimentaire_autorisee"] and z["couleur"] == "VERT":
            continue
        noms = [z["culture"]] + [a["nom"] for a in z["alternatives"]]
        alim = [z["alimentaire"]] + [a["alimentaire"] for a in z["alternatives"]]
        if any(alim):
            raise ErreurSecurite(f"zone {z['id']} : plante alimentaire proposee ({noms})")
    return True
