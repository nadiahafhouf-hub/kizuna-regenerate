# Kizuna Regenerate

Réécriture en Django du prototype Streamlit « Gabès Regenerate » — hackathon eau · énergie · agriculture.

## Installation (Windows / PowerShell, Python 3.11)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # puis mettre GEMINI_API_KEY dans .env
python manage.py migrate
python manage.py runserver
```

Ouvrir http://127.0.0.1:8000/ — admin : `python manage.py createsuperuser` puis `/admin/`.

## Organisation : 1 app = 1 bloc = 1 personne = 1 branche

| App | Branche | Rôle |
|---|---|---|
| `core` | `main` | `Parcel`, `PollutionSource` (sources configurables), page d'accueil |
| `diagnostics` | `bloc-1` | mesures CE/pH/Cd/Pb → grille 10 m → IDW → couleur → 1 à 3 zones → traitement ; carte Leaflet + GeoJSON |
| `advisor` | `bloc-2` | pop-up terre nue / plantée, recommandations, photo Gemini Vision, score d'optimalité |
| `irrigation` | `bloc-3` | planning 7 jours (Open-Meteo ET0 × Kc, CE), validation, vanne simulée + pompe solaire |
| `passport` | `bloc-4` | PDF + QR, chaîne de hash (`data_hash`, `prev_hash`), `/verify/<id>/`, chatbot RAG |

## Interface (démo jury)

Parcours par parcelle : `/` (dashboard) → `/p/<id>/diagnostic/` → `/crops/` → `/irrigation/` → `/passport/`,
plus la page publique `/verify/<passport_id>/` (cible du QR). Bouton « Load demo parcel » = `/demo/`.

- **Stack sans build** : Tailwind (CDN), Alpine.js, HTMX, Leaflet (imagerie Esri), Chart.js, Lucide, DM Sans.
- **Données** : toutes les pages lisent `services/demo_data.py` (fixtures `fixtures/demo/*.json`).
  Pour brancher la vraie logique d'un bloc, remplacer la fonction correspondante en gardant les mêmes champs :
  bloc 1 → `land_profile`, `zones`, `sensors`, `case_detail` · bloc 2 → `crop_recommendations`, `score_planting`
  · bloc 3 → `irrigation_plan` · bloc 4 → `passport`, `chatbot_reply`.
- **Textes** : tous dans `core/strings.py` (`{{ T.section.cle }}` dans les templates, `UI.section.cle` en JS).
  Valeurs du contrat (ROUGE, phytoextraction…) → libellé affiché via le filtre `{{ valeur|label }}`.
- **Composants** réutilisables dans `templates/components/` : `zone_badge` (via `{% zone_badge "ROUGE" %}`),
  `zone_card`, `kpi_card`, `gauge`, `threshold_row`, `crop_card`, `parcel_card`, `modal`, `hash_chip`, `section_header`.
- **JS/CSS** : `static/js/` (app, map, diagnostic_map, irrigation_sim). Utiliser `{% vstatic 'js/x.js' %}`
  (ajoute `?v=<date>` pour éviter le cache navigateur).
- Démo irrigation : le bouton « Approve plan » est mémorisé en session ; `POST /p/<id>/irrigation/reset/` le remet à zéro.
- Démo passeport falsifié : `/verify/GAB-001-P4-T/` affiche « Tampered ✗ ».
- Le QR pointe vers l'adresse du serveur : pour le scanner avec un téléphone pendant la démo, lancer
  `python manage.py runserver 0.0.0.0:8000`, ajouter l'IP du PC dans `ALLOWED_HOSTS` (`.env`) et ouvrir la page par cette IP.

## Le contrat entre les blocs : LandProfile

Le bloc 1 produit un **LandProfile** ; les blocs 2-4 le consomment. Un exemple complet
(grille 3×3, 3 zones) est dans [`fixtures/land_profile.sample.json`](fixtures/land_profile.sample.json).
En attendant le bloc 1, utilisez :

```python
from diagnostics.contract import load_sample   # ou latest_for(parcel)
profile = load_sample()
```

Règles :
- **Une seule fonction couleur** : `diagnostics.couleur.couleur_case(ce, ph, cd, pb)`. Ne pas la recopier.
- Valeurs en **MAJUSCULES** : `ROUGE` / `ORANGE` / `VERT`, `NUE` / `PLANTEE`, etc.
- Ne pas changer les clés du contrat sans prévenir toute l'équipe.

## Bloc 2 — conseiller cultures (terre nue)

Calculs sans Django dans `advisor/services/` (testables seuls), branchés sur l'interface via
`advisor/logic.py` → `services.demo_data.crop_recommendations()` (mêmes champs qu'avant).

- **ROUGE / ORANGE** : plantes et microbes du `traitement` du bloc 1 (rien d'inventé) ; si `traitement`
  est vide → secours Atriplex + hyperaccumulatrice. ROUGE : pas de lessivage (LR = 0) + collecte du drainage.
- **VERT** : **une seule culture par zone** (une vanne = mêmes besoins en eau), évaluée avec la CE **max**
  de la zone et le climat, + 2 alternatives. `culture_alimentaire_autorisee = false` → jamais d'alimentaire.
- Base de plantes : `advisor/data/plantes.json` (ajouter une plante = copier un bloc, sans coder).
- Climat : Open-Meteo → NASA POWER (ET0 Hargreaves) → `advisor/data/regions.json` ; cache dans `cache/`.
- Eau d'irrigation : `ce_eau_dS_m` du LandProfile si mesurée, sinon valeur typique de la région
  (Gabès ≈ 3,5 dS/m, ordre de grandeur à confirmer).
- JSON complet (pour le bloc 4) : `GET /p/<id>/crops/recommandation.json` · plan PNG : `GET /p/<id>/crops/plan/`.
- Page Crops : **carte satellite** du plan (zones, plantes, goutte-à-goutte, vannes, réservoir, pompe ; `static/js/crops_map.js`)
  et onglet **plan détaillé** (PNG, aussi pour le passeport).
- Tests : `python manage.py test advisor` (hors ligne).

## Irrigation — planning 7 jours (tâche du bloc 2)

Calculs sans Django dans `irrigation/services/`, branchés via `irrigation/logic.py` →
`services.demo_data.irrigation_plan()` (mêmes champs pour `irrigation.html` et `irrigation_sim.js`).

- Météo 7 jours Open-Meteo (ET0, pluie, rayonnement horaire, températures ; cache 1 h) → sinon moyennes du climat.
- Besoin par zone et par jour = formule FAO du bloc 2 ; arrosage à 6 h en 1 à 3 doses selon la texture.
- Pluie ≥ 5 mm → arrosage annulé (raison affichée). Quota de nappe/semaine jamais dépassé :
  priorité VERT → ORANGE → ROUGE, chaque réduction est expliquée.
- Pompage nappe → réservoir seulement aux heures où `kWc × rayonnement/1000 × 0,8 ≥ puissance pompe` ;
  le réservoir ne déborde jamais ; on remplit d'avance avant les jours sans soleil.
- Paramètres modifiables dans l'admin : **Paramètres d'irrigation** (pompe, panneaux, réservoir, quota, seuils).
  Par défaut 2,0 kWc : avec 1,0 kWc × 0,8 la pompe de 0,75 kW ne démarre presque jamais en hiver.
- **Planning enregistré en base** (`IrrigationPlan` + `IrrigationEvent`, vannes `ValveState`, humidité simulée
  `SoilMoistureReading`, journal `ValveEvent`). Parcours sur la page : **Valider → Passer en automatique →
  Simuler la journée suivante / Reprendre la main** (seuls les boutons utiles sont affichés), **Modifier un volume**
  (recalcule tout), **Nouveau planning**. Avant chaque arrosage, l'automate vérifie la pluie et l'humidité simulée.
- JSON : `GET /p/<id>/irrigation/plan.json` · état en direct : `etat.json` · passeport (bloc 4) :
  `GET /p/<id>/irrigation/passeport.json` (événements FAIT / ANNULE déjà passés selon l'horloge simulée).
- Tests : `python manage.py test irrigation` (hors ligne).

## `services/` — code récupéré de l'ancien projet

| Fichier | Origine | Contenu |
|---|---|---|
| `seuils.py` | `config.py` | seuils CE / pH / Cd / Pb, vitesses d'extraction, facteurs d'infiltration |
| `traitement.py` | `agents/prediction_agent.py`, `rule_*` de `app.py`, `model_interface.py` | `traitement_zone()`, `culture_alimentaire_autorisee()`, `volume_lessivage_m3()` |
| `cultures.py` | `agents/models/crop_factor.pkl` + FAO 29 | Kc par culture, tolérance CE, `cultures_compatibles()` |
| `rag/knowledge_base.py` | `rag/build_knowledge_base.py` | base de connaissances + `search()` TF-IDF (index construit au 1er appel) |
| `passport_generator.py` | `utils/passport_generator.py` | QR + PDF ReportLab, `generate_qr_for_url()` |

Non repris : `app.py` Streamlit, LUCAS/NIR, `auth.py`, `llm_agent.py`.
Les modèles `.pkl` ne sont pas versionnés : `water_model.pkl` fait 107 Mo (limite GitHub : 100 Mo)
et attend des variables d'un autre jeu de données ; le bloc 3 calcule les besoins par ET0 × Kc.

## Workflow git

```powershell
git checkout bloc-1          # votre branche
git pull origin main         # récupérer les changements communs
git push origin bloc-1
```
Fusion dans `main` par pull request. Les clés API restent dans `.env`, jamais dans le code.
