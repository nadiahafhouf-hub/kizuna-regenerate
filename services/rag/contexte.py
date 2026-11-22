"""Tout ce que le chatbot sait d'une parcelle, en documents courts à indexer dans Qdrant, + actions recommandées.

Sources (chaque bloc est facultatif : une source en panne ne bloque jamais le chatbot) :
  bloc 1  diagnostic (zones, CE, Cd, Pb, traitement, mois avant sol sain)
  bloc 2  cultures recommandées (terre nue) / plantées, nombre de plants, eau par jour
  bloc 3  agent d'irrigation (plan, consignes du jour, semaine, stockages, pompe solaire), réseau goutte-à-goutte
  bloc 4  passeport (chaîne de hash, statut)
  solaire alertes et réglages photovoltaïques
"""
from django.urls import reverse


def _s(x):
    return "" if x is None else str(x)


def _docs_diagnostic(pid, docs, faits):
    from services import demo_data
    p = demo_data.parcel(pid)
    faits["parcelle"] = {"id": pid, "nom": p.get("name"), "agriculteur": p.get("farmer"), "region": p.get("region"),
                         "surface_m2": p.get("area_m2"), "taille": p.get("size"), "sol": p.get("texture"),
                         "pire_zone": p.get("worst"), "part_saine_pct": p.get("healthy_pct")}
    docs.append(dict(titre=f"Parcelle {pid}", url=reverse("diagnostics:index", args=[pid]), source="diagnostic",
                     texte=f"Parcelle {pid} « {p.get('name')} », agriculteur {p.get('farmer')}, région {p.get('region')}. "
                           f"Surface {p.get('area_m2')} m² ({p.get('size')}), sol {p.get('texture')}, "
                           f"{p.get('zones_count')} zones, part saine (VERT) {p.get('healthy_pct')} %, "
                           f"pire zone {p.get('worst')}. Dernière mesure : {p.get('last_reading')}."))
    for z in demo_data.zones(pid):
        t = z.get("traitement") or {}
        docs.append(dict(
            titre=f"Diagnostic zone {z['id']} ({z['couleur']})", url=reverse("diagnostics:index", args=[pid]),
            source="diagnostic",
            texte=f"Zone {z['id']} de la parcelle {pid} : couleur {z['couleur']}, {z['surface_m2']} m² "
                  f"({z.get('share_pct')} % de la parcelle). Salinité CE max {z.get('ce_max')} dS/m, cadmium max "
                  f"{z.get('cd_max')} mg/kg, plomb max {z.get('pb_max')} mg/kg. Culture alimentaire autorisée : "
                  f"{'oui' if z.get('culture_alimentaire_autorisee') else 'non'}. Traitement : {t.get('strategie')}, "
                  f"plantes {', '.join(t.get('plantes') or [])}, microbes {', '.join(t.get('microbes') or [])}, "
                  f"amendements {', '.join(t.get('amendements') or [])}. Sol sain dans environ "
                  f"{t.get('mois_avant_sain')} mois."))


def _docs_cultures(pid, docs, faits):
    from advisor.logic import recommandation
    r = recommandation(pid, cache_only=True)
    faits["cultures"] = [{"zone": z["id"], "culture": z["culture"], "nb_plants": z.get("nb_plants"),
                          "eau_l_jour": z.get("besoin_litres_jour")} for z in r["zones"]]
    for z in r["zones"]:
        alt = ", ".join(a["nom"] for a in z.get("alternatives") or [])
        docs.append(dict(
            titre=f"Cultures zone {z['id']}", url=reverse("advisor:index", args=[pid]), source="cultures (bloc 2)",
            texte=f"Zone {z['id']} ({z['couleur']}) : culture recommandée {z['culture']} ({z.get('note')}), "
                  f"{z.get('nb_plants')} plants à l'espacement de {z.get('espacement_m')} m, besoin en eau "
                  f"{z.get('besoin_litres_jour')} L/jour (ETc {z.get('etc_mm_jour')} mm/j, lessivage "
                  f"{round((z.get('lr') or 0) * 100)} %), alimentaire : {'oui' if z.get('alimentaire') else 'non'}. "
                  + (f"Autres choix : {alt}. " if alt else "")
                  + (f"Microbes : {', '.join(z.get('microbes') or [])}. " if z.get("microbes") else "")
                  + ("Collecter l'eau de drainage (zone polluée). " if z.get("collecte_drainage") else "")))


