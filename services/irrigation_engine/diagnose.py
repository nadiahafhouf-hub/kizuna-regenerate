"""Diagnostic (scores), bilan d'eau actuel vs optimal, recommandations priorisees."""

import math
from .crops import get_crop, SYSTEMES, RDI, MOIS
from . import water


def _clip(x, a=0.0, b=100.0):
    return max(a, min(b, x))


def score_disposition(zinfo, crop):
    r = zinfo["rangs"]
    if not zinfo["plantee"] or r is None:
        return None, {}
    sr_o, sp_o = crop["ecart_opt"]
    sr = r["ecart_rang_m"] if not math.isnan(r["ecart_rang_m"]) else sr_o
    sp = r["ecart_plante_m"]
    dens = zinfo["n_plantes"] / max(zinfo["surface_m2"], 1) * 1e4
    dens_th = 1e4 / (sr * sp)
    dens_opt = 1e4 / (sr_o * sp_o)
    ratio = dens_th / dens_opt
    s_dens = 100 * math.exp(-abs(math.log(ratio)) / 0.6)
    in_r = crop["ecart_rang_m"][0] * 0.9 <= sr <= crop["ecart_rang_m"][1] * 1.1
    in_p = crop["ecart_plante_m"][0] * 0.9 <= sp <= crop["ecart_plante_m"][1] * 1.1
    s_range = 50 * in_r + 50 * in_p
    s_reg = _clip(100 * (1 - r["cv_ecart"] / 0.4))
    s_ali = _clip(100 * (1 - r["ecart_alignement_m"] / (0.25 * sp)))
    miss = len(r["manquants"])
    frac = miss / max(miss + zinfo["n_plantes"], 1)
    s_gap = _clip(100 * (1 - 2 * frac))
    total = 0.30 * s_dens + 0.20 * s_range + 0.20 * s_reg + 0.15 * s_ali + 0.15 * s_gap
    return total, {
        "densite_reelle_pl_ha": dens,
        "densite_rangs_pl_ha": dens_th,
        "densite_optimale_pl_ha": dens_opt,
        "ecart_rang_m": sr,
        "ecart_plante_m": sp,
        "ecart_rang_ok": in_r,
        "ecart_plante_ok": in_p,
        "regularite": s_reg,
        "alignement": s_ali,
        "manquants": miss,
        "pct_manquants": 100 * frac,
        "s_densite": s_dens,
        "s_ecartements": s_range,
        "s_trous": s_gap,
    }


def score_irrigation(zinfo, dz):
    irr = zinfo["irrigation"]
    typ = irr["type"]
    if typ == "aucun":
        return 0.0
    eff = SYSTEMES[typ]["efficience"]
    s = 40 * eff / 0.90
    s += 35 * irr.get("couverture_plantes_pct", 0) / 100
    if typ == "gravitaire":
        s += 15 * dz.get("gc", 0.3)
        s += 5
    elif typ == "aspersion":
        hz = irr.get("hors_zone_m2", 0) / max(irr.get("surface_mouillee_m2", 1), 1)
        s += 15 * (1 - min(1, hz)) * dz.get("gc", 0.5)
        s += 5
    else:
        s += 15 * (1 - irr.get("part_inutile_pct", 0) / 100)
        a = irr.get("ecart_angle_rangs_deg")
        s += 10 * (1 - min(a, 45) / 45) if a is not None else 5
    return _clip(s)


