"""Base agronomique : cultures, climat (Tunisie), sols, systemes d'irrigation.

Sources des valeurs : FAO-56 (Allen et al., 1998) pour les Kc, FAO-24 / Keller & Bliesner
pour l'irrigation localisee, pratiques courantes en Tunisie pour les ecartements.
Ce sont des valeurs INDICATIVES : remplacez-les par vos donnees locales (CRDA, INM, station meteo).
"""

# Kc mensuel (jan..dec). 0 = culture absente / en repos (pas d'irrigation).
CROPS = {
    "olivier": {
        "nom": "Olivier",
        "type": "arbre",
        "kc": [0.50, 0.50, 0.65, 0.60, 0.55, 0.50, 0.45, 0.45, 0.55, 0.60, 0.65, 0.50],
        "ecart_rang_m": (6.0, 8.0),
        "ecart_plante_m": (4.0, 6.0),
        "ecart_opt": (7.0, 5.0),
        "diam_couronne_m": 4.0,
        "prof_racine_m": 1.2,
        "p": 0.65,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 4.0,
        "lignes_par_rang": 2,
        "tolerance_secheresse": "elevee",
    },
    "agrumes": {
        "nom": "Agrumes",
        "type": "arbre",
        "kc": [0.65, 0.65, 0.65, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.65, 0.65],
        "ecart_rang_m": (5.0, 7.0),
        "ecart_plante_m": (3.5, 5.0),
        "ecart_opt": (6.0, 4.0),
        "diam_couronne_m": 3.5,
        "prof_racine_m": 1.0,
        "p": 0.50,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 4.0,
        "lignes_par_rang": 2,
        "tolerance_secheresse": "faible",
    },
    "palmier": {
        "nom": "Palmier dattier",
        "type": "arbre",
        "kc": [0.90, 0.90, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.90, 0.90],
        "ecart_rang_m": (8.0, 10.0),
        "ecart_plante_m": (8.0, 10.0),
        "ecart_opt": (9.0, 9.0),
        "diam_couronne_m": 6.0,
        "prof_racine_m": 1.5,
        "p": 0.50,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 8.0,
        "lignes_par_rang": 2,
        "tolerance_secheresse": "moyenne",
    },
    "amandier": {
        "nom": "Amandier",
        "type": "arbre",
        "kc": [0.00, 0.40, 0.55, 0.75, 0.90, 0.90, 0.90, 0.80, 0.65, 0.50, 0.00, 0.00],
        "ecart_rang_m": (6.0, 7.0),
        "ecart_plante_m": (5.0, 6.0),
        "ecart_opt": (7.0, 5.5),
        "diam_couronne_m": 4.5,
        "prof_racine_m": 1.2,
        "p": 0.40,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 4.0,
        "lignes_par_rang": 2,
        "tolerance_secheresse": "elevee",
    },
    "pecher": {
        "nom": "Pecher / abricotier",
        "type": "arbre",
        "kc": [0.00, 0.00, 0.50, 0.70, 0.90, 0.90, 0.90, 0.80, 0.65, 0.50, 0.00, 0.00],
        "ecart_rang_m": (4.5, 6.0),
        "ecart_plante_m": (3.0, 4.5),
        "ecart_opt": (5.0, 4.0),
        "diam_couronne_m": 3.5,
        "prof_racine_m": 1.0,
        "p": 0.50,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 4.0,
        "lignes_par_rang": 2,
        "tolerance_secheresse": "faible",
    },
    "grenadier": {
        "nom": "Grenadier",
        "type": "arbre",
        "kc": [0.00, 0.00, 0.40, 0.60, 0.75, 0.80, 0.80, 0.75, 0.65, 0.50, 0.00, 0.00],
        "ecart_rang_m": (4.0, 5.0),
        "ecart_plante_m": (3.0, 4.0),
        "ecart_opt": (5.0, 3.5),
        "diam_couronne_m": 3.0,
        "prof_racine_m": 0.9,
        "p": 0.50,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 4.0,
        "lignes_par_rang": 1,
        "tolerance_secheresse": "elevee",
    },
    "figuier": {
        "nom": "Figuier",
        "type": "arbre",
        "kc": [0.00, 0.00, 0.40, 0.55, 0.70, 0.80, 0.80, 0.75, 0.60, 0.45, 0.00, 0.00],
        "ecart_rang_m": (5.0, 7.0),
        "ecart_plante_m": (4.0, 6.0),
        "ecart_opt": (6.0, 5.0),
        "diam_couronne_m": 4.0,
        "prof_racine_m": 1.0,
        "p": 0.55,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 4.0,
        "lignes_par_rang": 1,
        "tolerance_secheresse": "elevee",
    },
    "vigne": {
        "nom": "Vigne de table",
        "type": "arbuste",
        "kc": [0.00, 0.00, 0.30, 0.45, 0.70, 0.85, 0.85, 0.75, 0.55, 0.40, 0.00, 0.00],
        "ecart_rang_m": (2.5, 3.0),
        "ecart_plante_m": (1.2, 2.0),
        "ecart_opt": (3.0, 1.5),
        "diam_couronne_m": 1.2,
        "prof_racine_m": 1.0,
        "p": 0.35,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 2.0,
        "lignes_par_rang": 1,
        "tolerance_secheresse": "moyenne",
    },
    "atriplex": {
        "nom": "Atriplex halimus (halophyte)",
        "type": "arbuste",
        "kc": [0.40, 0.40, 0.45, 0.50, 0.55, 0.55, 0.55, 0.55, 0.50, 0.45, 0.40, 0.40],
        "ecart_rang_m": (1.5, 3.0),
        "ecart_plante_m": (1.0, 2.0),
        "ecart_opt": (2.0, 1.5),
        "diam_couronne_m": 1.5,
        "prof_racine_m": 1.5,
        "p": 0.70,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 2.0,
        "lignes_par_rang": 1,
        "tolerance_secheresse": "elevee",
    },
    "tamarix": {
        "nom": "Tamarix (brise-vent, phyto)",
        "type": "arbre",
        "kc": [0.50, 0.50, 0.60, 0.70, 0.75, 0.80, 0.80, 0.80, 0.75, 0.65, 0.55, 0.50],
        "ecart_rang_m": (2.0, 4.0),
        "ecart_plante_m": (1.5, 3.0),
        "ecart_opt": (3.0, 2.0),
        "diam_couronne_m": 2.5,
        "prof_racine_m": 2.0,
        "p": 0.65,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 4.0,
        "lignes_par_rang": 1,
        "tolerance_secheresse": "elevee",
    },
    "arbuste_generique": {
        "nom": "Arbuste (parametres generiques)",
        "type": "arbuste",
        "kc": [0.50] * 12,
        "ecart_rang_m": (2.0, 3.0),
        "ecart_plante_m": (1.5, 2.5),
        "ecart_opt": (2.5, 2.0),
        "diam_couronne_m": 1.8,
        "prof_racine_m": 1.2,
        "p": 0.55,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 2.0,
        "lignes_par_rang": 1,
        "tolerance_secheresse": "moyenne",
    },
    "henne": {
        "nom": "Henne (oasis de Gabes)",
        "type": "maraichage",
        "kc": [0.00, 0.00, 0.00, 0.60, 0.80, 0.90, 0.95, 0.95, 0.85, 0.70, 0.00, 0.00],
        "ecart_rang_m": (0.4, 0.6),
        "ecart_plante_m": (0.2, 0.4),
        "ecart_opt": (0.5, 0.3),
        "diam_couronne_m": 0.4,
        "prof_racine_m": 0.8,
        "p": 0.50,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 1.6,
        "lignes_par_rang": 1,
        "ecart_goutteur_m": 0.3,
        "tolerance_secheresse": "moyenne",
    },
    "orge": {
        "nom": "Orge (tolerante au sel)",
        "type": "grande_culture",
        "kc": [0.70, 1.05, 1.15, 0.90, 0.30, 0.00, 0.00, 0.00, 0.00, 0.00, 0.30, 0.45],
        "ecart_rang_m": (0.15, 0.20),
        "ecart_plante_m": (0.02, 0.05),
        "ecart_opt": (0.18, 0.03),
        "diam_couronne_m": 0.05,
        "prof_racine_m": 1.0,
        "p": 0.55,
        "systeme": "aspersion",
        "debit_goutteur_l_h": 0,
        "lignes_par_rang": 0,
        "tolerance_secheresse": "elevee",
    },
    "tomate": {
        "nom": "Tomate (saison)",
        "type": "maraichage",
        "kc": [0.00, 0.00, 0.60, 0.75, 1.10, 1.15, 1.05, 0.80, 0.00, 0.00, 0.00, 0.00],
        "ecart_rang_m": (1.0, 1.5),
        "ecart_plante_m": (0.35, 0.50),
        "ecart_opt": (1.2, 0.4),
        "diam_couronne_m": 0.5,
        "prof_racine_m": 0.7,
        "p": 0.40,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 2.0,
        "lignes_par_rang": 1,
        "ecart_goutteur_m": 0.3,
        "tolerance_secheresse": "faible",
    },
    "piment": {
        "nom": "Piment / poivron",
        "type": "maraichage",
        "kc": [0.00, 0.00, 0.60, 0.70, 0.95, 1.05, 1.05, 0.90, 0.80, 0.00, 0.00, 0.00],
        "ecart_rang_m": (0.8, 1.2),
        "ecart_plante_m": (0.30, 0.45),
        "ecart_opt": (1.0, 0.4),
        "diam_couronne_m": 0.45,
        "prof_racine_m": 0.6,
        "p": 0.30,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 2.0,
        "lignes_par_rang": 1,
        "ecart_goutteur_m": 0.3,
        "tolerance_secheresse": "faible",
    },
    "pomme_de_terre": {
        "nom": "Pomme de terre (saison)",
        "type": "maraichage",
        "kc": [0.50, 0.75, 1.10, 1.15, 0.75, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
        "ecart_rang_m": (0.7, 0.9),
        "ecart_plante_m": (0.25, 0.35),
        "ecart_opt": (0.75, 0.3),
        "diam_couronne_m": 0.4,
        "prof_racine_m": 0.5,
        "p": 0.35,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 1.6,
        "lignes_par_rang": 1,
        "ecart_goutteur_m": 0.3,
        "tolerance_secheresse": "faible",
    },
    "pasteque": {
        "nom": "Pasteque / melon",
        "type": "maraichage",
        "kc": [0.00, 0.00, 0.00, 0.40, 0.70, 1.00, 1.00, 0.75, 0.00, 0.00, 0.00, 0.00],
        "ecart_rang_m": (1.8, 2.5),
        "ecart_plante_m": (0.8, 1.2),
        "ecart_opt": (2.0, 1.0),
        "diam_couronne_m": 1.0,
        "prof_racine_m": 1.0,
        "p": 0.40,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 2.0,
        "lignes_par_rang": 1,
        "ecart_goutteur_m": 0.5,
        "tolerance_secheresse": "moyenne",
    },
    "oignon": {
        "nom": "Oignon",
        "type": "maraichage",
        "kc": [0.90, 1.00, 1.05, 1.05, 0.75, 0.00, 0.00, 0.00, 0.00, 0.70, 0.75, 0.85],
        "ecart_rang_m": (0.3, 0.4),
        "ecart_plante_m": (0.08, 0.12),
        "ecart_opt": (0.35, 0.1),
        "diam_couronne_m": 0.15,
        "prof_racine_m": 0.4,
        "p": 0.30,
        "systeme": "goutte_a_goutte",
        "debit_goutteur_l_h": 1.6,
        "lignes_par_rang": 1,
        "ecart_goutteur_m": 0.2,
        "tolerance_secheresse": "faible",
    },
    "ble": {
        "nom": "Ble (irrigation d'appoint)",
        "type": "grande_culture",
        "kc": [0.70, 1.05, 1.15, 1.10, 0.50, 0.00, 0.00, 0.00, 0.00, 0.00, 0.30, 0.40],
        "ecart_rang_m": (0.15, 0.20),
        "ecart_plante_m": (0.02, 0.05),
        "ecart_opt": (0.18, 0.03),
        "diam_couronne_m": 0.05,
        "prof_racine_m": 1.0,
        "p": 0.55,
        "systeme": "aspersion",
        "debit_goutteur_l_h": 0,
        "lignes_par_rang": 0,
        "tolerance_secheresse": "moyenne",
    },
    "luzerne": {
        "nom": "Luzerne",
        "type": "grande_culture",
        "kc": [0.60, 0.70, 0.85, 0.95, 0.95, 0.95, 0.95, 0.95, 0.90, 0.85, 0.70, 0.60],
        "ecart_rang_m": (0.15, 0.25),
        "ecart_plante_m": (0.02, 0.05),
        "ecart_opt": (0.2, 0.03),
        "diam_couronne_m": 0.05,
        "prof_racine_m": 1.2,
        "p": 0.55,
        "systeme": "aspersion",
        "debit_goutteur_l_h": 0,
        "lignes_par_rang": 0,
        "tolerance_secheresse": "moyenne",
    },
}

# ET0 moyen (mm/jour) et pluie (mm/mois), jan..dec. Valeurs indicatives (normales climatiques).
CLIMATS = {
    "tunisie_nord": {
        "nom": "Nord (Tunis, Bizerte, Beja)",
        "et0": [1.6, 2.2, 3.1, 4.0, 5.2, 6.4, 7.0, 6.5, 4.9, 3.4, 2.2, 1.6],
        "pluie": [59, 57, 47, 38, 23, 10, 3, 8, 33, 66, 56, 67],
    },
    "tunisie_centre": {
        "nom": "Centre (Kairouan, Sousse, Sfax, Sidi Bouzid)",
        "et0": [2.0, 2.7, 3.7, 4.8, 6.0, 7.2, 7.9, 7.3, 5.5, 3.9, 2.6, 1.9],
        "pluie": [26, 24, 30, 30, 23, 10, 3, 8, 30, 30, 25, 24],
    },
    "tunisie_sud_cotier": {
        "nom": "Sud cotier (Gabes, Medenine, Djerba)",
        "et0": [2.2, 2.9, 3.9, 5.0, 6.0, 7.0, 7.6, 7.2, 5.6, 4.0, 2.7, 2.1],
        "pluie": [22, 16, 20, 12, 8, 2, 0, 2, 12, 24, 22, 17],
    },
    "tunisie_sud": {
        "nom": "Sud (Gabes, Gafsa, Tozeur, Kebili)",
        "et0": [2.3, 3.2, 4.5, 6.0, 7.5, 8.8, 9.5, 8.8, 6.6, 4.6, 2.9, 2.1],
        "pluie": [14, 9, 15, 9, 6, 2, 0, 2, 6, 9, 14, 10],
    },
}

# Diametre mouille par un goutteur 4 L/h (m) et reserve utile (mm d'eau / m de sol)
SOLS = {
    "sableux": {
        "nom": "Sableux",
        "diam_mouille_m": 0.8,
        "ru_mm_m": 70,
        "infiltration_mm_h": 30,
    },
    "sablo-limoneux": {
        "nom": "Sablo-limoneux",
        "diam_mouille_m": 1.0,
        "ru_mm_m": 110,
        "infiltration_mm_h": 20,
    },
    "limoneux": {
        "nom": "Limoneux",
        "diam_mouille_m": 1.2,
        "ru_mm_m": 150,
        "infiltration_mm_h": 12,
    },
    "limono-argileux": {
        "nom": "Limono-argileux",
        "diam_mouille_m": 1.4,
        "ru_mm_m": 170,
        "infiltration_mm_h": 8,
    },
    "argileux": {
        "nom": "Argileux",
        "diam_mouille_m": 1.6,
        "ru_mm_m": 190,
        "infiltration_mm_h": 5,
    },
}

# Efficience globale d'application (part de l'eau reellement utilisee par la plante)
SYSTEMES = {
    "gravitaire": {
        "nom": "Gravitaire (submersion / seguia)",
        "efficience": 0.55,
        "localise": False,
    },
    "aspersion": {"nom": "Aspersion", "efficience": 0.75, "localise": False},
    "goutte_a_goutte": {"nom": "Goutte-a-goutte", "efficience": 0.90, "localise": True},
    "enterre": {"nom": "Goutte-a-goutte enterre", "efficience": 0.95, "localise": True},
    "aucun": {"nom": "Aucun / pluvial", "efficience": 1.0, "localise": False},
}

# Tubes PE standards : diametre exterieur (mm) -> diametre interieur approx. PN6 (mm)
PE_TUBES = [
    (16, 13.6),
    (20, 16.0),
    (25, 21.0),
    (32, 28.0),
    (40, 35.2),
    (50, 44.0),
    (63, 55.4),
    (75, 66.0),
    (90, 79.2),
    (110, 96.8),
    (125, 110.2),
    (160, 141.0),
]

# Seuil de salinite du sol tolere sans perte de rendement, ECe (dS/m) - FAO-29 (Ayers & Westcot)
ECE_SEUIL = {
    "atriplex": 15.0,
    "tamarix": 12.0,
    "arbuste_generique": 4.0,
    "henne": 4.0,
    "orge": 8.0,
    "olivier": 4.0,
    "agrumes": 1.7,
    "palmier": 4.0,
    "amandier": 1.5,
    "pecher": 1.7,
    "grenadier": 2.7,
    "figuier": 4.2,
    "vigne": 1.5,
    "tomate": 2.5,
    "piment": 1.5,
    "pomme_de_terre": 1.7,
    "pasteque": 2.2,
    "oignon": 1.2,
    "ble": 6.0,
    "luzerne": 2.0,
}

# ECe (dS/m) correspondant a 100 % de perte de rendement (FAO-29, valeurs approchees),
# utilise pour la fraction de lessivage en irrigation localisee : LR = ECw / (2 x ECe_max)
ECE_MAX = {
    "atriplex": 40.0,
    "tamarix": 30.0,
    "arbuste_generique": 12.0,
    "henne": 12.0,
    "orge": 28.0,
    "olivier": 14.0,
    "agrumes": 8.0,
    "palmier": 32.0,
    "amandier": 6.8,
    "pecher": 6.5,
    "grenadier": 10.0,
    "figuier": 12.0,
    "vigne": 12.0,
    "tomate": 12.5,
    "piment": 8.5,
    "pomme_de_terre": 10.0,
    "pasteque": 16.0,
    "oignon": 7.5,
    "ble": 20.0,
    "luzerne": 16.0,
}

# Cultures sur lesquelles l'irrigation deficitaire controlee (RDI) est bien documentee :
# coefficient applique a la dose sur les mois indiques (index 0 = janvier)
RDI = {
    "olivier": (0.70, [6, 7]),
    "amandier": (0.70, [6, 7]),
    "grenadier": (0.75, [6, 7]),
    "figuier": (0.75, [7]),
    "vigne": (0.70, [7, 8]),
}

MOIS = [
    "Jan",
    "Fev",
    "Mar",
    "Avr",
    "Mai",
    "Juin",
    "Juil",
    "Aout",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
JOURS_MOIS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def get_crop(key):
    if key not in CROPS:
        raise KeyError(f"Culture inconnue '{key}'. Disponibles : {', '.join(CROPS)}")
    return CROPS[key]


# --------------------------------------------------------------------------- correspondances de noms
import unicodedata


def _norm(s):
    s = (
        unicodedata.normalize("NFKD", str(s))
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .strip()
    )
    return s.replace("_", " ").replace("-", " ")


NOMS_CULTURES = {
    "atriplex": "atriplex",
    "atriplex halimus": "atriplex",
    "atriplex nummularia": "atriplex",
    "guetaf": "atriplex",
    "tamarix": "tamarix",
    "tamaris": "tamarix",
    "tamarix aphylla": "tamarix",
    "athel": "tamarix",
    "olivier": "olivier",
    "olea europaea": "olivier",
    "olive": "olivier",
    "palmier": "palmier",
    "palmier dattier": "palmier",
    "phoenix dactylifera": "palmier",
    "dattier": "palmier",
    "grenadier": "grenadier",
    "punica granatum": "grenadier",
    "figuier": "figuier",
    "ficus carica": "figuier",
    "amandier": "amandier",
    "prunus dulcis": "amandier",
    "pecher": "pecher",
    "abricotier": "pecher",
    "agrumes": "agrumes",
    "citrus": "agrumes",
    "oranger": "agrumes",
    "citronnier": "agrumes",
    "vigne": "vigne",
    "vitis vinifera": "vigne",
    "luzerne": "luzerne",
    "medicago sativa": "luzerne",
    "orge": "orge",
    "hordeum vulgare": "orge",
    "ble": "ble",
    "triticum": "ble",
    "henne": "henne",
    "lawsonia inermis": "henne",
    "tomate": "tomate",
    "solanum lycopersicum": "tomate",
    "piment": "piment",
    "poivron": "piment",
    "capsicum annuum": "piment",
    "pomme de terre": "pomme_de_terre",
    "pasteque": "pasteque",
    "melon": "pasteque",
    "oignon": "oignon",
    "allium cepa": "oignon",
}


def culture_depuis_nom(nom):
    """'Atriplex halimus' -> 'atriplex'. Retourne (cle, reconnu: bool)."""
    n = _norm(nom)
    if n.replace(" ", "_") in CROPS:
        return n.replace(" ", "_"), True
    if n in NOMS_CULTURES:
        return NOMS_CULTURES[n], True
    for k, v in NOMS_CULTURES.items():
        if (
            n.startswith(k)
            or k.startswith(n.split(" ")[0])
            and len(n.split(" ")[0]) > 4
        ):
            return v, True
    return "arbuste_generique", False


def sol_depuis_texture(t):
    n = _norm(t).replace(" ", "-")
    alias = {
        "sablo-limoneux": "sablo-limoneux",
        "limono-sableux": "sablo-limoneux",
        "sableux": "sableux",
        "sable": "sableux",
        "limoneux": "limoneux",
        "limon": "limoneux",
        "limono-argileux": "limono-argileux",
        "argilo-limoneux": "limono-argileux",
        "argileux": "argileux",
        "argile": "argileux",
    }
    return alias.get(n, "limoneux")


REGIONS = {
    "gabes": "tunisie_sud_cotier",
    "medenine": "tunisie_sud_cotier",
    "djerba": "tunisie_sud_cotier",
    "zarzis": "tunisie_sud_cotier",
    "tozeur": "tunisie_sud",
    "kebili": "tunisie_sud",
    "gafsa": "tunisie_sud",
    "tataouine": "tunisie_sud",
    "kairouan": "tunisie_centre",
    "sfax": "tunisie_centre",
    "sousse": "tunisie_centre",
    "monastir": "tunisie_centre",
    "mahdia": "tunisie_centre",
    "sidi bouzid": "tunisie_centre",
    "kasserine": "tunisie_centre",
    "siliana": "tunisie_nord",
    "tunis": "tunisie_nord",
    "ariana": "tunisie_nord",
    "ben arous": "tunisie_nord",
    "manouba": "tunisie_nord",
    "bizerte": "tunisie_nord",
    "beja": "tunisie_nord",
    "jendouba": "tunisie_nord",
    "nabeul": "tunisie_nord",
    "zaghouan": "tunisie_nord",
    "le kef": "tunisie_nord",
    "kef": "tunisie_nord",
}


def climat_depuis_region(r):
    return REGIONS.get(_norm(r), "tunisie_centre")