def _docs_irrigation(pid, docs, faits, actions):
    from irrigation.agent import dernier_reseau
    from irrigation.logic import consignes_agent, plan_actif
    url = reverse("irrigation:index", args=[pid])
    plan_db = plan_actif(pid, creer=False)
    if plan_db is None:
        actions.append(dict(id="plan_irrigation", label="Préparer le plan d'irrigation", url=url))
    else:
        c = consignes_agent(plan_db)
        j, s = c["jour"], c["semaine"]
        faits["irrigation"] = {"statut": plan_db.statut, "aujourdhui": j["titre"], "eau_semaine_m3": s["eau_m3"],
                               "economie_pct": s["economie_pct"]}
        statut = {"BROUILLON": "plan proposé, pas encore validé", "VALIDE": "plan validé, pas encore automatique",
                  "AUTO": "irrigation automatique en marche", "MANUEL": "l'agriculteur a repris la main"}
        docs.append(dict(titre="Plan d'irrigation : aujourd'hui", url=url + "#agent", source="agent d'irrigation",
                         texte=f"Statut du plan : {statut.get(plan_db.statut, plan_db.statut)}. " + c["texte"]))
        for z in s["par_zone"]:
            docs.append(dict(
                titre=f"Irrigation zone {z['zone']}", url=url + "#agent", source="agent d'irrigation",
                texte=f"Zone {z['zone']} : terre {'déjà plantée' if z['etat'] == 'PLANTEE' else 'nue (nouvelle plantation)'}, "
                      f"culture {z['culture']}, {_s(z['nb_plantes']) or 'nombre inconnu de'} plantes (source : {z['source']}). "
                      f"Irrigation actuelle : {z['irrigation_actuelle']}, {z['actuel_m3']} m³/semaine ; avec le plan "
                      f"goutte-à-goutte : {z['plan_m3']} m³/semaine (économie {z['economie_pct']} %). "
                      f"Réseau goutte-à-goutte conçu : {'oui' if z['reseau'] else 'non'}."))
        docs.append(dict(
            titre="Pompe solaire et stockage de l'eau", url=url, source="agent d'irrigation",
            texte=f"La pompe ne tourne qu'au soleil (0 kWh du réseau) : cette semaine {s['pompe_m3']} m³ pompés sur un "
                  f"quota de nappe de {s['quota_m3']} m³ ({s['quota_pct']} %), {s['pompe_kwh']} kWh utilisés sur "
                  f"{s['solaire_kwh']} kWh produits. Stockage total {s['stockage_m3']} m³ (réservoir + bassin), "
                  f"{s['stock_fin_m3']} m³ en fin de semaine. Les jours de soleil, l'eau des prochains jours est mise "
                  "en réserve ; arrosage à 6 h par gravité depuis le réservoir."))
        if plan_db.statut == "BROUILLON":
            actions.append(dict(id="valider_plan", label="Valider le plan d'irrigation", url=url + "#agent"))
        elif plan_db.statut in ("VALIDE", "MANUEL"):
            actions.append(dict(id="automatique", label="Passer l'irrigation en automatique", url=url + "#agent"))
        actions.append(dict(id="voir_agent", label="Voir les consignes de l'agent", url=url + "#agent"))
    net = dernier_reseau(pid)
    if net is None:
        actions.append(dict(id="concevoir_reseau", label="Concevoir le réseau goutte-à-goutte",
                            url=reverse("irrigation:network", args=[pid])))
    else:
        for c in net.conseil:
            docs.append(dict(
                titre=f"Réseau goutte-à-goutte {c.get('zone')}", url=reverse("irrigation:network", args=[pid]),
                source="réseau goutte-à-goutte",
                texte=f"Réseau conçu sur image satellite, zone {c.get('zone')} : {c.get('n_plantes')} plantes "
                      f"(dont {c.get('a_replanter') or 0} à replanter), {c.get('goutteurs_par_plante')} goutteurs de "
                      f"{c.get('debit_goutteur_l_h')} L/h par plante, {c.get('longueur_rampes_m')} m de rampes."))
        actions.append(dict(id="voir_reseau", label="Voir le réseau goutte-à-goutte",
                            url=reverse("irrigation:network", args=[pid])))


