"""Base vectorielle Qdrant du chatbot (bloc 4) + embeddings.

- Qdrant en mode embarqué (dossier local, aucun serveur) ; ou un serveur Qdrant si QDRANT_URL est défini.
- Deux familles d'embeddings, chacune dans SA collection (dimensions différentes) :
    « local »  : n-grammes de caractères hachés (1024 dimensions), toujours disponible, hors ligne,
                 robuste aux orthographes du tounsi en lettres latines (3arbizi) ;
    « gemini » : modèle d'embedding Gemini (GEMINI_EMBED_MODEL), si la clé fonctionne.
- Deux types de documents : « connaissance » (base Gabès + glossaire) et « parcelle » (données d'une parcelle,
  filtrées par parcelle_id), réindexés seulement quand leur contenu change (empreinte).
"""
import hashlib
import threading
import uuid

import numpy as np

DIM_LOCAL = 1024
_verrou = threading.Lock()
_client = None
_client_cle = None
_vectoriseur = None
_a_jour = {}            # (collection, groupe) -> empreinte déjà indexée dans ce processus


# ───────────────────────────── embeddings ─────────────────────────────

def _local(textes):
    global _vectoriseur
    if _vectoriseur is None:
        from sklearn.feature_extraction.text import HashingVectorizer
        _vectoriseur = HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), n_features=DIM_LOCAL,
                                         alternate_sign=False, norm="l2", lowercase=True)
    return _vectoriseur.transform(textes).toarray().astype(np.float32)


def _gemini(textes, cle, modele, tache):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=cle)
    try:
        out = []
        for i in range(0, len(textes), 50):
            rep = client.models.embed_content(
                model=modele, contents=textes[i:i + 50],
                config=types.EmbedContentConfig(task_type=tache, output_dimensionality=768))
            out.extend(e.values for e in rep.embeddings)
        v = np.array(out, dtype=np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    finally:
        try:
            client.close()
        except Exception:
            pass


def familles(config):
    """Familles d'embeddings utilisables : gemini (si clé) puis local (toujours)."""
    f = []
    if config.get("cle") and config.get("modele_embedding"):
        f.append("gemini")
    f.append("local")
    return f


def vecteurs(textes, famille, config, tache="RETRIEVAL_DOCUMENT"):
    if famille == "gemini":
        return _gemini(textes, config["cle"], config["modele_embedding"], tache)
    return _local(textes)


# ───────────────────────────── Qdrant ─────────────────────────────

def client(config):
    """Client Qdrant partagé (un seul par processus : le mode embarqué verrouille son dossier)."""
    global _client, _client_cle
    from qdrant_client import QdrantClient
    cle = (config.get("url"), config.get("chemin"))
    with _verrou:
        if _client is None or _client_cle != cle:
            if config.get("url"):
                _client = QdrantClient(url=config["url"], api_key=config.get("qdrant_cle") or None)
            elif config.get("chemin") in (None, ":memory:"):
                _client = QdrantClient(location=":memory:")
            else:
                _client = QdrantClient(path=str(config["chemin"]))
            _client_cle = cle
            _a_jour.clear()
        return _client


def fermer():
    global _client, _client_cle
    with _verrou:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client, _client_cle = None, None
        _a_jour.clear()


def nom_collection(famille):
    return "kizuna_" + famille


def _assurer(c, famille, dim):
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams
    nom = nom_collection(famille)
    if not c.collection_exists(nom):
        c.create_collection(nom, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        if _client_cle and _client_cle[0]:   # serveur Qdrant : index sur les filtres (inutiles en mode embarqué)
            for champ in ("type", "parcelle_id", "groupe"):
                try:
                    c.create_payload_index(nom, champ, PayloadSchemaType.KEYWORD)
                except Exception:
                    pass
    return nom


def empreinte(docs):
    return hashlib.sha256("\n".join(d["texte"] for d in docs).encode("utf-8")).hexdigest()[:16]


def indexer(docs, groupe, config, parcelle_id=None, type_doc="connaissance"):
    """Remplace les documents d'un groupe (ex. « connaissances » ou « parcelle:GAB-001 ») s'ils ont changé.
    docs = [{"titre", "texte", "url"?, "source"?}]. Renvoie le nombre de documents réindexés (0 = à jour)."""
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PointStruct
    if not docs:
        return 0
    emp = empreinte(docs)
    c = client(config)
    total = 0
    filtre = Filter(must=[FieldCondition(key="groupe", match=MatchValue(value=groupe))])
    for famille in familles(config):
        nom = nom_collection(famille)
        # déjà à jour ? (vérifié AVANT de calculer les embeddings : pas d'appel Gemini inutile)
        if _a_jour.get((nom, groupe)) == emp:
            continue
        if c.collection_exists(nom):
            existants, _ = c.scroll(nom, scroll_filter=filtre, limit=1, with_payload=True)
            if existants and existants[0].payload.get("empreinte") == emp:
                _a_jour[(nom, groupe)] = emp
                continue
        try:
            v = vecteurs([f"{d['titre']}\n{d['texte']}" for d in docs], famille, config)
        except Exception:
            continue          # Gemini indisponible : la famille locale suffit
        nom = _assurer(c, famille, v.shape[1])
        c.delete(nom, points_selector=FilterSelector(filter=filtre))
        c.upsert(nom, points=[PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{groupe}|{i}|{emp}")), vector=v[i].tolist(),
            payload={**d, "groupe": groupe, "type": type_doc, "parcelle_id": parcelle_id or "", "empreinte": emp})
            for i, d in enumerate(docs)])
        _a_jour[(nom, groupe)] = emp
        total = len(docs)
    return total


def chercher(question, config, parcelle_id=None, k_connaissances=4, k_parcelle=6):
    """Documents les plus proches de la question : connaissances générales + données de LA parcelle."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    c = client(config)
    for famille in familles(config):
        nom = nom_collection(famille)
        if not c.collection_exists(nom):
            continue
        try:
            q = vecteurs([question], famille, config, tache="RETRIEVAL_QUERY")[0].tolist()
        except Exception:
            continue
        res = []
        filtres = [(Filter(must=[FieldCondition(key="type", match=MatchValue(value="connaissance"))]), k_connaissances)]
        if parcelle_id:
            filtres.append((Filter(must=[FieldCondition(key="parcelle_id", match=MatchValue(value=parcelle_id))]),
                            k_parcelle))
        for filtre, k in filtres:
            pts = c.query_points(nom, query=q, query_filter=filtre, limit=k, with_payload=True).points
            res += [{**p.payload, "score": round(float(p.score), 3), "famille": famille} for p in pts]
        if res:
            return sorted(res, key=lambda d: -d["score"])
    return []
