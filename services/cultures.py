"""Référentiel cultures partagé (blocs 2 et 3).

- KC : coefficients culturaux repris de l'ancien agents/models/crop_factor.pkl
  (Olivier ajouté, valeur FAO-56 mi-saison).
- CULTURES : tolérance à la salinité = seuil CEe (dS/m) sans perte de rendement,
  d'après FAO Irrigation & Drainage Paper 29 (Ayers & Westcot). Les valeurs marquées
  « approx. » ne figurent pas dans la table FAO et sont des estimations à affiner.
"""

KC = {
    "Tomate": 1.3,
    "Grenadier": 1.0,
    "Atriplex": 0.6,
    "Salicorne": 0.5,
    "Orge": 0.8,
    "Palmier dattier": 0.9,
    "Luzerne": 1.1,
    "Blé": 1.0,
    "Riz": 1.6,
    "Maïs": 1.3,
    "Coton": 1.2,
    "Pomme de terre": 1.1,
    "Canne à sucre": 1.7,
    "Olivier": 0.7,
}

# besoin_eau : FAIBLE / MOYEN / ELEVE (sert au regroupement par besoin en eau du bloc 2)
CULTURES = [
    {"nom": "Salicorne", "ce_seuil": 40.0, "alimentaire": False, "usage": "fourrage / halophyte (approx.)", "besoin_eau": "FAIBLE"},
    {"nom": "Atriplex", "ce_seuil": 20.0, "alimentaire": False, "usage": "fourrage ovin", "besoin_eau": "FAIBLE"},
    {"nom": "Orge", "ce_seuil": 8.0, "alimentaire": True, "usage": "céréale / fourrage", "besoin_eau": "FAIBLE"},
    {"nom": "Coton", "ce_seuil": 7.7, "alimentaire": False, "usage": "fibre", "besoin_eau": "MOYEN"},
    {"nom": "Blé", "ce_seuil": 6.0, "alimentaire": True, "usage": "céréale", "besoin_eau": "MOYEN"},
    {"nom": "Palmier dattier", "ce_seuil": 4.0, "alimentaire": True, "usage": "fruit", "besoin_eau": "MOYEN"},
    {"nom": "Olivier", "ce_seuil": 4.0, "alimentaire": True, "usage": "fruit / huile (approx.)", "besoin_eau": "FAIBLE"},
    {"nom": "Grenadier", "ce_seuil": 4.0, "alimentaire": True, "usage": "fruit (approx.)", "besoin_eau": "MOYEN"},
    {"nom": "Riz", "ce_seuil": 3.0, "alimentaire": True, "usage": "céréale", "besoin_eau": "ELEVE"},
    {"nom": "Tomate", "ce_seuil": 2.5, "alimentaire": True, "usage": "maraîchage", "besoin_eau": "ELEVE"},
    {"nom": "Luzerne", "ce_seuil": 2.0, "alimentaire": False, "usage": "fourrage", "besoin_eau": "ELEVE"},
    {"nom": "Maïs", "ce_seuil": 1.7, "alimentaire": True, "usage": "céréale", "besoin_eau": "ELEVE"},
    {"nom": "Pomme de terre", "ce_seuil": 1.7, "alimentaire": True, "usage": "maraîchage", "besoin_eau": "MOYEN"},
    {"nom": "Canne à sucre", "ce_seuil": 1.7, "alimentaire": True, "usage": "industriel", "besoin_eau": "ELEVE"},
]


def cultures_compatibles(couleur: str, ce: float) -> list[dict]:
    """Cultures possibles sur terre nue selon la couleur de la zone et sa CE.
    ROUGE : aucune culture de production (phytoremédiation seulement, cf. traitement).
    ORANGE : pas d'alimentaire humain. VERT : tout ce qui tolère la CE."""
    if couleur == "ROUGE":
        return []
    return [c for c in CULTURES
            if c["ce_seuil"] >= ce and (couleur == "VERT" or not c["alimentaire"])]