def _docs_passeport(pid, docs, faits, actions):
    from services import demo_data
    pp = demo_data.passport(pid)
    faits["passeport"] = {"id": pp["id"], "intact": pp["intact"], "evenements": len(pp["events"])}
    docs.append(dict(
        titre="Passeport du sol", url=reverse("passport:index", args=[pid]), source="passeport (bloc 4)",
        texte=f"Passeport {pp['id']} : chaîne de {len(pp['events'])} événements, "
              f"{'intacte (non modifiée)' if pp['intact'] else 'MODIFIÉE (falsifiée)'}, statut {pp['status']}, "
              f"{pp['food_area_m2']} m² autorisés pour les cultures alimentaires. Le QR code renvoie vers la page "
              "publique de vérification : l'acheteur voit l'historique scellé par empreintes (hash)."))
    actions.append(dict(id="passeport", label="Voir le passeport du sol", url=reverse("passport:index", args=[pid])))


def _docs_solaire(pid, docs, faits, actions):
    from energy.models import Alerte, ConfigSolaire
    url = reverse("energy:index", args=[pid])
    alertes = list(Alerte.objects.filter(parcelle_id=pid, lue=False)[:5])
    cfg = ConfigSolaire.objects.filter(parcelle_id=pid).first()
    txt = "Volet solaire : "
    txt += (f"puits de {cfg.profondeur_m:g} m, panneaux de {cfg.panneau_wc} Wc. " if cfg else "pas encore configuré. ")
    txt += ("Alertes : " + " ; ".join(f"{a.get_type_display()} ({a.get_niveau_display()})" for a in alertes) + "."
            if alertes else "Aucune alerte sur les panneaux.")
    faits["solaire"] = {"alertes": len(alertes)}
    docs.append(dict(titre="Panneaux solaires", url=url, source="volet solaire", texte=txt))
    if alertes:
        actions.append(dict(id="solaire", label="Voir les alertes des panneaux solaires", url=url))


def contexte_parcelle(pid):
    """(docs, faits, actions) pour une parcelle. Chaque source est protégée : une erreur ne bloque pas le reste."""
    docs, faits, actions = [], {}, []
    for f, args in ((_docs_diagnostic, (docs, faits)), (_docs_cultures, (docs, faits)),
                    (_docs_irrigation, (docs, faits, actions)), (_docs_passeport, (docs, faits, actions)),
                    (_docs_solaire, (docs, faits, actions))):
        try:
            f(pid, *args)
        except Exception as e:   # noqa: BLE001 - le chatbot fonctionne même si un bloc est en panne
            faits.setdefault("erreurs", []).append(f"{f.__name__}: {type(e).__name__}")
    actions.append(dict(id="cultures", label="Voir les cultures conseillées", url=reverse("advisor:index", args=[pid])))
    actions.append(dict(id="diagnostic", label="Voir le diagnostic du sol", url=reverse("diagnostics:index", args=[pid])))
    vus, uniques = set(), []
    for a in actions:
        if a["id"] not in vus:
            vus.add(a["id"])
            uniques.append(a)
    return docs, faits, uniques
