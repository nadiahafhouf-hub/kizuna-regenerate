"""Chatbot Verdix (bloc 4) : RAG sur Qdrant + Gemini, en derja tounsi.

repondre(question, pid, historique) -> {"reponse", "actions", "sources", "mode"}
  1. indexe (si besoin) la base de connaissances et les données de la parcelle dans Qdrant ;
  2. retrouve les passages utiles (connaissances + parcelle) ;
  3. Gemini répond en tounsi, UNIQUEMENT avec ces passages, et choisit les actions utiles dans une liste fermée
     (liens vers les pages de l'application) ;
  4. sans clé ou en cas d'erreur : réponse de secours construite à partir des passages retrouvés.
"""
import json
import re

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

GUIDE_APPLI = """GUIDE DE L'APPLICATION VERDIX :
1. Diagnostic : mesures du sol par case de 10 m (CE, pH, cadmium, plomb), zones ROUGE / ORANGE / VERT et traitement.
2. Crops : terre nue -> cultures conseillées par zone ; déjà plantée -> score, analyse du champ, réseau goutte-à-goutte.
3. Irrigation : l'agent prépare le plan de 7 jours (météo, plantes, réservoir + bassin, pompe solaire). L'agriculteur
   valide puis passe en automatique : les vannes et la pompe suivent le plan ; il peut reprendre la main.
   Design the drip network : réseau goutte-à-goutte tracé sur l'image satellite.
4. Passport : passeport du sol scellé par empreintes (hash), QR code vérifiable par l'acheteur.
Solar : dimensionnement des panneaux, alertes de nettoyage."""

