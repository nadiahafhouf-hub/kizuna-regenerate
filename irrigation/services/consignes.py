"""Consignes de l'agent d'irrigation pour l'agriculteur : journée et semaine. Sans Django.

Tout est déduit du planning calculé (services/planning.py) : aucun chiffre n'est inventé ici.
Gemini (services/agent_ia.py) ne fait que reformuler ce résultat en langage simple.
"""
import datetime

CHALEUR_C = 35          # au-dessus : alerte forte chaleur
QUOTA_ALERTE = 0.9      # 90 % du quota de nappe

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _jour_fr(date_iso):
    d = datetime.date.fromisoformat(date_iso)
    return f"{JOURS[d.weekday()]} {d.day:02d}/{d.month:02d}"


def _duree(minutes):
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m:02d}" if h else f"{m} min"


def _m3(litres):
    return round(litres / 1000, 2)


def consignes(plan, meteo=None, zones_agent=None, jour_index=0):
    """plan = sortie de generer_planning (avec « evenements » à jour) ; jour_index = jour de la semaine à détailler."""
    p = plan["parametres"]
    jours = plan["jours"]
    if not jours:
        return {"jour": None, "semaine": None, "alertes": [], "texte": "Pas de planning."}
    jour_index = max(0, min(len(jours) - 1, int(jour_index)))
    j = jours[jour_index]
    meteo_j = {m["date"]: m for m in (meteo or {}).get("jours", [])}.get(j["date"], {})
    zones = {z["id"]: z for z in plan.get("zones", [])}
    infos = {a["id"]: a for a in (zones_agent or [])}
    debit_grav = p.get("debit_goutte_m3_h", 3.0) * 1000
    evts = [e for e in plan["evenements"] if e["date"] == j["date"]]

    # ---------- journée ----------
    actions, alertes = [], []
    for zid, z in zones.items():
        arr = sorted([e for e in evts if e["type"] == "ARROSAGE" and e["zone_id"] == zid], key=lambda e: e["heure"])
        if not arr:
            continue
        faits = [e for e in arr if e["statut"] != "ANNULE" and e["volume_l"] > 0]
        culture = z.get("culture") or ""
        if not faits:
            actions.append(dict(heure=arr[0]["heure"], type="annule", zone=zid, couleur=z.get("couleur"),
                                titre=f"Zone {zid} ({culture}) : pas d'arrosage",
                                detail=arr[0].get("raison") or "aucun besoin aujourd'hui"))
            continue
        litres = sum(e["volume_l"] for e in faits)
        debit = z.get("debit_reseau_l_h") or debit_grav
        detail = f"{litres:,} L en {len(faits)} fois, environ {_duree(litres / debit * 60)} de vanne ouverte".replace(",", " ")
        nb = z.get("nb_plantes") or (infos.get(zid) or {}).get("nb_plantes")
        if nb:
            detail += f", soit {litres / nb:.1f} L par plante ({nb} plantes)"
        reduit = sorted({r.strip() for e in faits for r in (e.get("raison") or "").split(" ; ") if r.startswith("reduit")})
        if reduit:
            detail += " — " + " ; ".join(reduit)
            alertes.append(dict(niveau="moyen", texte=f"Zone {zid} : arrosage réduit ({reduit[0]})."))
        actions.append(dict(heure=faits[0]["heure"], type="arrosage", zone=zid, couleur=z.get("couleur"),
                            titre=f"{faits[0]['heure']} — arroser la zone {zid} ({culture})", detail=detail,
                            volume_l=litres))
    pompes = sorted([e for e in evts if e["type"] == "POMPAGE" and e["statut"] != "ANNULE" and e["volume_l"] > 0],
                    key=lambda e: e["heure"])
    if pompes:
        v = sum(e["volume_l"] for e in pompes)
        kwh = sum(e.get("energie_kwh", 0) for e in pompes)
        fin = int(pompes[-1]["heure"][:2]) + 1
        st = j.get("stockages_soir") or {}
        stock = f"réservoir {_m3(st.get('reservoir_l', 0))} m³" + (
            f" + bassin {_m3(st.get('bassin_l', 0))} m³" if p.get("bassin_m3") else "")
        actions.append(dict(heure=pompes[0]["heure"], type="pompage", zone="RESERVOIR",
                            titre=f"{pompes[0]['heure']}–{fin:02d}:00 — pompe solaire : nappe → stockage",
                            detail=f"{_m3(v)} m³ pompés avec {kwh:.1f} kWh du soleil ; le soir : {stock}. "
                                   f"{pompes[0]['raison'].split(' ; ')[-1].capitalize()}.",
                            volume_l=v))
    elif j.get("heures_pompage") == []:
        alertes.append(dict(niveau="info", texte=f"{_jour_fr(j['date'])} : pas assez de soleil pour faire tourner la pompe "
                                                 f"({p['puissance_pompe_kw']:g} kW) ; on arrose avec l'eau stockée."))
    actions.sort(key=lambda a: a["heure"])

    tmax = meteo_j.get("tmax_c")
    if tmax is not None and tmax >= CHALEUR_C:
        alertes.append(dict(niveau="haut", texte=f"Forte chaleur ({tmax} °C) : arroser uniquement tôt le matin, "
                                                 "vérifier qu'aucun goutteur n'est bouché."))
    if j["pluie_mm"] >= p["seuil_pluie_mm"]:
        alertes.append(dict(niveau="info", texte=f"Pluie prévue ({j['pluie_mm']:g} mm) : l'arrosage est annulé, "
                                                 "la pluie suffit."))
    for zid, z in zones.items():
        if z.get("couleur") == "ROUGE":
            alertes.append(dict(niveau="moyen", texte=f"Zone {zid} polluée : goutte-à-goutte seulement, ne jamais "
                                                      "réutiliser l'eau de drainage de cette zone."))

    # ---------- semaine ----------
    t = plan["totaux"]
    quota_pct = t["pompe_prevu_l"] / t["quota_l"] if t.get("quota_l") else 0
    if quota_pct >= QUOTA_ALERTE:
        alertes.append(dict(niveau="haut", texte=f"Quota de nappe presque atteint ({quota_pct * 100:.0f} %) : "
                                                 "les zones vertes sont servies en premier."))
    sans_arrosage = [_jour_fr(d["date"]) for d in jours if d["arrose_l"] == 0]
    par_zone = []
    for c in plan.get("comparaison", []):
        z = zones.get(c["zone_id"], {})
        a = infos.get(c["zone_id"], {})
        par_zone.append(dict(
            zone=c["zone_id"], couleur=z.get("couleur"), etat=z.get("etat") or a.get("etat"),
            culture=z.get("culture"), nb_plantes=z.get("nb_plantes"), source=z.get("source"),
            # zone pas encore irriguée : on compare avec une submersion de référence (et on le dit)
            irrigation_actuelle=("aucune aujourd'hui (réf. : submersion)" if c["irrigation_actuelle"] == "aucun"
                                 else a.get("irrigation_actuelle_nom") or c["irrigation_actuelle"]),
            actuel_m3=_m3(c["actuel_l"]), plan_m3=_m3(c["plan_l"]), economie_m3=_m3(c["economie_l"]),
            economie_pct=round(100 * c["economie_l"] / c["actuel_l"]) if c["actuel_l"] else 0,
            reseau=bool(z.get("debit_reseau_l_h")), note=z.get("note")))
    solaire = t.get("solaire_kwh") or sum(d.get("energie_solaire_kwh", 0) for d in jours)
    semaine = dict(
        du=_jour_fr(jours[0]["date"]), au=_jour_fr(jours[-1]["date"]),
        eau_m3=_m3(t["arrosage_prevu_l"]), besoin_m3=_m3(t["besoin_l"]),
        actuel_m3=_m3(t["eau_traditionnelle_l"]), economie_m3=_m3(t["eau_economisee_l"]),
        economie_pct=round(100 * t["eau_economisee_l"] / t["eau_traditionnelle_l"]) if t["eau_traditionnelle_l"] else 0,
        pompe_m3=_m3(t["pompe_prevu_l"]), quota_m3=_m3(t["quota_l"]), quota_pct=round(quota_pct * 100),
        solaire_kwh=round(solaire, 1), pompe_kwh=t["energie_kwh"],
        reseau_electrique_kwh=0,   # la pompe ne tourne qu'au soleil
        stockage_m3=_m3(t.get("capacite_reservoir_l", 0)), stock_fin_m3=_m3(t["niveau_final_l"]),
        jours_sans_arrosage=sans_arrosage, par_zone=par_zone)

    jour = dict(date=j["date"], titre=_jour_fr(j["date"]), index=jour_index,
                meteo=dict(tmax=tmax, tmin=meteo_j.get("tmin_c"), pluie=j["pluie_mm"], et0=j["et0_mm"]),
                actions=actions, eau_m3=_m3(j["arrose_l"]), pompe_m3=_m3(j["pompe_l"]))
    vus, uniques = set(), []
    for a in alertes:
        if a["texte"] not in vus:
            vus.add(a["texte"])
            uniques.append(a)
    res = dict(jour=jour, semaine=semaine, alertes=uniques,
               source_meteo=plan.get("source_meteo"), mention=plan.get("mention"))
    res["texte"] = texte_simple(res)
    return res


