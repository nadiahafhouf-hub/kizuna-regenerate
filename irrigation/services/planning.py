"""Planning d'irrigation sur 7 jours. Sans Django.

Deux types d'evenements :
  POMPAGE  nappe -> reservoir : seulement quand la production solaire >= puissance de la pompe,
           sans jamais faire deborder le reservoir ni depasser le quota de la semaine.
  ARROSAGE reservoir -> zones par gravite : tot le matin, en 1 a 3 fois selon la texture.
Si le quota ne suffit pas : on sert d'abord les zones VERTES, puis ORANGE, puis ROUGE.
"""
import datetime
import math

from advisor.services.eau import besoin_eau_jour
from .meteo import prevision_7_jours

PARAMETRES_DEFAUT = dict(
    puissance_pompe_kw=0.75,
    debit_pompe_m3_h=1.5,
    puissance_crete_kwc=2.0,       # voir README : avec 1,0 kWc x 0,8 la pompe de 0,75 kW ne demarre presque jamais
    ratio_performance=0.8,
    capacite_reservoir_m3=5.0,
    niveau_initial_m3=2.5,         # eau deja dans le reservoir au debut de la semaine
    quota_nappe_m3_semaine=15.0,
    seuil_pluie_mm=5.0,
    seuil_humidite_pct=30.0,
    heure_arrosage=6,
    rendement_submersion=0.6,      # arrosage traditionnel, pour la jauge "eau economisee"
    ce_eau_dS_m=None,              # None = valeur de la recommandation (LandProfile ou region)
)
PRIORITE = {"VERT": 1, "ORANGE": 2, "ROUGE": 3}
NOM_PRIORITE = {1: "cultures (VERT)", 2: "depollution ORANGE", 3: "depollution ROUGE"}
ZONE_RESERVOIR = "RESERVOIR"


def production_solaire_kw(rayonnement_w_m2, kwc, ratio):
    """P = kWc x rayonnement / 1000 x ratio de performance."""
    return kwc * rayonnement_w_m2 / 1000 * ratio


def heures_pompage_possibles(rayonnements, p):
    return [h for h, r in enumerate(rayonnements)
            if production_solaire_kw(r, p["puissance_crete_kwc"], p["ratio_performance"]) >= p["puissance_pompe_kw"]]


def _fmt(x):
    return f"{x:g}"


