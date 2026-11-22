"""Chatbot Kizuna (bloc 4) : RAG sur Qdrant + Gemini, en derja tounsi.

repondre(question, pid, historique) -> {"reponse", "actions", "sources", "mode"}
  1. indexe (si besoin) la base de connaissances et les données de la parcelle dans Qdrant ;
  2. retrouve les passages utiles (connaissances + parcelle) ;
  3. Gemini répond en tounsi, UNIQUEMENT avec ces passages, et choisit les actions utiles dans une liste fermée
     (liens vers les pages de l'application) ;
  4. sans clé ou en cas d'erreur : réponse de secours construite à partir des passages retrouvés.
"""
import json
import re
import time

from .knowledge_base import KNOWLEDGE_DOCS, split_chunks
from . import vecteurs as V

# Glossaire tounsi <-> termes du système (aide la recherche et le modèle)
GLOSSAIRE_TOUNSI = """GLOSSAIRE TOUNSI (derja) — termes de la ferme :
sa9i / ns9i / tes9i = arroser / irrigation ; lma / el ma = l'eau ; goutte à goutte / goutte = goutte-à-goutte ;
pompe / el pompe = pompe ; panneau / louhet chams / el panneaux = panneaux solaires ; chams = soleil ;
bassin / majen / fes9ia = bassin, réservoir ; nappe / bir = puits, nappe ; mlou7a / mel7 = salinité, sel ;
trab / ard / blad = sol, terre ; ard fer8a = terre nue ; mzrou3a / mghrousa = déjà plantée ;
zitoun = olivier ; rommen = grenadier ; nakhla / nakhel = palmier ; 9ta = atriplex (guettaf) ;
khodhra = légumes ; dwa / ghobra = pollution / poussière du phosphogypse ; cadmium / plomb = métaux ;
wa9tech = quand ; 9addech = combien ; kifech = comment ; chnowa / chniya = quoi ; 3lech = pourquoi ;
lyoum = aujourd'hui ; ghodwa = demain ; jem3a = semaine ; zone = zone (Z1, Z2...) ; passeport = passeport du sol.
Chiffres du 3arbizi : 3 = ع, 7 = ح, 9 = ق, 5 = خ, 8 = غ, 2 = ء."""

GUIDE_APPLI = """GUIDE DE L'APPLICATION KIZUNA REGENERATE :
1. Diagnostic : mesures du sol par case de 10 m (CE, pH, cadmium, plomb), zones ROUGE / ORANGE / VERT et traitement.
2. Crops : terre nue -> cultures conseillées par zone ; déjà plantée -> score, analyse du champ, réseau goutte-à-goutte.
3. Irrigation : l'agent prépare le plan de 7 jours (météo, plantes, réservoir + bassin, pompe solaire). L'agriculteur
   valide puis passe en automatique : les vannes et la pompe suivent le plan ; il peut reprendre la main.
   Design the drip network : réseau goutte-à-goutte tracé sur l'image satellite.
4. Passport : passeport du sol scellé par empreintes (hash), QR code vérifiable par l'acheteur.
Solar : dimensionnement des panneaux, alertes de nettoyage."""

PROMPT = """Inti mosa3ed fella7i (assistant agricole) mta3 Kizuna Regenerate f Gabes, Tounes.

LANGUE : jaweb DIMA bel derja tounsiya (dialecte tunisien), mouch bel 3arbiya el fos7a.
- Ken el fella7 ykteb bel 7rouf el 3arbiya -> jaweb bel 7rouf el 3arbiya (derja).
- Ken ykteb bel 7rouf latiniya / 3arbizi (ex. « kifech ns9i ») -> jaweb bel 3arbizi tounsi.
- Tnajem testa3mel klem fransi mta3 el technique (goutte à goutte, pompe, zone, cadmium) kima y7ki el fella7 f Gabes.
STYLE : jomal 9sira w sahla, 120 kelma max, ar9am wadh7a (litres, m³, sa3a). Ma testa3melch ET0, Kc.

RÈGLES :
- Esta3mel BARKA el ma3loumet elli f « CONTEXTE ». Ma tikhtara3 7atta ra9m. Ken el ma3louma mech mawjouda, 9ollou.
- El 9rarat (9addech lma, wa9tech) yjiw mel plan mta3 el agent : ma tbadelhomch.
- Zone ROUGE : ma tansa7ch b khodhra wala 7aja tetkla.
- Ikhtar mel « ACTIONS POSSIBLES » el actions elli yfidou el fella7 (0 7atta 3), b el « id » mta3hom.

Rodd JSON barka : {{"reponse": "...", "actions": ["id1", "id2"]}}

{glossaire}

PARCELLE : {parcelle}

CONTEXTE :
{contexte}

ACTIONS POSSIBLES :
{actions}

HISTORIQUE (akher msegat) :
{historique}

SO2AL EL FELLA7 : {question}"""


