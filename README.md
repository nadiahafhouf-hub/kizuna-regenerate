# Verdix

**Verdix** — réécriture en Django du prototype Streamlit « Gabès Regenerate » — hackathon eau · énergie · agriculture.
Une parcelle polluée de Gabès est diagnostiquée (sol), reçoit des cultures adaptées, un arrosage
goutte-à-goutte piloté par pompe solaire, puis un passeport de sol vérifiable par QR code.

Deux interfaces sur la même logique et les mêmes données :

| Vue | Adresse | Pour qui |
|---|---|---|
| **Farmer** | `/farm/` | l'agriculteur : site web simple, phrases courtes, gros chiffres, sans sigles |
| **Expert & Jury** | `/` | l'équipe et le jury : toutes les données, cartes, graphiques, modèles IA et sources |

Chaque page a un lien vers la page équivalente de l'autre vue (même parcelle).

## Installation (Windows / PowerShell, Python 3.11)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # puis remplir les clés (facultatives) dans .env
python manage.py migrate
python manage.py energy_train    # IA du volet solaire (sinon replis physiques)
python manage.py runserver
```

Ouvrir http://127.0.0.1:8000/ (vue Expert & Jury) ou http://127.0.0.1:8000/farm/ (vue Farmer).
Admin : `python manage.py createsuperuser` puis `/admin/`.

Tests (hors ligne) : `python manage.py test` → 108 tests.

### Variables d'environnement (`.env`, jamais commité)

| Variable | Rôle | Sans elle |
|---|---|---|
| `DJANGO_SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | Django | valeurs de développement |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | photo des plantes (bloc 2/3), chatbot (bloc 4) | chatbot en mode secours, pas de comptage des plantes |
| `GEMINI_EMBED_MODEL` | embeddings du chatbot | embeddings locaux (n-grammes) |
| `QDRANT_URL`, `QDRANT_API_KEY` | serveur Qdrant | Qdrant embarqué (`qdrant_data/`) |
| `GOOGLE_MAPS_API_KEY`, `GOOGLE_MAPS_BROWSER_KEY` | image satellite haute résolution (bloc 3) | Esri World Imagery (sans clé) |
| `SATELLITE_FOURNISSEUR`, `SATELLITE_ZOOM`, `MAPBOX_TOKEN` | forcer le fournisseur de tuiles | `esri`, zoom auto |
| `DETECTION_IA` | détection des plantes par Gemini Vision | `True` |

**Aucun compte n'est nécessaire** pour la démo : Sentinel-2 (Earth Search), PVGIS, Open-Meteo, NREL PVDAQ
et Esri sont en accès libre.

## Organisation : 1 app = 1 bloc

| App | Branche | Rôle |
|---|---|---|
| `core` | `main` | `Parcel`, `PollutionSource`, tableau de bord, textes de l'interface, chatbot (`/chat/`) |
| `diagnostics` | `bloc-1` | plan des capteurs, mesures CE/pH/Cd/Pb → IDW → couleur → zones → traitement ; modèle Cd ; Sentinel-2 |
| `advisor` | `bloc-2` | terre nue / plantée, recommandations par zone, score d'une plantation, plan PNG |
| `irrigation` | `bloc-3` | planning 7 jours, validation / automatique / manuel, réseau goutte-à-goutte sur image satellite |
| `energy` | `energy` | volet solaire : dimensionnement (panneaux, pompe, réservoir) + 3 IA de nettoyage + alertes |
| `passport` | `bloc-4` | passeport PDF + QR, chaîne de hash, page publique `/verify/<id>/` |
| `farmer` | `ui-v2` | vue Farmer : vues minces qui appellent les fonctions des autres apps, aucune logique propre |

## Interface

### Parcours (vue Expert & Jury)

`/` (dashboard) → `/p/<id>/diagnostic/` → `/p/<id>/crops/` → `/p/<id>/irrigation/` → `/p/<id>/solar/`
→ `/p/<id>/passport/`, plus la page publique `/verify/<passport_id>/` (cible du QR).
Nouvelle parcelle : `/parcels/new/` (position GPS + hectares) → plan des capteurs → relevés → diagnostic.
Bouton « Load demo parcel » = `/demo/`.