def analyser(cfg, terrain, conception):
    zones_out, recos = [], []
    prix = cfg.get("prix_eau_dt_m3", 0.20)

    def R(prio, zone, titre, detail, gain_m3=0.0):
        recos.append(
            {
                "priorite": prio,
                "zone": zone,
                "titre": titre,
                "detail": detail,
                "gain_m3_an": gain_m3,
            }
        )

    tot_act, tot_opt, tot_rdi, tot_new = [0.0] * 12, [0.0] * 12, [0.0] * 12, [0.0] * 12
    for zinfo, dz in zip(terrain.zones, conception.zones):
        zc = cfg["zones"][zinfo["id"]]
        if dz.get("vide"):
            continue
        crop = get_crop(zinfo["culture"])
        nom = zinfo["nom"]
        s_disp, det = score_disposition(zinfo, crop)
        s_irr = score_irrigation(zinfo, dz)
        sys_opt = "aspersion" if dz.get("mode") == "aspersion" else "goutte_a_goutte"
        mens_opt, p_opt = water.besoins_zone(
            cfg, zinfo, dz, sys_opt, sys_opt != "aspersion", dz["surface_utile_m2"]
        )
        mens_rdi, _ = water.besoins_zone(
            cfg,
            zinfo,
            dz,
            sys_opt,
            sys_opt != "aspersion",
            dz["surface_utile_m2"],
            rdi=True,
        )
        act = water.consommation_actuelle(cfg, zc, zinfo, dz)
        prog, raw = (
            water.programme(cfg, zinfo, dz, mens_opt)
            if sys_opt != "aspersion"
            else ([], 0)
        )
        opt_m3 = sum(r["m3"] for r in mens_opt)
        rdi_m3 = sum(r["m3"] for r in mens_rdi)
        existante = zinfo["plantee"] or zinfo["irrigation"]["type"] != "aucun"
        for m in range(12):
            if not existante:
                tot_new[m] += (
                    mens_rdi[m]["m3"] if zc.get("appliquer_rdi") else mens_opt[m]["m3"]
                )
                continue
            tot_act[m] += (
                act["mensuel"][m]
                if act["source"] != "valeur declaree par l'utilisateur"
                else act["m3_an"] / 12
            )
            tot_opt[m] += mens_opt[m]["m3"]
            tot_rdi[m] += mens_rdi[m]["m3"]
        z_out = {
            "nom": nom,
            "culture": crop["nom"],
            "culture_key": zinfo["culture"],
            "plantee": zinfo["plantee"],
            "surface_m2": zinfo["surface_m2"],
            "n_plantes_detectees": zinfo["n_plantes"],
            "score_disposition": s_disp,
            "detail_disposition": det,
            "score_irrigation": s_irr,
            "irrigation_actuelle": {
                k: v
                for k, v in zinfo["irrigation"].items()
                if k not in ("plantes_couvertes", "asperseurs")
            },
            "conso_actuelle_m3_an": act["m3_an"],
            "source_conso": act["source"],
            "notes_gaspillage": act["notes"],
            "conso_optimale_m3_an": opt_m3,
            "conso_rdi_m3_an": rdi_m3,
            "parametres_optimal": p_opt,
            "mensuel_optimal": mens_opt,
            "programme": prog,
            "dose_max_mm": raw,
            "conception": {
                k: dz.get(k)
                for k in (
                    "mode",
                    "ecart_rang_m",
                    "ecart_plante_m",
                    "n_plantes_total",
                    "goutteurs_par_plante",
                    "debit_goutteur_l_h",
                    "espacement_goutteurs_m",
                    "debit_par_plante_l_h",
                    "lignes_par_rang",
                    "pw",
                    "gc",
                    "alimentation",
                    "longueur_max_rampe_m",
                    "autoregulant_requis",
                    "debit_zone_l_h",
                    "n_goutteurs",
                    "surface_utile_m2",
                    "alerte_rampe",
                )
            },
            "secteurs": [
                {
                    k: s[k]
                    for k in (
                        "debit_l_h",
                        "L_porte_rampe_m",
                        "diam_porte_rampe_mm",
                        "hf_porte_rampe_m",
                        "hf_rampe_m",
                        "n_rangs",
                    )
                }
                for s in dz["secteurs"]
            ],
            "n_plantes_a_planter": len(dz.get("plantes_a_planter", [])),
        }
        zones_out.append(z_out)

        # ---------------- recommandations : irrigation
        gain = max(0.0, act["m3_an"] - opt_m3)
        typ = zinfo["irrigation"]["type"]
        if typ in ("gravitaire", "aspersion") and sys_opt == "goutte_a_goutte":
            R(
                "Haute",
                nom,
                f"Passer de {SYSTEMES[typ]['nom'].lower()} au goutte-a-goutte",
                f"Efficience {SYSTEMES[typ]['efficience']*100:.0f}% -> 90%, et seul le sol au pied des plantes est humidifie "
                f"(Kr = {p_opt['kr']:.2f}). Economie estimee {gain:,.0f} m3/an ({gain*prix:,.0f} DT/an).",
                gain,
            )
        elif typ == "aucun" and zinfo["plantee"]:
            R(
                "Haute",
                nom,
                "Installer un goutte-a-goutte",
                "Zone plantee sans irrigation detectee.",
            )
        irr = zinfo["irrigation"]
        if typ == "goutte_a_goutte":
            cov = irr.get("couverture_plantes_pct", 100)
            if cov < 95 and zinfo["n_plantes"] > 0:
                n_unc = zinfo["n_plantes"] - irr.get("n_plantes_couvertes", 0)
                R(
                    "Haute",
                    nom,
                    f"{n_unc} plantes hors de portee des lignes ({100-cov:.0f}%)",
                    "Ajouter / deplacer des rampes pour que chaque plante soit desservie (voir plan optimal). "
                    "Les plantes non couvertes sont en stress et poussent l'agriculteur a sur-irriguer tout le secteur.",
                )
            if irr.get("part_inutile_pct", 0) > 5:
                R(
                    "Haute",
                    nom,
                    f"Supprimer/boucher {irr['longueur_inutile_m']:.0f} m de ligne sur sol nu",
                    f"{irr['part_inutile_pct']:.0f}% du reseau arrose des emplacements sans plante.",
                    gain * 0.5,
                )
            a = irr.get("ecart_angle_rangs_deg")
            if a is not None and a > 15:
                R(
                    "Moyenne",
                    nom,
                    f"Lignes non paralleles aux rangs (ecart {a:.0f} deg)",
                    "Reposer les rampes le long des rangs : une rampe par rang (2 pour les arbres adultes).",
                )
            if gain > 0.05 * opt_m3:
                R(
                    "Moyenne",
                    nom,
                    "Ajuster la duree d'arrosage au programme mensuel",
                    f"Economie estimee {gain:,.0f} m3/an en supprimant les gaspillages et le surdosage.",
                    gain,
                )
        if dz.get("autoregulant_requis"):
            R(
                "Moyenne",
                nom,
                "Utiliser des goutteurs autoregulants",
                f"Rangs plus longs que la longueur maxi d'une rampe classique ({dz['longueur_max_rampe_m']:.0f} m) : "
                "sans autoregulant, le debit varie de plus de 10 % entre le debut et la fin de la rampe.",
            )
        if dz.get("alerte_rampe"):
            R("Haute", nom, "Rangs trop longs", dz["alerte_rampe"])
        if len(dz["secteurs"]) > 1:
            R(
                "Info",
                nom,
                f"Diviser la zone en {len(dz['secteurs'])} secteurs",
                "Le debit de la zone depasse la capacite de la pompe : arroser les secteurs l'un apres l'autre.",
            )
        if zinfo["culture"] in RDI and rdi_m3 < opt_m3:
            f, months = RDI[zinfo["culture"]]
            R(
                "Moyenne",
                nom,
                "Irrigation deficitaire controlee (RDI)",
                f"Apporter {f*100:.0f}% de la dose en {', '.join(MOIS[m] for m in months)} (phase peu sensible) : "
                f"-{opt_m3-rdi_m3:,.0f} m3/an supplementaires avec un impact limite sur le rendement.",
                opt_m3 - rdi_m3,
            )
        if crop["type"] == "maraichage":
            R(
                "Moyenne",
                nom,
                "Paillage plastique ou organique",
                "Reduit l'evaporation du sol de 20-30 % et les adventices ; reduire alors la dose de ~15 % apres controle tensiometre.",
                0.15 * opt_m3,
            )

        # ---------------- recommandations : disposition
        if s_disp is not None:
            d = det
            if d["manquants"] > 0 and crop["type"] in ("arbre", "arbuste"):
                R(
                    "Moyenne",
                    nom,
                    f"Replanter {d['manquants']} plants manquants",
                    "Positions indiquees en orange sur le plan. Ne pas laisser de goutteurs sur les emplacements vides en attendant.",
                )
            ratio = d["densite_rangs_pl_ha"] / d["densite_optimale_pl_ha"]
            if ratio < 0.75:
                R(
                    "Basse" if crop["type"] == "arbre" else "Moyenne",
                    nom,
                    "Plantation trop peu dense",
                    f"{d['densite_rangs_pl_ha']:.0f} pl/ha contre ~{d['densite_optimale_pl_ha']:.0f} pl/ha recommandes "
                    f"(ecartement {crop['ecart_opt'][0]} x {crop['ecart_opt'][1]} m). L'eau et le sol sont sous-utilises ; "
                    + (
                        "intercaler des arbres sur le rang a la prochaine plantation."
                        if crop["type"] == "arbre"
                        else "resserrer les rangs a la prochaine saison."
                    ),
                )
            elif ratio > 1.25 or (
                not d["ecart_rang_ok"] and d["ecart_rang_m"] < crop["ecart_rang_m"][0]
            ):
                R(
                    "Moyenne",
                    nom,
                    "Plantation trop dense",
                    f"{d['densite_rangs_pl_ha']:.0f} pl/ha contre ~{d['densite_optimale_pl_ha']:.0f} : concurrence pour l'eau "
                    "et la lumiere, besoins en eau plus eleves. "
                    + (
                        "Envisager un eclaircissage."
                        if crop["type"] == "arbre"
                        else "Elargir les ecartements la prochaine saison."
                    ),
                )
            if d["regularite"] < 60 or d["alignement"] < 60:
                R(
                    "Basse",
                    nom,
                    "Disposition irreguliere",
                    "Ecartements ou alignement irreguliers : chaque plante recoit une quantite d'eau differente. "
                    + (
                        "Pour les nouvelles plantations, utiliser un piquetage au cordeau."
                        if crop["type"] == "arbre"
                        else "Replanter en rangs droits a ecartement fixe a la prochaine saison."
                    ),
                )
        elif not zinfo["plantee"]:
            R(
                "Info",
                nom,
                f"Plantation recommandee : {crop['nom']} en {dz['ecart_rang_m']} x {dz['ecart_plante_m']} m",
                f"{dz['n_plantes_total']} plants, rangs orientes selon la longueur de la parcelle "
                "(rampes plus longues, moins de vannes). Voir le plan.",
            )

    # ---------------- recommandations generales
    tot_a, tot_o = sum(tot_act), sum(tot_opt)
    R(
        "Haute",
        "Tout le terrain",
        "Arroser tot le matin ou la nuit",
        "Entre 18h et 8h l'evaporation et la derive par le vent sont minimales (surtout pour l'aspersion).",
    )
    R(
        "Haute",
        "Tout le terrain",
        "Piloter avec tensiometres et compteur",
        "Installer 2 sondes par secteur (30 et 60 cm). Arroser quand la tension depasse ~30-40 cbar (maraichage) "
        "ou ~60-80 cbar (arbres). Relever le compteur chaque semaine et comparer au programme.",
    )
    R(
        "Moyenne",
        "Tout le terrain",
        "Entretien du reseau",
        "Nettoyer les filtres a chaque arrosage (ou des que la pression chute de 0.5 bar), purger les rampes chaque mois, "
        "acidifier si l'eau est calcaire, verifier les fuites. Un reseau colmate perd vite son uniformite.",
    )
    if cfg.get("salinite_eau_dS_m"):
        R(
            "Moyenne",
            "Tout le terrain",
            f"Eau saline ({cfg['salinite_eau_dS_m']} dS/m)",
            "Une fraction de lessivage est incluse dans les doses. Ne jamais laisser secher le bulbe humide "
            "(les sels remontent) et profiter des pluies d'automne pour lessiver.",
        )
    prio = {"Haute": 0, "Moyenne": 1, "Basse": 2, "Info": 3}
    recos.sort(key=lambda r: (prio[r["priorite"]], -r["gain_m3_an"]))

    # ---------------- verification capacite pompe au mois de pointe
    peak = max(range(12), key=lambda m: tot_opt[m] + tot_new[m])
    heures = 0.0
    for z, dz in zip(zones_out, [c for c in conception.zones if not c.get("vide")]):
        p = z["programme"]
        if not p:
            # aspersion : volume/jour / debit
            heures += (
                z["mensuel_optimal"][peak]["brut_mm_j"]
                * dz["surface_utile_m2"]
                / 1000
                / max(dz["debit_zone_l_h"] / 1000, 1e-6)
            )
            continue
        line = p[peak]
        if line["intervalle_j"]:
            heures += (
                len(dz["secteurs"]) * line["duree_min"] / 60 / line["intervalle_j"]
            )
    pompe = cfg.get("pompe", {})
    hmax = pompe.get("heures_max_jour", 12)
    if heures > hmax:
        R(
            "Haute",
            "Station de pompage",
            "Capacite de pompage insuffisante au mois de pointe",
            f"Il faut {heures:.1f} h/jour en {MOIS[peak]} pour {hmax} h disponibles : augmenter le debit de la pompe, "
            "construire un bassin de stockage (rempli la nuit) ou reduire la surface irriguee.",
        )
        recos.sort(key=lambda r: (prio[r["priorite"]], -r["gain_m3_an"]))
    p_bar = pompe.get("pression_bar")
    if p_bar and p_bar * 10.2 < conception.hmt_m:
        R(
            "Haute",
            "Station de pompage",
            "Pression de la pompe insuffisante",
            f"HMT necessaire ~{conception.hmt_m:.0f} m ({conception.hmt_m/10.2:.1f} bar) pour {p_bar} bar disponibles.",
        )
        recos.sort(key=lambda r: (prio[r["priorite"]], -r["gain_m3_an"]))

    bilan = {
        "actuel_m3_an": tot_a,
        "optimal_m3_an": tot_o,
        "rdi_m3_an": sum(tot_rdi),
        "economie_m3_an": tot_a - tot_o,
        "economie_pct": 100 * (tot_a - tot_o) / tot_a if tot_a else 0,
        "economie_avec_rdi_pct": 100 * (tot_a - sum(tot_rdi)) / tot_a if tot_a else 0,
        "economie_dt_an": (tot_a - tot_o) * prix,
        "prix_eau_dt_m3": prix,
        "nouvelles_zones_m3_an": sum(tot_new),
        "mensuel_nouvelles": tot_new,
        "mensuel_actuel": tot_act,
        "mensuel_optimal": tot_opt,
        "mensuel_rdi": tot_rdi,
        "mois_pointe": MOIS[peak],
        "pointe_m3_jour": (tot_opt[peak] + tot_new[peak])
        / [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][peak],
        "heures_pompage_pointe": heures,
        "hmt_m": conception.hmt_m,
    }
    return {"zones": zones_out, "recommandations": recos, "bilan": bilan}
