"""Decisions de l'automate (capteur d'humidite simule, vanne, pompe). Sans Django."""
import hashlib

HUMIDITE_BASE = {"sable": 12.0, "limon": 18.0, "argile": 25.0}   # % volumique apres une journee seche


def humidite_simulee(texture, pluie_jour_mm, pluie_veille_mm, arrose_veille, graine=""):
    """Capteur SIMULE : base selon la texture + pluie + arrosage de la veille + petit bruit stable."""
    h = HUMIDITE_BASE.get(texture, 18.0)
    h += 1.5 * min(pluie_jour_mm, 20) + 0.8 * min(pluie_veille_mm, 20)
    if arrose_veille:
        h += 6
    bruit = int(hashlib.md5(graine.encode()).hexdigest()[:4], 16) / 0xFFFF * 6 - 3   # entre -3 et +3
    return round(max(2.0, min(60.0, h + bruit)), 1)


def decider_arrosage(volume_l, pluie_mm, humidite_pct, niveau_l, seuil_pluie_mm, seuil_humidite_pct):
    """Renvoie (statut, volume_l, raison) juste avant d'ouvrir la vanne."""
    if pluie_mm >= seuil_pluie_mm:
        return "ANNULE", 0, f"annule : {pluie_mm:g} mm de pluie (seuil {seuil_pluie_mm:g} mm)"
    if humidite_pct >= seuil_humidite_pct:
        return "ANNULE", 0, f"annule : sol deja humide ({humidite_pct:g} % >= {seuil_humidite_pct:g} %)"
    if niveau_l <= 0:
        return "ANNULE", 0, "annule : reservoir vide"
    if niveau_l < volume_l:
        v = int(niveau_l)
        return "FAIT", v, f"fait mais reduit a {v} L : reservoir presque vide (humidite {humidite_pct:g} %)"
    return "FAIT", int(volume_l), f"fait : vanne ouverte puis fermee (humidite {humidite_pct:g} %)"


def decider_pompage(volume_l, niveau_l, capacite_l, deja_pompe_l, quota_l):
    """Le reservoir ne deborde jamais et le quota n'est jamais depasse."""
    v = int(min(volume_l, capacite_l - niveau_l, quota_l - deja_pompe_l))
    if v <= 0:
        if deja_pompe_l >= quota_l:
            return "ANNULE", 0, "annule : quota de nappe atteint"
        return "ANNULE", 0, "annule : reservoir plein"
    if v < volume_l:
        return "FAIT", v, f"fait mais reduit a {v} L (reservoir plein ou quota)"
    return "FAIT", v, "fait : pompage solaire nappe -> reservoir"