def generer_planning(recommandation, parametres=None, meteo=None, date_debut=None, volumes_forces=None):
    """recommandation = sortie de recommander_cultures ; volumes_forces = {"Z3|2026-11-23": litres}."""
    reco = recommandation
    p = dict(PARAMETRES_DEFAUT, **(parametres or {}))
    volumes_forces = volumes_forces or {}
    if meteo is None:
        o = reco.get("origine") or {}
        meteo = prevision_7_jours(o.get("lat"), o.get("lon"), reco["climat"], date_debut)
    jours = meteo["jours"][:7]
    tex = reco["texture"]
    n_arr = max(1, min(3, tex["arrosages"]))
    cap_l = p["capacite_reservoir_m3"] * 1000
    quota_l = p["quota_nappe_m3_semaine"] * 1000
    debit_l_h = p["debit_pompe_m3_h"] * 1000
    niveau_initial_l = min(cap_l, p["niveau_initial_m3"] * 1000)
    ce_eau = p.get("ce_eau_dS_m") or reco.get("ce_eau_dS_m") or 2.0
    zones = sorted(reco["zones"], key=lambda z: (PRIORITE.get(z["couleur"], 3), z["id"]))

    # ---- 1. besoin de chaque zone pour chaque jour ----
    demandes = {}   # (jour, zone) -> dict
    for d, j in enumerate(jours):
        for z in zones:
            e = besoin_eau_jour(z["kc"], z["couverture"], z["seuil_ce"], z["couleur"], z["surface_m2"],
                                j["et0_mm"], j["pluie_mm"], tex["facteur"], ce_eau=ce_eau)
            it = dict(besoin_l=e["brut_l"], volume_l=e["brut_l"], raisons=[], annule=False, lr=e["lr"])
            cle = f"{z['id']}|{j['date']}"
            if j["pluie_mm"] >= p["seuil_pluie_mm"]:
                it.update(volume_l=0, annule=True)
                it["raisons"].append(f"annule : {_fmt(j['pluie_mm'])} mm de pluie prevus (seuil {_fmt(p['seuil_pluie_mm'])} mm)")
            elif cle in volumes_forces:
                it["volume_l"] = max(0.0, float(volumes_forces[cle]))
                it["raisons"].append(f"volume modifie a la main ({round(it['volume_l'])} L, calcul : {round(e['brut_l'])} L)")
            if not it["annule"] and it["volume_l"] <= 0:
                it.update(volume_l=0, annule=True)
                it["raisons"].append("annule : pas de besoin (pluie efficace >= ETc)" if cle not in volumes_forces
                                     else "annule : volume mis a 0 a la main")
            demandes[(d, z["id"])] = it

    # ---- 2. quota de la semaine, par priorite (VERT d'abord) ----
    reste = quota_l
    for prio in (1, 2, 3):
        items = [demandes[(d, z["id"])] for d in range(len(jours)) for z in zones
                 if PRIORITE.get(z["couleur"], 3) == prio and not demandes[(d, z["id"])]["annule"]]
        total = sum(it["volume_l"] for it in items)
        if total <= 0:
            continue
        ratio = min(1.0, reste / total)
        for it in items:
            v = math.floor(it["volume_l"] * ratio)
            if ratio < 1:
                pct = round((1 - ratio) * 100)
                it["raisons"].append(f"reduit de {pct} % : quota de nappe atteint (priorite {prio} : {NOM_PRIORITE[prio]})")
            it["volume_l"] = v
        reste -= sum(it["volume_l"] for it in items)

    # ---- 3. simulation jour par jour du reservoir ----
    evenements, trajectoire, resume_jours = [], [], []
    niveau = niveau_initial_l
    total_pompe = 0.0
    cause_manque = "reserve du reservoir insuffisante en debut de semaine"
    h0 = int(p["heure_arrosage"])
    # heures ou la pompe peut tourner (apres les arrosages du matin, pour ne jamais faire deborder)
    heures_soleil = [[h for h in heures_pompage_possibles(j["rayonnement_w_m2"], p) if h >= h0 + n_arr]
                     for j in jours]

    def besoin_jour(k):
        return sum(demandes[(k, z["id"])]["volume_l"] for z in zones if not demandes[(k, z["id"])]["annule"])

    for d, j in enumerate(jours):
        niveau_matin = niveau
        arrose_jour = 0
        # arrosage tot le matin, zones prioritaires d'abord
        for z in zones:
            it = demandes[(d, z["id"])]
            raisons = list(it["raisons"])
            if it["annule"]:
                evenements.append(dict(zone_id=z["id"], couleur=z["couleur"], date=j["date"], heure=f"{h0:02d}:00",
                                       type="ARROSAGE", volume_l=0, statut="ANNULE", raison=" ; ".join(raisons),
                                       energie_kwh=0))
                continue
            donne = min(it["volume_l"], math.floor(niveau))
            if donne < it["volume_l"]:
                raisons.append(f"reduit : {cause_manque}")
            if donne <= 0:
                evenements.append(dict(zone_id=z["id"], couleur=z["couleur"], date=j["date"], heure=f"{h0:02d}:00",
                                       type="ARROSAGE", volume_l=0, statut="ANNULE", raison=" ; ".join(raisons),
                                       energie_kwh=0))
                continue
            # decoupage selon la texture (sable : 3 petites doses)
            part = donne // n_arr
            for k in range(n_arr):
                v = part if k < n_arr - 1 else donne - part * (n_arr - 1)
                niveau -= v
                arrose_jour += v
                raison = " ; ".join(raisons) or f"besoin estime {round(it['besoin_l'])} L/jour (dose {k + 1}/{n_arr})"
                evenements.append(dict(zone_id=z["id"], couleur=z["couleur"], date=j["date"],
                                       heure=f"{h0 + k:02d}:00", type="ARROSAGE", volume_l=int(v),
                                       statut="PREVU", raison=raison, energie_kwh=0))
                trajectoire.append(dict(date=j["date"], heure=f"{h0 + k:02d}:00", niveau_l=round(niveau)))

        # pompage aux heures de soleil, apres les arrosages du matin
        prod = [round(production_solaire_kw(r, p["puissance_crete_kwc"], p["ratio_performance"]), 3)
                for r in j["rayonnement_w_m2"]]
        heures_ok = heures_soleil[d]
        if d < len(jours) - 1:
            demain = besoin_jour(d + 1)
            cible = demain
            pourquoi = "remplir pour l'arrosage de demain"
            # anticipation : si les jours suivants n'ont pas assez de soleil, on remplit aussi pour eux
            k = d + 1
            while k < len(jours) - 1 and not heures_soleil[k]:
                cible += besoin_jour(k + 1)
                k += 1
                pourquoi = "remplir pour demain + jours sans soleil a venir"
            cible = min(cap_l, cible)
        else:
            cible = niveau_initial_l   # on reconstitue la reserve pour la semaine suivante
            demain = cible
            pourquoi = "reconstituer la reserve pour la semaine suivante"
        pompe_jour = 0
        for h in heures_ok:
            v = min(debit_l_h, cible - niveau, cap_l - niveau, quota_l - total_pompe)
            v = math.floor(v)
            if v <= 0:
                break
            niveau += v
            total_pompe += v
            pompe_jour += v
            evenements.append(dict(zone_id=ZONE_RESERVOIR, couleur="", date=j["date"], heure=f"{h:02d}:00",
                                   type="POMPAGE", volume_l=int(v), statut="PREVU",
                                   raison=f"soleil : {prod[h]:.2f} kW >= pompe {_fmt(p['puissance_pompe_kw'])} kW ; {pourquoi}",
                                   energie_kwh=round(v / debit_l_h * p["puissance_pompe_kw"], 3)))
            trajectoire.append(dict(date=j["date"], heure=f"{h:02d}:00", niveau_l=round(niveau)))
        # cause d'un eventuel manque demain matin
        if niveau < demain:
            if total_pompe >= quota_l - 1:
                cause_manque = "quota de nappe atteint"
            elif demain > cap_l:
                cause_manque = f"reservoir trop petit ({_fmt(p['capacite_reservoir_m3'])} m3)"
            elif not heures_ok:
                cause_manque = "pas assez de soleil pour pomper la veille"
            else:
                cause_manque = "pas assez d'heures de soleil la veille"
        resume_jours.append(dict(
            date=j["date"], et0_mm=j["et0_mm"], pluie_mm=j["pluie_mm"],
            rayonnement_w_m2=j["rayonnement_w_m2"], production_kw=prod, heures_pompage=heures_ok,
            besoin_l=round(sum(demandes[(d, z["id"])]["besoin_l"] for z in zones)),
            arrose_l=int(arrose_jour), pompe_l=int(pompe_jour),
            niveau_matin_l=round(niveau_matin), niveau_soir_l=round(niveau)))

    # ---- 4. totaux + comparaison avec l'arrosage traditionnel ----
    arrose = sum(e["volume_l"] for e in evenements if e["type"] == "ARROSAGE")
    energie = sum(e["energie_kwh"] for e in evenements)
    et0_moy = reco["climat"]["et0_mm_jour"]
    # submersion : toute la surface, rendement 0,6, sans tenir compte de la meteo
    traditionnel = sum(z["kc"] * et0_moy * z["surface_m2"] / p["rendement_submersion"] for z in zones) * len(jours)
    totaux = dict(
        besoin_l=round(sum(it["besoin_l"] for it in demandes.values())),
        arrosage_prevu_l=int(arrose), pompe_prevu_l=int(total_pompe), quota_l=int(quota_l),
        energie_kwh=round(energie, 2), eau_traditionnelle_l=round(traditionnel),
        eau_economisee_l=round(max(0, traditionnel - arrose)),
        niveau_initial_l=round(niveau_initial_l), niveau_final_l=round(niveau),
        capacite_reservoir_l=round(cap_l))
    return dict(
        parcelle_id=reco["parcelle_id"], date_debut=jours[0]["date"] if jours else None,
        source_meteo=meteo["source"], parametres=p, ce_eau_dS_m=ce_eau, arrosages_par_jour=n_arr,
        zones=[dict(id=z["id"], couleur=z["couleur"], culture=z["culture"], priorite=PRIORITE.get(z["couleur"], 3),
                    surface_m2=z["surface_m2"]) for z in zones],
        jours=resume_jours, evenements=evenements, trajectoire_reservoir=trajectoire, totaux=totaux,
        genere_le=datetime.datetime.now().isoformat(timespec="seconds"),
        mention="Estimations - donnees simulees - prototype")