- **Barre latérale** (≥ 1024 px, tiroir sur mobile) : sélecteur de parcelle, Dashboard, New parcel, les 5 étapes
  avec leur état, Farm Assistant (chatbot), lien « Farmer view ». Le stepper reste en haut du contenu.
- **Sources visibles** : bandeau « Open data behind these numbers » (`components/data_sources.html`,
  ex. `{% include "components/data_sources.html" with keys="nrel,pvgis,meteo" %}`).

### Vue Farmer (`/farm/`)

| Page | Adresse | Contenu | Page experte équivalente |
|---|---|---|---|
| My farm | `/farm/` | une carte par champ : état en une phrase + prochaine action | `/` |
| Water | `/farm/<id>/water/` | arrosage du jour (heure, litres, durée), réservoir, demain, pluie, semaine | `/p/<id>/irrigation/` |
| Soil | `/farm/<id>/soil/` | carte satellite des zones + une phrase par zone | `/p/<id>/diagnostic/` |
| Plants | `/farm/<id>/plants/` | % planté (satellite), santé, plantes comptées (vision), quoi planter | `/p/<id>/crops/` |
| Sun | `/farm/<id>/sun/` | nombre de panneaux, quand les nettoyer, « I cleaned them » | `/p/<id>/solar/` |
| Certificate | `/farm/<id>/certificate/` | statut du passeport, QR, PDF | `/p/<id>/passport/` |

- **Mêmes actions** que la vue experte : « Use this plan » = `irrigation:action valider`,
  « Water automatically » / « Restart automatic » = `automatique`, « Stop – I water myself » = `manuel`
  (avec confirmation), « Simulate next day » = `irrigation:simuler`, « I cleaned them » = `energy:clean`.
  Un champ `next` (seulement `/farm/…`, même site) ramène à la page Farmer après l'action.
- Sans diagnostic, les pages renvoient vers Soil (« Get the diagnostic »). Sans clé Gemini, Plants affiche
  seulement le satellite.
- Desktop d'abord (1280 px), responsive jusqu'à 375 px, mode sombre automatique.

### Design system (`design-system/kizuna/`)

Généré avec la skill **ui-ux-pro-max**, puis ajusté par l'équipe (décisions en tête de `MASTER.md`) :
- **Farmer** = « Accessible & Ethical » + « Bento Box Grid » (`pages/farmer.md`) ;
  **Expert** = « Data-Dense Dashboard » (`pages/expert.md`).
- On garde l'identité Verdix : sand, olive, water, sun, zones ROUGE/ORANGE/VERT (toujours icône + libellé),
  DM Sans + DM Mono. Tokens dans la config Tailwind de `templates/base.html` uniquement (jamais de hex dans les pages).
- Règles communes : focus clavier visible, contraste AA, chiffres `tabular-nums`, squelettes de chargement,
  `prefers-reduced-motion` respecté, aucun débordement à 375 px. Réglages Chart.js communs dans `static/js/app.js`.

### Conventions front

- **Stack sans build** : Tailwind (CDN), Alpine.js, HTMX, Leaflet (imagerie Esri), Chart.js, Lucide, DM Sans / DM Mono.
- **Textes** : tous dans `core/strings.py` (`{{ T.section.cle }}` dans les templates, `UI.section.cle` en JS ;
  vue Farmer : section `farmer`, exposée en `F`). Filtre `{{ texte|fill:valeur }}` pour remplir un champ `{…}`.
  Valeurs du contrat (ROUGE, phytoextraction…) → libellé via `{{ valeur|label }}`.
- **Composants** dans `templates/components/` : `zone_badge` (`{% zone_badge "ROUGE" %}`), `zone_card`, `kpi_card`,
  `gauge`, `threshold_row`, `crop_card`, `parcel_card`, `modal`, `hash_chip`, `section_header`, `data_sources`.