def texte_simple(c):
    """Consignes en français simple, sans IA (toujours disponible)."""
    j, s = c["jour"], c["semaine"]
    m = j["meteo"]
    l = [f"Aujourd'hui ({j['titre']})"
         + (f" : {m['tmax']}°/{m['tmin']}°" if m.get("tmax") is not None else "")
         + (f", pluie {m['pluie']:g} mm" if m.get("pluie") else "") + "."]
    l += [f"• {a['titre']} : {a['detail']}" for a in j["actions"]] or ["• Rien à faire aujourd'hui."]
    l.append(f"Cette semaine ({s['du']} → {s['au']}) : {s['eau_m3']:g} m³ d'eau au goutte-à-goutte au lieu de "
             f"{s['actuel_m3']:g} m³ avec l'irrigation actuelle ou une submersion (−{s['economie_pct']} %), "
             f"{s['pompe_m3']:g} m³ pompés au soleil ({s['pompe_kwh']:g} kWh sur {s['solaire_kwh']:g} kWh produits, "
             "0 kWh du réseau).")
    if s["jours_sans_arrosage"]:
        l.append("Pas d'arrosage : " + ", ".join(s["jours_sans_arrosage"]) + ".")
    l += [f"⚠ {a['texte']}" for a in c["alertes"]]
    l.append("Si vous êtes d'accord, validez le plan : les vannes et la pompe suivront ce programme automatiquement.")
    return "\n".join(l)
