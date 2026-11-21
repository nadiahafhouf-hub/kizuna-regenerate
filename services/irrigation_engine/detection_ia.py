"""Détection des plantes par un modèle de vision (Gemini) sur l'image vue du dessus.

Le modèle repère chaque arbre / arbuste / plant DANS le contour de la parcelle et décrit ce qu'il voit
(culture probable, disposition, irrigation visible). La DISPOSITION DU RÉSEAU (rampes, goutteurs,
secteurs, diamètres, durées) reste calculée par le moteur à partir de ces plantes : un modèle de vision
ne sait pas dimensionner un réseau hydraulique.

    from services.irrigation_engine.detection_ia import detecter_plantes
    det = detecter_plantes("satellite.png", coins_px, cle="...", modele="gemini-2.5-flash")
    det["plantes_px"], det["plantes_diam_px"], det["info"]

Sans clé ou en cas d'erreur : DetectionIAErreur (le moteur revient alors à la détection classique).
Ce module ne dépend pas de Django.
"""

import json
import re

import numpy as np
import cv2
from PIL import Image, ImageDraw

TAILLE_MAX = 1536  # côté max de l'image envoyée au modèle (coût et latence)
MAX_PLANTES = 800

PROMPT = """You are an agronomist looking at a top-down (satellite, aerial or drone) image of a farm parcel.
The parcel is outlined in RED. Detect every individual tree, shrub or crop plant whose centre is
INSIDE the red outline. Ignore shadows, buildings, walls, rocks, roads, vehicles and patches of grass or weeds.
For trees, the box must cover the crown only (not its shadow).

Return ONLY a JSON object:
{
  "plantes": [{"box_2d": [ymin, xmin, ymax, xmax], "label": "olive tree"}],
  "culture_probable": "olive | palm | pomegranate | citrus | vegetables | cereals | other | none",
  "disposition": "regular_rows | scattered_trees | low_crop_rows | no_plants",
  "irrigation_visible": "none | drip | flood | sprinkler | unknown",
  "remarques": "one short sentence, in French, about what you see"
}
box_2d coordinates are normalised to 0-1000 relative to the image. Return at most %d plants.""" % MAX_PLANTES


class DetectionIAErreur(Exception):
    pass


def _image_annotee(chemin, coins_px):
    """Image réduite (côté <= TAILLE_MAX) avec le contour de la parcelle en rouge."""
    im = Image.open(chemin).convert("RGB")
    k = min(1.0, TAILLE_MAX / max(im.size))
    if k < 1:
        im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    elif max(im.size) < 768:  # image satellite tres petite (zoom 18) : agrandie pour le modele
        k = 768 / max(im.size)
        im = im.resize((int(im.width * k), int(im.height * k)), Image.BICUBIC)
    d = ImageDraw.Draw(im)
    pts = [(x * k, y * k) for x, y in coins_px]
    d.line(pts + [pts[0]], fill=(255, 0, 0), width=max(2, int(min(im.size) / 300)))
    return im


def _client(cle):
    try:
        from google import genai
    except ImportError as e:  # pragma: no cover
        raise DetectionIAErreur("Bibliothèque google-genai absente (pip install google-genai).") from e
    return genai.Client(api_key=cle)


def _appeler(cle, modele, image):
    from google.genai import types

    cfg = {"response_mime_type": "application/json", "temperature": 0.1}
    if "2.5" in modele:  # Gemini 2.5 : pas de « réflexion » pour la détection (recommandation Google)
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    rep = _client(cle).models.generate_content(
        model=modele, contents=[image, PROMPT], config=types.GenerateContentConfig(**cfg))
    return rep.text or ""


def _lire_json(texte):
    t = texte.strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise DetectionIAErreur("Réponse du modèle illisible (pas de JSON).")
    return json.loads(m.group(0))


def detecter_plantes(chemin_image, coins_px, cle, modele="gemini-2.5-flash", appel=None):
    """Renvoie {"plantes_px": [[x, y]...], "plantes_diam_px": [d...], "info": {...}} en pixels de l'image
    d'origine. `appel(cle, modele, image_pil) -> texte` est remplaçable (tests)."""
    if not cle:
        raise DetectionIAErreur("Clé GEMINI_API_KEY absente.")
    w0, h0 = Image.open(chemin_image).size
    image = _image_annotee(chemin_image, coins_px)
    try:
        texte = (appel or _appeler)(cle, modele, image)
        data = _lire_json(texte)
    except DetectionIAErreur:
        raise
    except Exception as e:
        raise DetectionIAErreur(f"Appel au modèle {modele} impossible : {type(e).__name__}: {e}") from e
    poly = np.float32(coins_px).reshape(-1, 1, 2)
    plantes, diam = [], []
    for p in (data.get("plantes") or [])[:MAX_PLANTES]:
        b = p.get("box_2d") if isinstance(p, dict) else None
        if not b or len(b) != 4:
            continue
        ymin, xmin, ymax, xmax = (float(v) for v in b)
        x, y = (xmin + xmax) / 2000 * w0, (ymin + ymax) / 2000 * h0
        if cv2.pointPolygonTest(poly, (x, y), False) < 0:  # hors parcelle
            continue
        plantes.append([round(x, 2), round(y, 2)])
        diam.append(round(((xmax - xmin) / 1000 * w0 + (ymax - ymin) / 1000 * h0) / 2, 2))
    info = {k: data.get(k) for k in ("culture_probable", "disposition", "irrigation_visible", "remarques")}
    info.update(modele=modele, n_plantes=len(plantes))
    return {"plantes_px": plantes, "plantes_diam_px": diam, "info": info}