- **JS/CSS** : `static/js/`, `static/css/app.css`. Utiliser `{% vstatic 'js/x.js' %}` (ajoute `?v=<date>`).
- **Données** : `services/demo_data.py` lit les parcelles de démo (`fixtures/demo/*.json`) et les parcelles en base
  (`core.Parcel` + LandProfile du bloc 1).

### Astuces de démo

- Passeport falsifié : `/verify/GAB-001-P4-T/` affiche « Tampered ».
- Remettre l'irrigation à zéro : bouton « New plan », ou `POST /p/<id>/irrigation/reset/`.
- QR scanné par un téléphone : `python manage.py runserver 0.0.0.0:8000`, ajouter l'IP du PC dans `ALLOWED_HOSTS`
  (`.env`) et ouvrir la page par cette IP.

## Le contrat entre les blocs : LandProfile

Le bloc 1 produit un **LandProfile** ; les blocs 2-4 et le solaire le consomment. Exemple complet
(grille 3×3, 3 zones) : [`fixtures/land_profile.sample.json`](fixtures/land_profile.sample.json).

```python
from diagnostics.contract import load_sample   # ou latest_for(parcel)
profile = load_sample()
```

Règles :
- **Une seule fonction couleur** : `diagnostics.couleur.couleur_case(ce, ph, cd, pb)`. Ne pas la recopier.
- Valeurs en **MAJUSCULES** : `ROUGE` / `ORANGE` / `VERT`, `NUE` / `PLANTEE`, etc.
- Ne pas changer les clés du contrat sans prévenir toute l'équipe.
- Champs facultatifs ajoutés par le bloc 1 : `confiance`, `interpolation`, `satellite`, `fusion_ce`,
  `points_controle`, `cases[].satellite`, `zones[].observations`, `tri_labo`, `releves_simules`.

## Bloc 1 — diagnostic du sol

- **Plan des capteurs** : jusqu'à 1 ha, max(5, surface / 400 m²) points ; au-delà, 25 + 1 point par 0,25 ha.
  Terre de 20 ha au plus. Position GPS + hectares → image et plan des capteurs → relevés (ou « Simulate ») → diagnostic.
- **IDW** : puissance choisie par validation croisée (LOOCV), confiance selon la distance au relevé le plus proche.
- Notebook : [`notebooks/bloc1_modele.ipynb`](notebooks/bloc1_modele.ipynb) (déjà exécuté). Pour le relancer :
  `pip install notebook` ; données via `LUCAS_HM_XLSX` (par défaut `~/Downloads/HeavyMetals.xlsx`).
- `python manage.py bloc1_train_cd <HeavyMetals.xlsx>` : modèle « risque Cd ≥ 1 mg/kg à partir d'un relevé XRF »
  (LUCAS Heavy Metals 2009, ESDAC). AUC 0,84 (découpage aléatoire), 0,74 sur les sols méditerranéens.
  Le `.joblib` n'est pas versionné : à lancer sur chaque poste.
- `python manage.py bloc1_experiment` : erreur IDW selon le nombre de points (`fixtures/bloc1/experience_capteurs.json`).
- `python manage.py bloc1_extract_lucas <LUCAS_TOPSOIL_v1.xlsx>` : extrait des sols méditerranéens calcaires.

### Couche satellite (Sentinel-2)

- Images **Copernicus Sentinel-2 L2A** via le catalogue public Earth Search (AWS), **sans compte**.
  Par case de 10 m : NDVI (vigueur), NDMI (stress hydrique), indice de sel de surface (sol nu seulement).
- **Le satellite ne mesure jamais Cd ni Pb.** Il sert à : (1) une fusion « régression + IDW des résidus » pour la
  **CE**, adoptée seulement si la validation croisée gagne ≥ 10 % et |r| ≥ 0,5 ; (2) des **observations par zone** ;
  (3) des **points de contrôle** (cases non mesurées anormales → confiance réduite).
