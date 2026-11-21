"""LA fonction couleur du projet. Ne pas la dupliquer ailleurs : tout le monde importe
`from diagnostics.couleur import couleur_case`.

Reprise de rule_zone() de l'ancien app.py. Priorité ROUGE > ORANGE > VERT.
"""
from services import seuils as S

ROUGE, ORANGE, VERT = "ROUGE", "ORANGE", "VERT"
COULEURS = (ROUGE, ORANGE, VERT)


def couleur_case(ce: float, ph: float, cd: float, pb: float) -> str:
    """Renvoie "ROUGE", "ORANGE" ou "VERT" pour une case à partir de CE (dS/m), pH,
    Cd (mg/kg) et Pb (mg/kg)."""
    if (cd >= S.CD_LIMITE_UE or pb >= S.PB_RISQUE_ELEVE or ce >= S.CE_SEVERE
            or ph <= S.PH_ACIDE_SEVERE or ph >= S.PH_ALCALIN_SEVERE):
        return ROUGE
    if (ce >= S.CE_STRESS or cd >= S.CD_SEUIL_SAIN or pb >= S.PB_RISQUE_MODERE
            or ph <= S.PH_ACIDE_STRESS or ph >= S.PH_ALCALIN_STRESS):
        return ORANGE
    return VERT
