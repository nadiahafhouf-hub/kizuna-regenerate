"""Rapport HTML autonome (images integrees) + exports JSON / CSV."""

import base64
import csv
import json
from html import escape
from .crops import MOIS, SYSTEMES, SOLS
from .water import climat


def _img(path):
    return "data:image/png;base64," + base64.b64encode(open(path, "rb").read()).decode()


def _f(x, d=0):
    if x is None:
        return "-"
    return f"{x:,.{d}f}".replace(",", " ")


def _badge(score):
    if score is None:
        return '<span class="b gray">n/a</span>'
    c = "green" if score >= 75 else "orange" if score >= 50 else "red"
    return f'<span class="b {c}">{score:.0f}/100</span>'


CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:1150px;margin:24px auto;padding:0 18px;color:#1f2328;line-height:1.5}
h1{font-size:26px;margin-bottom:2px}h2{border-bottom:2px solid #e6e8eb;padding-bottom:4px;margin-top:36px}h3{margin-bottom:6px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}
.kpi{background:#f6f8fa;border-radius:10px;padding:14px}.kpi .v{font-size:24px;font-weight:700}.kpi .l{font-size:13px;color:#57606a}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0 16px}th,td{border-bottom:1px solid #e6e8eb;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa}td.n{text-align:right;font-variant-numeric:tabular-nums}
.b{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;color:#fff}
.green{background:#1a7f37}.orange{background:#bf8700}.red{background:#cf222e}.gray{background:#8c959f}
.Haute{color:#cf222e;font-weight:700}.Moyenne{color:#bf8700;font-weight:700}.Basse{color:#57606a;font-weight:700}.Info{color:#0969da;font-weight:700}
img{max-width:100%;border:1px solid #e6e8eb;border-radius:6px}.warn{background:#fff8c5;border:1px solid #d4a72c;padding:8px 12px;border-radius:6px}
.small{font-size:12.5px;color:#57606a}
"""


def rapport_html(cfg, T, C, res, imgs, path, extra_html=""):
    b = res["bilan"]
    clim = climat(cfg)
    h = [
        f"<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'><title>Rapport irrigation - {escape(cfg.get('nom_projet','Terrain'))}</title>"
        f"<style>{CSS}</style></head><body>"
    ]
    h.append(
        f"<h1>Diagnostic et plan d'irrigation optimise</h1><div class='small'>{escape(cfg.get('nom_projet','Terrain'))} - "
        f"{cfg['dimensions_m']['largeur']} x {cfg['dimensions_m']['longueur']} m - climat : {escape(clim['nom'])} - "
        f"sol : {SOLS[cfg.get('sol','limoneux')]['nom'].lower()}</div>"
    )
    h.append(
        "<div class='kpis'>"
        f"<div class='kpi'><div class='v'>{_f(b['actuel_m3_an'])} m3</div><div class='l'>consommation actuelle estimee / an</div></div>"
        f"<div class='kpi'><div class='v'>{_f(b['optimal_m3_an'])} m3</div><div class='l'>avec le systeme optimise / an</div></div>"
        f"<div class='kpi'><div class='v'>-{_f(b['economie_pct'])} %</div><div class='l'>economie d'eau ({_f(b['economie_m3_an'])} m3/an)</div></div>"
        f"<div class='kpi'><div class='v'>-{_f(b['economie_avec_rdi_pct'])} %</div><div class='l'>avec irrigation deficitaire (RDI)</div></div>"
        "</div>"
    )
    h.append(
        f"<p>Economie financiere estimee : <b>{_f(b['economie_dt_an'])} DT/an</b> (eau a {b['prix_eau_dt_m3']} DT/m3, hors energie de pompage). "
        f"Mois de pointe : <b>{b['mois_pointe']}</b>, {_f(b['pointe_m3_jour'],1)} m3/jour, "
        f"{_f(b['heures_pompage_pointe'],1)} h de pompage/jour. Hauteur manometrique necessaire : ~{_f(b['hmt_m'])} m "
        f"({b['hmt_m']/10.2:.1f} bar).</p>"
    )
    h.append(extra_html)
    if T.warnings:
        h.append(
            "<div class='warn'><b>Avertissements de lecture de l'image</b><ul>"
            + "".join(f"<li>{escape(w)}</li>" for w in T.warnings)
            + "</ul></div>"
        )

    h.append(
        "<h2>1. Recommandations (par priorite)</h2><table><tr><th>Priorite</th><th>Zone</th><th>Action</th><th>Detail</th><th>Gain m3/an</th></tr>"
    )
    for r in res["recommandations"]:
        h.append(
            f"<tr><td class='{r['priorite']}'>{r['priorite']}</td><td>{escape(r['zone'])}</td><td><b>{escape(r['titre'])}</b></td>"
            f"<td>{escape(r['detail'])}</td><td class='n'>{_f(r['gain_m3_an']) if r['gain_m3_an'] else ''}</td></tr>"
        )
    h.append(
        "</table><p class='small'>Les gains ne s'additionnent pas tous (certains se recoupent). L'economie totale fiable est celle du bilan ci-dessus.</p>"
    )

    h.append("<h2>2. Analyse de l'existant</h2>")
    h.append(f"<img src='{_img(imgs['existant'])}' alt='analyse existant'>")
    h.append(
        "<table><tr><th>Zone</th><th>Culture</th><th>Surface</th><th>Plantes detectees</th><th>Ecartement mesure</th>"
        "<th>Disposition</th><th>Irrigation actuelle</th><th>Couverture</th><th>Score irrigation</th></tr>"
    )
    for z in res["zones"]:
        d = z["detail_disposition"]
        irr = z["irrigation_actuelle"]
        ec = f"{d['ecart_rang_m']:.1f} x {d['ecart_plante_m']:.1f} m" if d else "-"
        h.append(
            f"<tr><td><b>{escape(z['nom'])}</b></td><td>{escape(z['culture'])}{'' if z['plantee'] else ' (a planter)'}</td>"
            f"<td class='n'>{_f(z['surface_m2'])} m2</td><td class='n'>{z['n_plantes_detectees']}</td><td>{ec}</td>"
            f"<td>{_badge(z['score_disposition'])}</td><td>{SYSTEMES[irr['type']]['nom']}</td>"
            f"<td class='n'>{_f(irr.get('couverture_plantes_pct'))} %</td><td>{_badge(z['score_irrigation'] if irr['type']!='aucun' or z['plantee'] else None)}</td></tr>"
        )
    h.append("</table>")
    for z in res["zones"]:
        d = z["detail_disposition"]
        if not d:
            continue
        h.append(
            f"<h3>{escape(z['nom'])} - detail de la disposition</h3><table>"
            f"<tr><td>Densite reelle (plantes / surface de la zone)</td><td class='n'>{_f(d['densite_reelle_pl_ha'])} pl/ha</td></tr>"
            f"<tr><td>Densite des rangs mesures / optimale</td><td class='n'>{_f(d['densite_rangs_pl_ha'])} / {_f(d['densite_optimale_pl_ha'])} pl/ha</td></tr>"
            f"<tr><td>Ecartement entre rangs / sur le rang</td><td class='n'>{d['ecart_rang_m']:.2f} m {'OK' if d['ecart_rang_ok'] else 'hors norme'} / "
            f"{d['ecart_plante_m']:.2f} m {'OK' if d['ecart_plante_ok'] else 'hors norme'}</td></tr>"
            f"<tr><td>Regularite des ecartements</td><td class='n'>{_f(d['regularite'])}/100</td></tr>"
            f"<tr><td>Alignement des rangs</td><td class='n'>{_f(d['alignement'])}/100</td></tr>"
            f"<tr><td>Plantes manquantes</td><td class='n'>{d['manquants']} ({_f(d['pct_manquants'])} %)</td></tr></table>"
        )
        if z["notes_gaspillage"]:
            h.append(
                "<ul>"
                + "".join(f"<li>{escape(n)}</li>" for n in z["notes_gaspillage"])
                + "</ul>"
            )

    h.append("<h2>3. Systeme optimal propose</h2>")
    h.append(f"<img src='{_img(imgs['plan'])}' alt='plan optimal'>")
    h.append(
        "<table><tr><th>Zone</th><th>Plantation</th><th>Rampes</th><th>Goutteurs / plante</th><th>Debit / plante</th>"
        "<th>Sol humidifie</th><th>Alimentation</th><th>Debit zone</th><th>Secteurs</th></tr>"
    )
    for z in res["zones"]:
        c = z["conception"]
        if c.get("mode") == "aspersion":
            h.append(
                f"<tr><td><b>{escape(z['nom'])}</b></td><td>couverture integrale</td><td>asperseurs 12 x 12 m basse pression</td>"
                f"<td>-</td><td>-</td><td>100 %</td><td>-</td><td class='n'>{_f(c['debit_zone_l_h']/1000,1)} m3/h</td><td>{len(z['secteurs'])}</td></tr>"
            )
            continue
        mode = {
            "existant": "existante",
            "nouvelle_plantation": "nouvelle",
            "restructuration": "a restructurer",
            "arbres_existants": "arbres existants epars, surface par arbre",
        }.get(c["mode"], c["mode"])
        h.append(
            f"<tr><td><b>{escape(z['nom'])}</b></td><td>{c['ecart_rang_m']:.1f} x {c['ecart_plante_m']:.2f} m ({mode}), "
            f"{_f(c['n_plantes_total'])} plants{(' a planter' if c['mode']=='nouvelle_plantation' else ', dont '+str(z['n_plantes_a_planter'])+' a replanter') if z['n_plantes_a_planter'] else ''}</td>"
            f"<td>{c['lignes_par_rang']} par rang, PE 16 mm{', autoregulant' if c['autoregulant_requis'] else ''}</td>"
            f"<td class='n'>{c['goutteurs_par_plante']:.1f} x {c['debit_goutteur_l_h']:.1f} L/h (tous les {c['espacement_goutteurs_m']:.2f} m)</td>"
            f"<td class='n'>{c['debit_par_plante_l_h']:.1f} L/h</td><td class='n'>{c['pw']*100:.0f} %</td>"
            f"<td>par {'le milieu' if c['alimentation']=='milieu' else 'un bout'} (max {c['longueur_max_rampe_m']:.0f} m)</td>"
            f"<td class='n'>{_f(c['debit_zone_l_h']/1000,2)} m3/h</td><td>{len(z['secteurs'])}</td></tr>"
        )
    h.append(
        "</table><h3>Secteurs et hydraulique</h3><table><tr><th>Secteur</th><th>Zone</th><th>Rangs</th><th>Debit</th>"
        "<th>Porte-rampe</th><th>Perte porte-rampe</th><th>Perte rampe</th></tr>"
    )
    k = 0
    for z, dz in zip(res["zones"], [c for c in C.zones if not c.get("vide")]):
        for s in dz["secteurs"]:
            k += 1
            h.append(
                f"<tr><td><b>{s.get('label','S'+str(k))}</b></td><td>{escape(z['nom'])}</td><td class='n'>{s['n_rangs']}</td>"
                f"<td class='n'>{_f(s['debit_l_h']/1000,2)} m3/h</td><td>PE {s['diam_porte_rampe_mm']} mm, {_f(s['L_porte_rampe_m'])} m</td>"
                f"<td class='n'>{s['hf_porte_rampe_m']:.2f} m</td><td class='n'>{s['hf_rampe_m']:.2f} m</td></tr>"
            )
    p = C.principal
    h.append(
        f"</table><p>Conduite principale : <b>PE {p['diam_mm']} mm</b>, {_f(p['longueur_m'])} m, debit max {_f(p['debit_max_l_h']/1000,1)} m3/h "
        f"(un secteur a la fois), vitesse {p['vitesse_m_s']:.2f} m/s, perte {p['hf_m']:.2f} m. "
        "Les secteurs fonctionnent l'un apres l'autre : la pompe n'alimente jamais plus d'un secteur.</p>"
    )

    h.append("<h2>4. Besoins en eau et programme d'arrosage</h2>")
    h.append(f"<img src='{_img(imgs['mensuel'])}' alt='besoins mensuels'>")
    h.append(
        "<table><tr><th>Zone</th><th>Actuel m3/an</th><th>Optimise m3/an</th><th>Avec RDI</th><th>Economie</th><th>Kr</th><th>Efficience</th></tr>"
    )
    for z in res["zones"]:
        a, o = z["conso_actuelle_m3_an"], z["conso_optimale_m3_an"]
        po = z["parametres_optimal"]
        h.append(
            f"<tr><td>{escape(z['nom'])}</td><td class='n'>{_f(a)}</td><td class='n'>{_f(o)}</td><td class='n'>{_f(z['conso_rdi_m3_an'])}</td>"
            f"<td class='n'>{_f(100*(a-o)/a) + ' %' if a else 'nouvelle zone'}</td><td class='n'>{po['kr']:.2f}</td><td class='n'>{po['efficience']*100:.0f} %</td></tr>"
        )
    h.append("</table>")
    for z in res["zones"]:
        if not z["programme"]:
            if z["conception"].get("mode") == "aspersion":
                h.append(
                    f"<h3>{escape(z['nom'])}</h3><table><tr><th>Mois</th>"
                    + "".join(f"<th>{m}</th>" for m in MOIS)
                    + "</tr><tr><td>mm/jour</td>"
                    + "".join(
                        f"<td class='n'>{r['brut_mm_j']:.1f}</td>"
                        for r in z["mensuel_optimal"]
                    )
                    + "</tr></table>"
                )
            continue
        h.append(
            f"<h3>{escape(z['nom'])} - programme (dose max par arrosage {z['dose_max_mm']:.0f} mm)</h3><table><tr><th>Mois</th>"
            "<th>ETc mm/j</th><th>Besoin brut mm/j</th><th>Litres / plante / jour</th><th>Arroser tous les</th><th>Duree par arrosage</th><th>m3/jour zone</th></tr>"
        )
        for r, mo in zip(z["programme"], z["mensuel_optimal"]):
            if not r["intervalle_j"]:
                h.append(
                    f"<tr><td>{MOIS[r['mois']]}</td><td colspan='6' class='small'>pas d'irrigation (repos / hors saison / pluie suffisante)</td></tr>"
                )
                continue
            h.append(
                f"<tr><td>{MOIS[r['mois']]}</td><td class='n'>{mo['etc_mm_j']:.1f}</td><td class='n'>{mo['brut_mm_j']:.1f}</td>"
                f"<td class='n'>{r['l_plante_j']:.1f}</td><td class='n'>{r['intervalle_j']} j</td>"
                f"<td class='n'>{int(r['duree_min']//60)} h {int(r['duree_min']%60):02d}</td><td class='n'>{r['m3_jour_zone']:.1f}</td></tr>"
            )
        h.append("</table>")

    h.append(
        "<h2>5. Liste du materiel (estimation)</h2><table><tr><th>Article</th><th>Quantite</th><th>Unite</th></tr>"
    )
    for it in C.nomenclature():
        h.append(
            f"<tr><td>{escape(it['article'])}</td><td class='n'>{_f(it['quantite'])}</td><td>{it['unite']}</td></tr>"
        )
    h.append(
        "</table><p class='small'>Quantites avec ~3-5 % de marge. Verifier avec votre fournisseur ; ajouter raccords, tes, coudes et colliers selon le terrain.</p>"
    )

    h.append(
        "<h2>6. Methode et hypotheses</h2><ul class='small'>"
        "<li>Echelle : dimensions saisies / taille de l'image en pixels. Zones : couleur la plus proche de la legende (espace Lab).</li>"
        "<li>Plantes : taches de la couleur des plantes (plan) ou indice de vegetation ExG (photo). Rangs : direction du plus proche voisin, regroupement perpendiculaire.</li>"
        "<li>Besoins : ETc = ET0 x Kc (FAO-56), pluie efficace FAO/AGLW, reduction Kr pour l'irrigation localisee (moyenne Keller-Karmeli / Freeman-Garzoli / Decroix), "
        "efficiences : gravitaire 55 %, aspersion 75 %, goutte-a-goutte 90 %. Fraction de lessivage FAO-29 si la salinite de l'eau est donnee.</li>"
        "<li>Goutteurs : sol humidifie cible >= 33 % de la surface par arbre (Keller). Rampes : regle des 20 % de variation de pression, Hazen-Williams C=140, F=0.36.</li>"
        "<li>Nouvelles plantations : besoins calcules pour des arbres adultes (couronne pleine). Les premieres annees, reduire les doses (indiquer 'age_ans' dans la zone pour un calcul ajuste). Les zones nouvelles ne sont pas comptees dans l'economie.</li>"
        "<li>Consommation actuelle : estimee par le modele si vous ne donnez pas votre consommation reelle (compteur ou heures x debit) - la donner rend l'economie beaucoup plus fiable.</li>"
        "<li>Climat : moyennes indicatives. Pour un projet reel, utiliser l'ET0 de la station la plus proche (INM, CRDA, CLIMWAT/FAO).</li>"
        "</ul></body></html>"
    )
    open(path, "w", encoding="utf-8").write("\n".join(h))


def exports(res, C, outdir):
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if hasattr(o, "item"):
            return o.item()
        return o

    json.dump(
        clean(res),
        open(outdir / "resultats.json", "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=1,
    )
    with open(outdir / "besoins_mensuels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            [
                "zone",
                "mois",
                "etc_mm_j",
                "besoin_brut_mm_j",
                "m3_mois",
                "litres_plante_jour",
                "intervalle_j",
                "duree_min",
            ]
        )
        for z in res["zones"]:
            for m in range(12):
                mo = z["mensuel_optimal"][m]
                pr = z["programme"][m] if z["programme"] else {}
                w.writerow(
                    [
                        z["nom"],
                        MOIS[m],
                        round(mo["etc_mm_j"], 2),
                        round(mo["brut_mm_j"], 2),
                        round(mo["m3"], 1),
                        round(pr.get("l_plante_j", 0) or 0, 1),
                        pr.get("intervalle_j") or "",
                        round(pr.get("duree_min", 0) or 0),
                    ]
                )
    with open(outdir / "materiel.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["article", "quantite", "unite"])
        for it in C.nomenclature():
            w.writerow([it["article"], it["quantite"], it["unite"]])
