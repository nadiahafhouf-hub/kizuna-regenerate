"""Calcul de l'eau (FAO-56 simplifie). Sans Django. Reutilise par l'irrigation.

1 mm d'eau sur 1 m2 = 1 litre.
"""
CE_EAU_DS_M = 2.0      # salinite de l'eau d'irrigation (dS/m) - hypothese
EFFICACITE_GOUTTE = 0.9
LR_MAX = 0.3
COEF_PLUIE_EFFICACE = 0.7

TEXTURES = {  # facteur sur l'eau + nombre d'arrosages par jour
    "sable": dict(nom="sable", facteur=1.10, arrosages=3),    # l'eau traverse vite : petites doses frequentes
    "limon": dict(nom="limon", facteur=1.00, arrosages=2),
    "argile": dict(nom="argile", facteur=0.95, arrosages=1),  # garde l'eau : une seule dose
}


def texture_info(texte):
    t = (texte or "").lower()
    if t.startswith("sabl"):
        return TEXTURES["sable"]
    if t.startswith("argil"):
        return TEXTURES["argile"]
    return TEXTURES["limon"]


def fraction_lessivage(couleur, seuil_ce, ce_eau=CE_EAU_DS_M):
    """LR = CE_eau / (5 x seuil - CE_eau), plafonne. Zone ROUGE : 0 (le cadmium ne doit pas descendre)."""
    if couleur == "ROUGE":
        return 0.0
    den = 5 * seuil_ce - ce_eau
    if den <= 0:
        return LR_MAX
    return min(ce_eau / den, LR_MAX)


def besoin_eau_jour(kc, couverture, seuil_ce, couleur, surface_m2, et0_mm, pluie_mm,
                    facteur_texture=1.0, ce_eau=CE_EAU_DS_M):
    """Besoin d'une zone pour un jour. Renvoie un dict avec unites dans les cles."""
    etc = kc * et0_mm
    pluie_eff = COEF_PLUIE_EFFICACE * pluie_mm
    net_l = max(0.0, etc - pluie_eff) * couverture * surface_m2
    lr = fraction_lessivage(couleur, seuil_ce, ce_eau)
    brut_l = net_l / (1 - lr) / EFFICACITE_GOUTTE * facteur_texture
    return dict(etc_mm=round(etc, 2), pluie_efficace_mm=round(pluie_eff, 2), lr=round(lr, 3),
                net_l=round(net_l, 1), brut_l=round(brut_l, 1))