def config():
    """Paramètres depuis settings (Django) ; utilisable aussi sans Django dans les tests."""
    try:
        from django.conf import settings
        return {
            "cle": getattr(settings, "GEMINI_API_KEY", ""),
            "modele": getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash"),
            "modele_embedding": getattr(settings, "GEMINI_EMBED_MODEL", "gemini-embedding-001"),
            "url": getattr(settings, "QDRANT_URL", "") or None,
            "qdrant_cle": getattr(settings, "QDRANT_API_KEY", ""),
            "chemin": getattr(settings, "QDRANT_PATH", None),
        }
    except Exception:
        return {"cle": "", "modele": "gemini-3.8-flash", "modele_embedding": "", "chemin": ":memory:"}


def docs_connaissances():
    docs = []
    # le glossaire tounsi n'est PAS indexé (il ressortait en tête de toutes les recherches) : il est donné
    # directement à Gemini dans le prompt
    for i, doc in enumerate(KNOWLEDGE_DOCS + [GUIDE_APPLI]):
        titre = doc.strip().split("\n", 1)[0].strip(" :—-")[:80]
        for j, morceau in enumerate(split_chunks(doc.strip(), chunk_size=80, overlap=15)):
            docs.append({"titre": titre, "texte": morceau, "source": "base de connaissances Gabès"})
    return docs


def indexer_tout(pid, cfg=None):
    """Indexe (ou garde) les connaissances et les données de la parcelle. Renvoie (faits, actions)."""
    from .contexte import contexte_parcelle
    cfg = cfg or config()
    V.indexer(docs_connaissances(), "connaissances", cfg, type_doc="connaissance")
    faits, actions = {}, []
    if pid:
        docs, faits, actions = contexte_parcelle(pid)
        V.indexer(docs, f"parcelle:{pid}", cfg, parcelle_id=pid, type_doc="parcelle")
    return faits, actions


def _lire_json(texte):
    m = re.search(r"\{.*\}", texte or "", re.S)
    if not m:
        raise ValueError("pas de JSON")
    return json.loads(m.group(0))


def _appeler_gemini(cle, modele, prompt):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=cle)
    try:
        for essai in range(3):   # surcharge (503) ou quota (429) : on réessaie
            try:
                rep = client.models.generate_content(
                    model=modele, contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.4, response_mime_type="application/json"))
                return rep.text or ""
            except Exception as e:
                if essai == 2 or not any(c in str(e) for c in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    raise
                time.sleep(3 * (essai + 1))
    finally:
        try:
            client.close()
        except Exception:
            pass


def _secours(question, passages, actions):
    """Sans Gemini : on montre les passages les plus proches (texte en français/derja simple)."""
    if not passages:
        return "Ma l9itech ma3louma 3la so2alek. Jarreb ektbou b tari9a o5ra, walla chouf les pages mta3 el parcelle."
    lignes = ["Hedha elli l9itou f el ma3loumet mta3ek :"]
    for p in passages[:3]:
        lignes.append(f"• {p['titre']} : {p['texte'][:260]}{'…' if len(p['texte']) > 260 else ''}")
    lignes.append("(Réponse automatique : zid clé Gemini bech njaweb bel derja b tafsil.)")
    return "\n".join(lignes)


def repondre(question, pid=None, historique=None, cfg=None, appel=None):
    cfg = cfg or config()
    question = (question or "").strip()[:500]
    faits, actions = indexer_tout(pid, cfg)
    passages = V.chercher(question, cfg, parcelle_id=pid)
    par_id = {a["id"]: a for a in actions}
    sources = [{"titre": p["titre"], "source": p.get("source"), "url": p.get("url"), "score": p["score"]}
               for p in passages[:5]]
    if not cfg.get("cle") and appel is None:
        return {"reponse": _secours(question, passages, actions), "actions": actions[:2], "sources": sources,
                "mode": "secours"}
    contexte = "\n".join(f"[{i + 1}] ({p.get('source')}) {p['titre']} : {p['texte']}" for i, p in enumerate(passages))
    hist = "\n".join(f"{m.get('role')}: {str(m.get('text', ''))[:300]}" for m in (historique or [])[-6:])
    prompt = PROMPT.format(glossaire=GLOSSAIRE_TOUNSI, parcelle=json.dumps(faits, ensure_ascii=False, default=str),
                           contexte=contexte or "(rien)", question=question, historique=hist or "(rien)",
                           actions="\n".join(f"- {a['id']} : {a['label']}" for a in actions) or "(aucune)")
    try:
        data = _lire_json((appel or _appeler_gemini)(cfg["cle"], cfg["modele"], prompt))
        texte = str(data.get("reponse") or "").strip()
        if not texte:
            raise ValueError("réponse vide")
        choisies = [par_id[i] for i in data.get("actions") or [] if i in par_id][:3]
        return {"reponse": texte, "actions": choisies, "sources": sources, "mode": "gemini"}
    except Exception as e:   # noqa: BLE001
        return {"reponse": _secours(question, passages, actions), "actions": actions[:2], "sources": sources,
                "mode": "secours", "erreur": f"{type(e).__name__}: {str(e)[:150]}"}