- `python manage.py bloc1_satellite [ids…]` : résultat mis en cache dans `fixtures/bloc1/satellite/` pour les
  parcelles de démo (démo hors ligne). Les nouvelles parcelles sont analysées à l'ouverture du diagnostic (~20-40 s).
- Attribution affichée : « Contains modified Copernicus Sentinel data ».

## Bloc 2 — conseiller cultures

Calculs sans Django dans `advisor/services/`, branchés via `advisor/logic.py`.

- **ROUGE / ORANGE** : plantes et microbes du `traitement` du bloc 1 ; secours Atriplex + hyperaccumulatrice.
  ROUGE : pas de lessivage (LR = 0) + collecte du drainage.
- **VERT** : **une seule culture par zone** (une vanne = mêmes besoins en eau), évaluée avec la CE **max** de la zone
  et le climat, + 2 alternatives. `culture_alimentaire_autorisee = false` → jamais d'alimentaire.
- Terre nue ou plantée : choix de l'agriculteur, sinon détecté par Sentinel-2 (`advisor/services/etat_terre.py`).
- Base de plantes : `advisor/data/plantes.json` (ajouter une plante = copier un bloc, sans coder).
- Climat : Open-Meteo → NASA POWER → `advisor/data/regions.json` ; cache dans `cache/`.
- JSON : `GET /p/<id>/crops/recommandation.json` · plan PNG : `GET /p/<id>/crops/plan/`.
- Tests : `python manage.py test advisor`.

## Bloc 3 — irrigation

### Planning 7 jours

Calculs sans Django dans `irrigation/services/`, branchés via `irrigation/logic.py`.

- Météo 7 jours Open-Meteo (ET0, pluie, rayonnement horaire ; cache 1 h) → sinon moyennes du climat.
- Besoin par zone et par jour = formule FAO du bloc 2 ; arrosage à 6 h en 1 à 3 doses selon la texture.
- Pluie ≥ 5 mm → arrosage annulé (raison affichée). Quota de nappe par semaine jamais dépassé :
  priorité VERT → ORANGE → ROUGE, chaque réduction est expliquée.
- Pompage nappe → réservoir seulement quand le soleil suffit à la pompe ; le réservoir ne déborde jamais.
- Paramètres dans l'admin : **Paramètres d'irrigation** (pompe, panneaux, réservoir, quota, seuils).
- **Planning en base** (`IrrigationPlan`, `IrrigationEvent`, `ValveState`, `SoilMoistureReading`, `ValveEvent`).
  Parcours : **Valider → Passer en automatique → Simuler la journée suivante / Reprendre la main (manuel)**,
  **Modifier un volume**, **Nouveau planning**. L'automate vérifie la pluie et l'humidité avant chaque arrosage.
- **Agent d'irrigation** : consignes du jour et de la semaine, rédigées par Gemini si la clé est présente.
- JSON : `plan.json`, `etat.json`, `agent.json`, `passeport.json` (sous `/p/<id>/irrigation/`).

### Réseau goutte-à-goutte optimal (image satellite)

Page `/p/<id>/irrigation/network/` : le moteur `services/irrigation_engine/` (Python pur) lit le LandProfile,
télécharge l'**image satellite** de l'emprise, détecte les plantes en place (Gemini Vision si activé), croise avec
le sol de chaque zone et **trace le réseau** (conduite principale, porte-rampes, rampes, goutteurs).

- Option « J'envoie ma photo » : photo vue du dessus + clic des 4 coins.
- Arbres épars (oliveraie traditionnelle) : réseau arbre par arbre, sans inventer d'arbres « à replanter ».
- Satellite : `esri` (sans clé, par défaut), `google` ou `mapbox`. Cache : `media/tiles_cache/`.
- Résultat : `irrigation.DripNetworkPlan` (image tracée, GeoJSON, bilan m³/an, conseils par zone).
  JSON : `GET /p/<id>/irrigation/network/api/` et `.../network/geojson/`.
- Tests : `python manage.py test irrigation` (faux serveur de tuiles, hors ligne).

## Volet solaire (app `energy`) — page « Solar »