PROMPT = """Inti mosa3ed fella7i (assistant agricole) mta3 Verdix f Gabes, Tounes.

LANGUE : jaweb DIMA bel derja tounsiya (dialecte tunisien), mouch bel 3arbiya el fos7a.
{consigne_ecriture}
- Tnajem testa3mel klem fransi mta3 el technique (goutte à goutte, pompe, zone, cadmium) kima y7ki el fella7 f Gabes.
STYLE : jomal 9sira w sahla, 120 kelma max, ar9am wadh7a (litres, m³, sa3a). Ma testa3melch ET0, Kc.
{consigne_voix}

RÈGLES :
- Esta3mel BARKA el ma3loumet elli f « CONTEXTE ». Ma tikhtara3 7atta ra9m. Ken el ma3louma mech mawjouda, 9ollou.
- El 9rarat (9addech lma, wa9tech) yjiw mel plan mta3 el agent : ma tbadelhomch.
- Zone ROUGE : ma tansa7ch b khodhra wala 7aja tetkla.
- Ikhtar mel « ACTIONS POSSIBLES » el actions elli yfidou el fella7 (0 7atta 3), b el « id » mta3hom.

Rodd JSON barka : {format_json}

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
            # modèles de secours (offre gratuite saturée) et modèle rapide pour la voix
            "modeles_secours": getattr(settings, "GEMINI_MODELES_SECOURS", ["gemini-3.5-flash", "gemini-3.1-flash-lite"]),
            "modele_voix": getattr(settings, "GEMINI_MODEL_VOIX", "gemini-3.5-flash"),
            "ecriture": getattr(settings, "CHAT_ECRITURE", "arabizi"),
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


SURCHARGE = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND")


BUDGET_GEMINI_S = 10      # le navigateur abandonne à 18 s : il reste le temps de la recherche + réponse locale
PAUSE_QUOTA_S = 300       # modèle à quota épuisé (429) : on ne le réessaie pas pendant 5 min
RELAIS_S = 3              # modèle sans réponse en 3 s : le suivant part en parallèle (3 modèles tiennent en 10 s)
_en_pause = {}            # modèle -> instant (time.monotonic) jusqu'auquel on le saute


def _appeler_gemini(cle, modele, prompt, budget_s=BUDGET_GEMINI_S):
    """`modele` : un nom ou une liste. Modèle surchargé / quota / retiré / trop lent -> on passe AUSSITÔT
    au suivant (l'offre gratuite est souvent saturée sur le plus récent). Toute la chaîne tient en `budget_s`
    secondes : au-delà, l'appelant répond avec les passages locaux au lieu de laisser le navigateur expirer."""
    import time

    from google import genai
    from google.genai import types
    modeles = [m for m in ([modele] if isinstance(modele, str) else list(modele)) if m]
    maintenant = time.monotonic()
    disponibles = [m for m in modeles if _en_pause.get(m, 0) <= maintenant] or modeles[-1:]
    fin = maintenant + budget_s
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as Delai

    # L'API refuse un délai < 10 s (400 INVALID_ARGUMENT) : délai HTTP fixe, le budget est tenu ici par l'attente
    client = genai.Client(api_key=cle, http_options=types.HttpOptions(
        timeout=15000, retry_options=types.HttpRetryOptions(attempts=1)))
    from concurrent.futures import FIRST_COMPLETED, wait

    pool = ThreadPoolExecutor(max_workers=len(disponibles) + 1)
    config = types.GenerateContentConfig(temperature=0.4, response_mime_type="application/json")
    try:
        derniere = TimeoutError("budget Gemini épuisé")
        file = list(disponibles)
        en_cours = {}   # appel -> modèle
        relance = True  # UNE copie de plus de la dernière demande, si elle reste bloquée ou est refusée (503)
        while file or en_cours:
            reste = fin - time.monotonic()
            if reste < 0.5:
                break
            if file and (not en_cours or reste >= 1.5):
                m = file.pop(0)
                en_cours[pool.submit(client.models.generate_content, model=m, contents=prompt, config=config)] = m
            # Le modèle lent n'est pas abandonné : s'il n'a pas répondu après RELAIS_S, le suivant part EN PARALLÈLE
            # et le premier qui répond gagne (le plus récent est souvent saturé sur l'offre gratuite).
            attente = min(reste, RELAIS_S) if (file or relance) else reste
            finis, _ = wait(en_cours, timeout=attente, return_when=FIRST_COMPLETED)
            if not finis and not file and relance and en_cours and reste >= 1.5:
                # dernier modèle sans réponse : une demande parfois reste bloquée chez Google, une copie
                # envoyée maintenant revient souvent en 2-3 s
                relance = False
                m = next(iter(en_cours.values()))
                en_cours[pool.submit(client.models.generate_content, model=m, contents=prompt, config=config)] = m
            for appel in finis:
                m = en_cours.pop(appel)
                try:
                    return appel.result().text or ""
                except Exception as e:
                    # modèle saturé, quota, retiré ou trop lent : on passe AUSSITÔT au suivant
                    if not any(c in str(e) for c in SURCHARGE + ("timeout", "Timeout", "timed out", "DEADLINE")):
                        raise
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        _en_pause[m] = time.monotonic() + PAUSE_QUOTA_S
                    elif relance and not file and not en_cours:
                        relance = False   # refus passager (503) du dernier modèle : un nouvel essai
                        file.append(m)
                    derniere = e
        if en_cours:
            derniere = Delai(f"{', '.join(en_cours.values())} : plus de {budget_s} s")
        raise derniere
    finally:
        pool.shutdown(wait=False)   # un appel trop lent finit en arrière-plan, sans bloquer la réponse
        try:
            client.close()
        except Exception:
            pass


def vers_lettres_arabes(texte, cfg=None, appel=None):
    """3arbizi (lettres latines) -> derja en lettres arabes, pour que la voix tunisienne la lise.
    Texte déjà en arabe, ou Gemini indisponible : texte inchangé."""
    arabe = sum(1 for c in texte if "؀" <= c <= "ۿ")
    latin = sum(1 for c in texte if c.isascii() and c.isalpha())
    if arabe >= latin:
        return texte
    cfg = cfg or config()
    if not cfg.get("cle") and appel is None:
        return texte
    prompt = ("Réécris ce texte en derja tounsiya avec des LETTRES ARABES, mot pour mot, sans rien ajouter. "
              "Écris les nombres en toutes lettres (ستة، مية و خمسين). Garde les mots techniques français "
              "transcrits en lettres arabes (الزونة، البومبة). Réponds en JSON : {\"texte\": \"...\"}\n\nTEXTE : "
              + texte[:1500])
    try:
        modeles = list(dict.fromkeys([cfg.get("modele_voix"), *(cfg.get("modeles_secours") or []), cfg.get("modele")]))
        data = _lire_json((appel or _appeler_gemini)(cfg["cle"], modeles if appel is None else "m", prompt))
        return str(data.get("texte") or "").strip() or texte
    except Exception:   # noqa: BLE001
        return texte


def _secours(passages, gemini_indisponible=False):
    """Sans Gemini : on montre les passages les plus proches (texte en français/derja simple)."""
    if not passages:
        return "Ma l9itech ma3louma 3la so2alek. Jarreb ektbou b tari9a o5ra, walla chouf les pages mta3 el parcelle."
    lignes = ["Hedha elli l9itou f el ma3loumet mta3ek :"]
    for p in passages[:3]:
        lignes.append(f"• {p['titre']} : {p['texte'][:260]}{'…' if len(p['texte']) > 260 else ''}")
    if gemini_indisponible:
        lignes.append("(Gemini indisponible. Affichage des données locales.)")
    return "\n".join(lignes)


CONSIGNE_VOIX = """MODE VOCAL : el fella7 y7ki bel sot w el jaweb bech yetsma3 b sot tounsi.
- Jomal 9sira kima l7ke, 70 kelma max, bla tirets, bla listes, bla emojis.
- « a_dire » = NAFS el jaweb, ama bel 7rouf el 3arbiya (derja tounsiya) bech el sot y9rah, w el ar9am
  bel 7rouf (الستة الصباح، مية و خمسين لتر)."""

# Écriture du texte affiché : 3arbizi tounsi (lettres latines + 3, 7, 9...) ou même écriture que l'agriculteur
ECRITURES = {
    "arabizi": "- Ekteb « reponse » DIMA bel 3arbizi tounsi (7rouf latiniya w ar9am 3, 7, 9, 5, 8, 2), kima "
               "« Lyoum ns9i el zone Z3 m3a 6 sbe7 », 7atta ken el fella7 kteb bel 3arbi.",
    "meme": "- Ken el fella7 ykteb bel 7rouf el 3arbiya -> jaweb bel 7rouf el 3arbiya (derja).\n"
            "- Ken ykteb bel 7rouf latiniya / 3arbizi (ex. « kifech ns9i ») -> jaweb bel 3arbizi tounsi.",
}
FORMAT_JSON = '{"reponse": "...", "actions": ["id1", "id2"]}'
FORMAT_JSON_VOIX = '{"reponse": "... (3arbizi)", "a_dire": "... (حروف عربية)", "question": "so2al el fella7 bel 3arbizi", "actions": ["id1"]}'


def repondre(question, pid=None, historique=None, cfg=None, appel=None, voix=False):
    cfg = cfg or config()
    question = (question or "").strip()[:500]
    faits, actions = indexer_tout(pid, cfg)
    passages = V.chercher(question, cfg, parcelle_id=pid)
    par_id = {a["id"]: a for a in actions}
    sources = [{"titre": p["titre"], "source": p.get("source"), "url": p.get("url"), "score": p["score"]}
               for p in passages[:5]]
    if not cfg.get("cle") and appel is None:
        return {"reponse": _secours(passages), "actions": actions[:2], "sources": sources,
                "mode": "secours"}
    contexte = "\n".join(f"[{i + 1}] ({p.get('source')}) {p['titre']} : {p['texte']}" for i, p in enumerate(passages))
    hist = "\n".join(f"{m.get('role')}: {str(m.get('text', ''))[:300]}" for m in (historique or [])[-6:])
    ecriture = cfg.get("ecriture") or "arabizi"
    prompt = PROMPT.format(consigne_voix=CONSIGNE_VOIX if voix else "",
                           consigne_ecriture=ECRITURES.get(ecriture, ECRITURES["arabizi"]),
                           format_json=FORMAT_JSON_VOIX if voix else FORMAT_JSON,
                           glossaire=GLOSSAIRE_TOUNSI, parcelle=json.dumps(faits, ensure_ascii=False, default=str),
                           contexte=contexte or "(rien)", question=question, historique=hist or "(rien)",
                           actions="\n".join(f"- {a['id']} : {a['label']}" for a in actions) or "(aucune)")
    try:
        principal = cfg.get("modele_voix") if voix else cfg["modele"]
        modeles = list(dict.fromkeys([principal, cfg["modele"], *(cfg.get("modeles_secours") or [])]))
        data = _lire_json((appel or _appeler_gemini)(cfg["cle"], modeles if appel is None else cfg["modele"], prompt))
        texte = str(data.get("reponse") or "").strip()
        if not texte:
            raise ValueError("réponse vide")
        choisies = [par_id[i] for i in data.get("actions") or [] if i in par_id][:3]
        out = {"reponse": texte, "actions": choisies, "sources": sources, "mode": "gemini"}
        if voix:   # texte à lire (lettres arabes) + question réécrite en 3arbizi pour l'affichage
            out["a_dire"] = str(data.get("a_dire") or "").strip() or texte
            out["question"] = str(data.get("question") or "").strip()
        return out
    except Exception as e:   # noqa: BLE001
        return {"reponse": _secours(passages, gemini_indisponible=True), "actions": actions[:2], "sources": sources,
                "mode": "secours", "erreur": f"{type(e).__name__}: {str(e)[:150]}"}
