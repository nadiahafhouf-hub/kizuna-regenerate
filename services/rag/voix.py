"""Voix du chatbot en tounsi : écouter (parole -> texte) et parler (texte -> parole).

- Écouter : Azure Speech, reconnaissance « ar-TN » (arabe, Tunisie) ; secours : Gemini (entrée audio).
- Parler  : Azure Speech, voix tunisiennes ar-TN-ReemNeural (femme) / ar-TN-HediNeural (homme), MP3.
Appels REST directs (aucun SDK Azure à installer). Sans Django : la configuration est passée en paramètre.
L'audio d'entrée est un WAV PCM 16 bits mono 16 kHz (enregistré et converti par le navigateur).
"""
import json
import re
import time
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

FORMAT_SORTIE = "audio-24khz-48kbitrate-mono-mp3"
MAX_CARACTERES = 1200       # une réponse parlée courte (le texte complet reste affiché)


class VoixErreur(Exception):
    pass


def config_voix():
    try:
        from django.conf import settings
        return {
            "azure_cle": getattr(settings, "AZURE_SPEECH_KEY", ""),
            "azure_region": getattr(settings, "AZURE_SPEECH_REGION", ""),
            "voix": getattr(settings, "AZURE_TTS_VOICE", "ar-TN-HediNeural"),
            "langue": getattr(settings, "AZURE_STT_LANGUAGE", "ar-TN"),
            "gemini_cle": getattr(settings, "GEMINI_API_KEY", ""),
            "gemini_modele": getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash"),
            "edge": getattr(settings, "VOIX_EDGE_TTS", True),
            "lahgtna": getattr(settings, "VOIX_LAHGTNA", True),
            "lahgtna_space": getattr(settings, "VOIX_LAHGTNA_SPACE", "AVOiD/derja-tts"),
            "lahgtna_delai": getattr(settings, "VOIX_LAHGTNA_DELAI_S", 45),
            "hf_token": getattr(settings, "HF_TOKEN", ""),
            "reference": getattr(settings, "VOIX_REFERENCE", "") or
                         str(__import__("pathlib").Path(settings.MEDIA_ROOT) / "voix" / "reference.mp3"),
            "reference_texte": getattr(settings, "VOIX_REFERENCE_TEXTE", ""),
            "whisper": getattr(settings, "WHISPER_DERJA_MODEL", ""),
        }
    except Exception:
        return {}


def azure_active(cfg):
    return bool(cfg.get("azure_cle") and cfg.get("azure_region"))


