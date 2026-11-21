"""Règles de traitement par zone.

Reprend les scénarios A–D de l'ancien agents/prediction_agent.py (ScientificRuleModel),
rule_plants/rule_microbes/rule_months de l'ancien app.py et les calculs de
agents/model_interface.py. La couleur n'est PAS recalculée ici : elle vient de
diagnostics.couleur.couleur_case().

Sortie au format du contrat LandProfile, champ zones[].traitement :
    {"strategie", "plantes", "microbes", "amendements", "mois_avant_sain"}
"""
import math

from . import seuils as S

ROUGE, ORANGE, VERT = "ROUGE", "ORANGE", "VERT"


def mois_avant_sain(cd: float, vitesse: float) -> int:
    """Mois pour ramener le Cd sous le seuil sain : (Cd - 1) / vitesse d'extraction."""
    if cd <= S.CD_SEUIL_SAIN or vitesse <= 0:
        return 0
    return math.ceil((cd - S.CD_SEUIL_SAIN) / vitesse)


def amendements_ph(ph: float) -> list[str]:
    if ph <= S.PH_ACIDE_STRESS:
        return ["chaux"]          # remonte le pH, immobilise le Cd
    if ph >= S.PH_ALCALIN_STRESS:
        return ["gypse"]          # corrige la sodicité
    return []


def traitement_zone(couleur: str, ce: float, ph: float, cd: float, pb: float) -> dict:
    """Traitement d'une zone à partir de sa couleur et de ses valeurs les plus défavorables
    (en pratique le max de CE, Cd, Pb et le pH le plus extrême des cases de la zone)."""
    salin = ce >= S.CE_STRESS
    metal_toxique = cd >= S.CD_LIMITE_UE
    pb_eleve = pb >= S.PB_RISQUE_MODERE

    if couleur == VERT:
        return {
            "strategie": "culture",
            "plantes": ["Grenadier", "Olivier"],
            "microbes": ["Azospirillum brasilense", "Glomus mosseae"],
            "amendements": amendements_ph(ph),
            "mois_avant_sain": 0,
        }

    if couleur == ROUGE and metal_toxique and salin:
        # Scénario B : double stress (Cd > 3 et CE > 6)
        return {
            "strategie": "phytoextraction",
            "plantes": ["Atriplex halimus", "Noccaea caerulescens"],
            "microbes": ["Glomus mosseae", "Rhizophagus irregularis", "Bacillus subtilis MR1"],
            "amendements": ["biochar"] + amendements_ph(ph),
            "mois_avant_sain": mois_avant_sain(cd, S.VITESSE_EXTRACTION_CD["Noccaea caerulescens"]),
        }

    if couleur == ROUGE and metal_toxique:
        # Scénario C : métaux dominants, salinité faible (Sedum ne tolère pas CE > 4)
        plantes = ["Sedum alfredii", "Noccaea caerulescens"] if ce < 4 else ["Noccaea caerulescens"]
        vitesse = S.VITESSE_EXTRACTION_CD[plantes[0]]
        return {
            "strategie": "phytoextraction",
            "plantes": plantes,
            "microbes": ["Bacillus subtilis MR1"],
            # EDTA incompatible avec les mycorhizes ; jamais à moins de 100 m d'un point d'eau
            "amendements": ["EDTA"] + amendements_ph(ph),
            "mois_avant_sain": mois_avant_sain(cd, vitesse),
        }

    if couleur == ROUGE:
        # ROUGE à cause de la salinité sévère, du Pb ou d'un pH extrême :
        # on stabilise (Atriplex fixe Pb/Cd dans les racines) et on corrige.
        return {
            "strategie": "phytostabilisation",
            "plantes": ["Atriplex halimus"],
            "microbes": ["Glomus mosseae", "Pseudomonas putida HS1"],
            "amendements": ["biochar"] + amendements_ph(ph),
            "mois_avant_sain": mois_avant_sain(cd, S.VITESSE_EXTRACTION_CD["Atriplex halimus"]),
        }

    # ORANGE
    if cd >= S.CD_SEUIL_SAIN or pb_eleve:
        # Risque métallique modéré (ancien scénario « DualStress » orange)
        return {
            "strategie": "phytostabilisation",
            "plantes": ["Atriplex halimus", "Noccaea caerulescens"],
            "microbes": ["Glomus mosseae", "Bacillus subtilis MR1"],
            "amendements": ["biochar"] + amendements_ph(ph),
            "mois_avant_sain": mois_avant_sain(cd, S.VITESSE_EXTRACTION_CD["Noccaea caerulescens"]),
        }
    # Scénario A : salinité dominante → fourrage sûr pendant la dépollution
    return {
        "strategie": "dessalement",
        "plantes": ["Atriplex halimus"],
        "microbes": ["Pseudomonas putida HS1", "Azospirillum brasilense"],
        "amendements": ["biochar", "lessivage"] + amendements_ph(ph),
        "mois_avant_sain": 0,
    }


def culture_alimentaire_autorisee(couleur: str) -> bool:
    """Seules les zones VERT sont autorisées pour l'alimentation humaine.
    ORANGE : fourrage possible si Cd < 3 ; ROUGE : biomasse toxique, filière contrôlée."""
    return couleur == VERT


def fourrage_autorise(couleur: str, cd: float) -> bool:
    return couleur == VERT or (couleur == ORANGE and cd < S.CD_LIMITE_UE)


def volume_lessivage_m3(ce: float, texture_sol: str) -> int:
    """Volume d'eau par cycle pour lessiver les sels sous la zone racinaire
    (formule de l'ancien model_interface : CE × 4,2 + 5, corrigée par la texture)."""
    facteur = S.FACTEUR_INFILTRATION.get((texture_sol or "").lower(), 1.0)
    return max(5, int((ce * 4.2 + 5) * facteur))
