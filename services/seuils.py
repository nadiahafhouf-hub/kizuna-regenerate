"""Seuils scientifiques (repris de l'ancien config.py).

Utilisés par diagnostics.couleur.couleur_case() et services.traitement.
"""

# Cadmium (mg/kg)
CD_SEUIL_SAIN = 1.0      # en dessous : sain
CD_LIMITE_UE = 3.0       # au-dessus : toxique (limite UE)

# Plomb (mg/kg)
PB_RISQUE_MODERE = 50
PB_RISQUE_ELEVE = 85

# Salinité, conductivité électrique (dS/m)
CE_STRESS = 6.0          # stress modéré → ORANGE
CE_SEVERE = 10.0         # catastrophique → ROUGE

# pH
PH_ACIDE_SEVERE = 5.5    # en dessous → ROUGE (mobilisation des métaux)
PH_ACIDE_STRESS = 6.5    # en dessous → ORANGE
PH_ALCALIN_STRESS = 8.5  # au-dessus → ORANGE (blocage des nutriments)
PH_ALCALIN_SEVERE = 9.0  # au-dessus → ROUGE (sodicité)

# Vitesse d'extraction du Cd par les plantes (mg/kg/mois)
VITESSE_EXTRACTION_CD = {
    "Noccaea caerulescens": 0.35,
    "Sedum alfredii": 0.40,
    "Atriplex halimus": 0.50,  # scénario A salinité (base de connaissances)
}

# Facteur d'infiltration selon la texture du sol (calcul du lessivage)
FACTEUR_INFILTRATION = {
    "sableux": 0.8,
    "sablo-limoneux": 1.0,
    "limoneux": 1.2,
    "argilo-limoneux": 1.5,
}
