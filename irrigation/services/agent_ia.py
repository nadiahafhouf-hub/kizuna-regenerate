"""Gemini reformule les consignes de l'agent pour l'agriculteur. Sans Django.

Les chiffres viennent TOUS de services/consignes.py : le modèle n'a le droit ni d'en inventer ni de
changer une décision. En cas d'erreur (pas de clé, quota, réseau), on garde le texte automatique.
"""
import json
import time

PROMPT = """Tu es le conseiller en irrigation d'une ferme à Gabès (Tunisie). Voici, en JSON, le plan calculé
pour la ferme : actions du jour, bilan de la semaine, eau économisée, pompage solaire et alertes.

Rédige les consignes pour l'agriculteur, en {langue}, avec des phrases courtes et simples :
1. « Aujourd'hui » : quoi faire, à quelle heure, combien d'eau par zone (et par plante si donné).
2. « Pompe solaire et stockage » : quand la pompe tourne et où va l'eau.
3. « Cette semaine » : eau totale, économie par rapport à l'irrigation actuelle, énergie solaire.
4. « Attention » : les alertes, s'il y en a.
Termine par : s'il est d'accord, il valide le plan et l'irrigation devient automatique.

Règles : utilise UNIQUEMENT les chiffres du JSON, n'en invente aucun, ne change aucune décision,
pas de jargon (évite ET0, Kc), 180 mots maximum, texte brut avec des titres et des tirets.

JSON :
{donnees}"""


class AgentIAErreur(Exception):
    pass


def rediger(consignes, cle, modele="gemini-3.8-flash", langue="français", appel=None):
    """Renvoie le texte rédigé par le modèle. `appel(cle, modele, prompt) -> texte` est remplaçable (tests)."""
    if not cle:
        raise AgentIAErreur("Clé GEMINI_API_KEY absente.")
    donnees = {k: consignes.get(k) for k in ("jour", "semaine", "alertes")}
    prompt = PROMPT.format(langue=langue, donnees=json.dumps(donnees, ensure_ascii=False, default=str))
    try:
        texte = (appel or _appeler)(cle, modele, prompt)
    except Exception as e:
        raise AgentIAErreur(f"{type(e).__name__}: {e}") from e
    texte = (texte or "").strip()
    if not texte:
        raise AgentIAErreur("réponse vide du modèle")
    return texte


def _appeler(cle, modele, prompt):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=cle)
    try:
        for essai in range(3):   # modèle surchargé (503) ou quota par minute (429) : on réessaie
            try:
                rep = client.models.generate_content(
                    model=modele, contents=prompt, config=types.GenerateContentConfig(temperature=0.3))
                return rep.text or ""
            except Exception as e:
                if essai == 2 or not any(c in str(e) for c in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    raise
                time.sleep(4 * (essai + 1))
    finally:
        try:
            client.close()
        except Exception:
            pass