- **Dimensionnement** : nombre de plantes (bloc 2, modifiable) → eau mois par mois (FAO-56, ET0 Open-Meteo ERA5)
  → énergie de pompage `E = 0,002725 · V · H / η` avec `H = (profondeur + 10) × 1,1`, `η = 0,45`
  → nombre de panneaux (450 W), pompe, réservoir. Mois dimensionnant : juillet, marge salissure 5 %.
  Production du lieu : **PVGIS v5.3** (Commission européenne).
- **IA 1** production attendue de panneaux propres, entraînée sur de **vraies données NREL PVDAQ**
  (2010-2012, test 2013) : erreur journalière 1,1 % (formule physique PVWatts 1,6 %).
- **IA 2** cause d'une baisse (propre / poussière / panne) : 97,2 % d'exactitude, 2,5 % de fausses alertes.
- **IA 3** date de nettoyage avec poussière et pluie prévues (Open-Meteo) : erreur médiane 3 jours.
  Conseils : nettoyer, nettoyer après la tempête, attendre la pluie, prévoir, rien.
- **Alertes** : page Solar, tableau de bord, vue Farmer ; bouton « I cleaned the panels today ».
- **ESP32** : `POST /api/energy/<id>/readings/` `{"mesures": [{"t": "...", "w": 410, "poa": 850, "t_air": 22}]}`.
  Sans capteur, la production est simulée sur la vraie météo des 45 derniers jours (signalé à l'écran).
- Commandes : `energy_fetch_pvdaq` (télécharger NREL), **`energy_train`** (à lancer sur chaque poste :
  les `.joblib` ne sont pas versionnés ; sans eux, replis physiques/règles).
  Notebook : [`notebooks/solaire_ia.ipynb`](notebooks/solaire_ia.ipynb).

## Bloc 4 — passeport et chatbot

- **Passeport** : chaîne de hash locale (`hash_n = sha256(hash_{n-1} + JSON canonique de l'événement)`),
  PDF ReportLab + QR (`services/passport_generator.py`), page publique `/verify/<id>/` lisible par un acheteur.
- **Farm Assistant** (chatbot, sur toutes les pages des deux vues) : `POST /chat/` `{"q", "pid", "historique"}`.
  RAG sur **Qdrant** (embarqué par défaut) + **Gemini**, réponses en **derja tounsi**, avec les données de la parcelle
  de la page et des liens d'action vers l'application (`services/rag/`). Sans clé : réponse de secours construite
  à partir des passages retrouvés.

## `services/` — code récupéré de l'ancien projet

| Fichier | Origine | Contenu |
|---|---|---|
| `seuils.py` | `config.py` | seuils CE / pH / Cd / Pb, vitesses d'extraction, facteurs d'infiltration |
| `traitement.py` | `agents/prediction_agent.py`, `rule_*` de `app.py`, `model_interface.py` | `traitement_zone()`, `culture_alimentaire_autorisee()`, `volume_lessivage_m3()` |
| `cultures.py` | `agents/models/crop_factor.pkl` + FAO 29 | Kc par culture, tolérance CE, `cultures_compatibles()` |
| `rag/` | `rag/build_knowledge_base.py` | base de connaissances, vecteurs Qdrant, assistant Gemini |
| `passport_generator.py` | `utils/passport_generator.py` | QR + PDF ReportLab, `generate_qr_for_url()` |

Non repris : `app.py` Streamlit, LUCAS/NIR, `auth.py`, `llm_agent.py`.
Les modèles `.pkl` ne sont pas versionnés : `water_model.pkl` fait 107 Mo (limite GitHub : 100 Mo).

## Workflow git

```powershell
git checkout bloc-1          # votre branche
git pull origin main         # récupérer les changements communs
git push origin bloc-1
```

Fusion dans `main` par pull request. Les clés API restent dans `.env`, jamais dans le code.
Ne sont pas versionnés : `.env`, `db.sqlite3`, `*.joblib`, `*.pkl`, `qdrant_data/`, `media/`, `cache/`.
