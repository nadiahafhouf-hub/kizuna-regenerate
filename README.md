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