def _http(url, data, entetes, timeout=30):
    req = urllib.request.Request(url, data=data, headers=entetes, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise VoixErreur(f"Azure HTTP {e.code} : {detail or e.reason}") from e
    except (urllib.error.URLError, OSError) as e:
        raise VoixErreur(f"Azure injoignable : {getattr(e, 'reason', e)}") from e


# ───────────────────────────── écouter ─────────────────────────────

def azure_stt(wav, cfg, http=None):
    """Reconnaissance vocale Azure (audio court, < 60 s) en arabe tunisien."""
    url = (f"https://{cfg['azure_region']}.stt.speech.microsoft.com/speech/recognition/conversation/"
           f"cognitiveservices/v1?language={cfg.get('langue') or 'ar-TN'}&format=simple")
    rep = (http or _http)(url, wav, {"Ocp-Apim-Subscription-Key": cfg["azure_cle"],
                                     "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                                     "Accept": "application/json"})
    d = json.loads(rep.decode("utf-8"))
    if d.get("RecognitionStatus") != "Success":
        raise VoixErreur(f"rien reconnu ({d.get('RecognitionStatus')})")
    return (d.get("DisplayText") or "").strip()


_whisper = {}


def whisper_stt(wav, cfg):
    """Écoute GRATUITE et hors ligne : Whisper-small entraîné sur le tounsi (derja + mots français),
    exécuté sur le PC (faster-whisper, int8). Modèle : TheBiggyBang/whisper-small-tunisian-derja-ct2
    (chemin local ou identifiant Hugging Face, téléchargé une seule fois)."""
    import io
    modele = cfg.get("whisper")
    if not modele:
        raise VoixErreur("Whisper Derja désactivé")
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise VoixErreur("faster-whisper non installé") from e
    try:
        if modele not in _whisper:   # chargé une seule fois par processus (~0,5 s)
            _whisper[modele] = WhisperModel(modele, device="cpu", compute_type="int8")
        segments, _ = _whisper[modele].transcribe(io.BytesIO(wav), language="ar", beam_size=5, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        raise VoixErreur(f"Whisper Derja : {type(e).__name__}: {str(e)[:150]}") from e


def gemini_stt(wav, cfg, appel=None):
    """Secours : Gemini écoute l'audio et le transcrit tel quel en derja (écriture arabe)."""
    if not cfg.get("gemini_cle"):
        raise VoixErreur("ni Azure ni Gemini configurés")
    consigne = ("Transcris exactement ce que dit cette personne. Elle parle tunisien (derja), parfois avec des mots "
                "français. Écris la derja en lettres arabes et garde les mots français tels quels. Renvoie seulement "
                "la transcription, sans commentaire.")
    if appel:
        return appel(wav, consigne).strip()
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=cfg["gemini_cle"])
    try:
        for essai in range(3):
            try:
                rep = client.models.generate_content(
                    model=cfg.get("gemini_modele") or "gemini-3.8-flash",
                    contents=[types.Part.from_bytes(data=wav, mime_type="audio/wav"), consigne])
                return (rep.text or "").strip()
            except Exception as e:
                if essai == 2 or not any(c in str(e) for c in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    raise VoixErreur(f"Gemini : {type(e).__name__}: {str(e)[:150]}") from e
                time.sleep(3 * (essai + 1))
    finally:
        try:
            client.close()
        except Exception:
            pass


def transcrire(wav, cfg=None, http=None, appel_gemini=None, whisper=None):
    """(texte, moteur). Azure ar-TN (si clé), puis Whisper Derja local (gratuit), puis Gemini en secours."""
    cfg = cfg or config_voix()
    if not wav or len(wav) < 1000:
        raise VoixErreur("enregistrement vide ou trop court")
    erreurs = []
    if azure_active(cfg):
        try:
            t = azure_stt(wav, cfg, http=http)
            if t:
                return t, "azure"
        except VoixErreur as e:
            erreurs.append(str(e))
    if cfg.get("whisper") or whisper:
        try:
            t = (whisper or whisper_stt)(wav, cfg)
            if t:
                return t, "whisper-derja"
        except VoixErreur as e:
            erreurs.append(str(e))
    try:
        t = gemini_stt(wav, cfg, appel=appel_gemini)
        if t:
            return t, "gemini"
    except VoixErreur as e:
        erreurs.append(str(e))
    raise VoixErreur(" ; ".join(erreurs) or "transcription impossible")


# ───────────────────────────── parler ─────────────────────────────

def texte_a_dire(texte):
    """Texte propre pour la voix : sans puces, émojis, liens ni répétitions de ponctuation."""
    t = re.sub(r"https?://\S+", "", texte or "")
    t = re.sub(r"^[\s•\-\*\d\.\)]+", "", t, flags=re.M)
    t = re.sub(r"[*_#>`~|]", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t[:MAX_CARACTERES]


def edge_tts_mp3(texte, voix="ar-TN-ReemNeural"):
    """Voix tunisiennes GRATUITES, sans clé ni carte : service « Lecture à voix haute » de Microsoft Edge
    (paquet edge-tts). Mêmes voix que Azure (Reem, Hedi). Service non officiel : peut changer sans préavis."""
    import asyncio
    try:
        import edge_tts
    except ImportError as e:
        raise VoixErreur("edge-tts non installé (pip install edge-tts)") from e
    t = texte_a_dire(texte)
    if not t:
        raise VoixErreur("rien à dire")

    async def generer():
        morceaux = []
        async for m in edge_tts.Communicate(t, voix or "ar-TN-ReemNeural", rate="-5%").stream():
            if m["type"] == "audio":
                morceaux.append(m["data"])
        return b"".join(morceaux)
    try:
        audio = asyncio.run(generer())
    except Exception as e:
        raise VoixErreur(f"edge-tts : {type(e).__name__}: {str(e)[:150]}") from e
    if not audio:
        raise VoixErreur("edge-tts : audio vide")
    return audio


REFERENCE_TEXTE_DEFAUT = ("عسلامة! اليوم تسقي الزونة زد ثلاثة مع الستة الصباح، مية و خمسين لتر، "
                          "و البومبة الشمسية تخدم من الحداش للثلاثة.")
_lahgtna = {}


def _reference(cfg):
    """(chemin, texte) de l'enregistrement dont Lahgtna imite la voix ; créé une fois avec edge-tts si absent."""
    import pathlib
    chemin = pathlib.Path(cfg.get("reference") or "reference.mp3")
    texte = cfg.get("reference_texte") or REFERENCE_TEXTE_DEFAUT
    if not chemin.exists():
        if cfg.get("reference_texte"):
            raise VoixErreur(f"enregistrement de référence introuvable : {chemin}")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(edge_tts_mp3(REFERENCE_TEXTE_DEFAUT, cfg.get("voix") or "ar-TN-HediNeural"))
        texte = REFERENCE_TEXTE_DEFAUT
    return str(chemin), texte


def lahgtna_tts(texte, cfg, appel=None):
    """Voix avec un VRAI accent tunisien : modèle « Lahgtna » entraîné sur la derja (Space Hugging Face, GPU
    gratuit, sans compte ni carte). Renvoie un WAV. Le texte doit être en lettres arabes."""
    t = texte_a_dire(texte)
    if not t:
        raise VoixErreur("rien à dire")
    ref, ref_texte = _reference(cfg)
    if appel:
        return appel(t, ref, ref_texte)
    import concurrent.futures as cf
    import pathlib
    try:
        from gradio_client import Client, handle_file
    except ImportError as e:
        raise VoixErreur("gradio_client non installé") from e

    def generer():
        space = cfg.get("lahgtna_space") or "AVOiD/derja-tts"
        if space not in _lahgtna:   # jeton Hugging Face gratuit = quota GPU quotidien plus grand qu'en anonyme
            jeton = cfg.get("hf_token") or None
            try:
                _lahgtna[space] = Client(space, token=jeton, verbose=False)        # gradio_client >= 2
            except TypeError:
                _lahgtna[space] = Client(space, hf_token=jeton, verbose=False)     # gradio_client 1.x
        # erreur GPU passagère du Space (« AcceleratorError ») : un nouvel essai, puis le moteur Silma F5
        # (lui aussi entraîné sur la derja) avant la voix Hedi
        derniere = None
        for moteur in ("Lahgtna (recommended)", "Lahgtna (recommended)", "Silma F5 (classic)"):
            try:
                audio, _ = _lahgtna[space].predict(moteur, t, handle_file(ref), ref_texte, 1.0, 42,
                                                   2.0, 32, 0.4, 0.7, 0.5, True, api_name="/generate")
                return pathlib.Path(audio).read_bytes()
            except Exception as e:   # noqa: BLE001
                if "limit" in str(e).lower():   # quota GPU épuisé : inutile d'insister
                    raise
                derniere = e
        raise derniere
    ex = cf.ThreadPoolExecutor(1)
    try:
        return ex.submit(generer).result(timeout=cfg.get("lahgtna_delai") or 45)
    except cf.TimeoutError as e:
        raise VoixErreur("Lahgtna trop lent (Space occupé)") from e
    except Exception as e:
        _lahgtna.clear()   # client à recréer au prochain essai
        raise VoixErreur(f"Lahgtna : {type(e).__name__}: {str(e)[:150]}") from e
    finally:
        ex.shutdown(wait=False)


def synthese(texte, cfg=None, http=None):
    """(audio, type MIME) : Azure (si clé) -> Lahgtna (vrai accent tunisien) -> edge-tts (Hedi / Reem)."""
    cfg = cfg or config_voix()
    erreurs = []
    if azure_active(cfg):
        try:
            return azure_tts(texte, cfg, http=http), "audio/mpeg"
        except VoixErreur as e:
            erreurs.append(str(e))
    if cfg.get("lahgtna"):
        try:
            return lahgtna_tts(texte, cfg), "audio/wav"
        except VoixErreur as e:
            erreurs.append(str(e))
    if cfg.get("edge", True):
        try:
            return edge_tts_mp3(texte, cfg.get("voix")), "audio/mpeg"
        except VoixErreur as e:
            erreurs.append(str(e))
    raise VoixErreur(" ; ".join(erreurs) or "aucune voix configurée")


def azure_tts(texte, cfg=None, http=None):
    """MP3 de la réponse lue par une voix tunisienne Azure."""
    cfg = cfg or config_voix()
    if not azure_active(cfg):
        raise VoixErreur("Azure Speech non configuré (AZURE_SPEECH_KEY, AZURE_SPEECH_REGION)")
    t = texte_a_dire(texte)
    if not t:
        raise VoixErreur("rien à dire")
    voix = cfg.get("voix") or "ar-TN-ReemNeural"
    ssml = (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ar-TN'>"
            f"<voice name='{escape(voix)}'><prosody rate='-5%'>{escape(t)}</prosody></voice></speak>")
    url = f"https://{cfg['azure_region']}.tts.speech.microsoft.com/cognitiveservices/v1"
    return (http or _http)(url, ssml.encode("utf-8"), {
        "Ocp-Apim-Subscription-Key": cfg["azure_cle"], "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": FORMAT_SORTIE, "User-Agent": "kizuna-regenerate"})
