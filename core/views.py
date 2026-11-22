import json
import logging

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from services import demo_data

from .chat_conditions import conditions_du_jour
from .chat_controls import STEP_URLS, command
from .strings import get_strings

logger = logging.getLogger(__name__)


def sans_diagnostic(request, pid):
    """Parcelle créée mais sol pas encore diagnostiqué : Crops, Irrigation et Passport ont besoin
    du LandProfile du bloc 1. On renvoie vers le plan des capteurs (comme la page Diagnostic)."""
    demo_data._record(pid)   # parcelle inconnue -> 404
    if demo_data.has_profile(pid):
        return None
    from django.contrib import messages
    messages.info(request, get_strings()["app"]["need_diagnostic"].format(pid=pid), extra_tags="diagnostic")
    return redirect("diagnostics:plan", pid)

def retour_farmer(request, suffixe=""):
    """Après une action postée depuis la vue Farmer (champ « next »), on y revient au lieu de la page experte."""
    from django.utils.http import url_has_allowed_host_and_scheme
    nxt = request.POST.get("next", "")
    if nxt.startswith("/farm/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt + suffixe)
    return None


def journey_context(pid, step) -> dict:
    """Contexte commun aux 4 pages du parcours : parcelle, stepper, sélecteur de parcelle."""
    keys = list(STEP_URLS)
    current = keys.index(step)
    steps = []
    for i, s in enumerate(get_strings()["steps"]):
        steps.append({**s, "url": reverse(STEP_URLS[s["key"]], args=[pid]),
                      "state": "current" if i == current else "done" if i < current else "todo"})
    try:
        p = demo_data.parcel(pid)
    except Http404:
        # parcelle créée mais pas encore diagnostiquée (plan des capteurs / saisie des relevés)
        p = {**demo_data._record(pid), "worst": "VERT", "zones_count": 0, "cells_count": 0}
    return {
        "parcel": p,
        "all_parcels": demo_data.parcels(),
        "steps": steps,
        "step": step,
        "step_url_name": STEP_URLS[step],
        "next_step": steps[current + 1] if current + 1 < len(steps) else None,
    }


def home(request):
    ps = demo_data.parcels()
    map_data = {
        "parcels": [{"id": p["id"], "name": p["name"], "worst": p["worst"], "center": p["center"],
                     "bounds": p["bounds"], "url": reverse("diagnostics:index", args=[p["id"]])}
                    for p in ps],
        "sources": demo_data.pollution_sources(),
    }
    return render(request, "core/dashboard.html", {
        "parcels_list": ps,
        "kpis": demo_data.global_kpis(),
        "map_data": map_data,
        "demo_pid": demo_data.DEMO_PARCEL,
        "solar_alerts": _alertes_solaires(),
    })


def _alertes_solaires():
    """Alertes non lues du volet photovoltaïque (app energy), pour le tableau de bord."""
    try:
        from energy.models import Alerte
        return list(Alerte.objects.filter(lue=False)[:5])
    except Exception:
        return []


def load_demo(request):
    return redirect("diagnostics:index", demo_data.DEMO_PARCEL)


@require_POST
def chat(request):
    """Chatbot (bloc 4) : RAG Qdrant + Gemini en derja tounsi, avec les données de la parcelle de la page.
    Corps JSON : {"q", "pid"?, "historique"?: [{"role", "text"}]} -> {"reply", "actions", "sources", "mode"}."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    q = str(data.get("q", ""))[:500]
    pid = data.get("pid") if isinstance(data.get("pid"), str) else None
    control = command(q, pid, get_strings(request.session.get("lang", "en")), voice=data.get("voice") is True)
    if control:
        return JsonResponse(control)
    if pid:
        try:
            demo_data.land_profile(pid)
        except Exception:   # parcelle inconnue ou sans diagnostic : connaissances générales seulement
            pid = None
    conditions = conditions_du_jour(q, pid)
    if conditions:
        return JsonResponse(conditions)
    try:
        from services.rag.assistant import repondre
        r = repondre(q, pid, data.get("historique") if isinstance(data.get("historique"), list) else None)
    except Exception as e:   # noqa: BLE001 - dernier recours : réponses de démonstration
        return JsonResponse({"reply": demo_data.chatbot_reply(q), "actions": [], "sources": [], "mode": "demo",
                             "error": type(e).__name__})
    if r.get("erreur"):   # réponse locale de secours : la vraie cause (quota, délai…) dans le journal du serveur
        logger.warning("Chatbot : Gemini indisponible (%s)", r["erreur"])
    return JsonResponse({"reply": r["reponse"], "actions": r["actions"], "sources": r["sources"], "mode": r["mode"]},
                        json_dumps_params={"ensure_ascii": False})


def _pid_valide(pid):
    if not pid:
        return None
    try:
        demo_data.land_profile(pid)
        return pid
    except Exception:
        return None


def _audio(texte):
    """{"audio": base64, "audio_mime"} lu par la voix tunisienne (Lahgtna, sinon edge-tts) ;
    audio None si aucune voix n'est disponible (le navigateur lit alors le texte avec sa voix arabe)."""
    import base64
    from services.rag.voix import VoixErreur, synthese
    try:
        audio, mime = synthese(texte)
        return {"audio": base64.b64encode(audio).decode("ascii"), "audio_mime": mime}
    except VoixErreur:
        return {"audio": None, "audio_mime": None}


@require_POST
def chat_voice(request):
    """Chatbot vocal : audio WAV (16 kHz mono) -> transcription tounsi (Azure ar-TN, sinon Gemini) ->
    réponse RAG en derja (écriture arabe, phrases courtes) -> voix tunisienne Azure (MP3 base64)."""
    from services.rag.assistant import repondre
    from services.rag.voix import VoixErreur, transcrire
    audio = request.FILES.get("audio")
    if audio is None or audio.size > 5 * 1024 * 1024:
        return JsonResponse({"error": "audio"}, status=400)
    try:
        texte, moteur = transcrire(audio.read())
    except VoixErreur as e:
        return JsonResponse({"error": "transcription", "detail": str(e)[:200]}, status=422)
    try:
        historique = json.loads(request.POST.get("historique") or "[]")
    except ValueError:
        historique = []
    try:
        r = repondre(texte, _pid_valide(request.POST.get("pid")), historique if isinstance(historique, list) else None,
                     voix=True)
    except Exception as e:   # noqa: BLE001
        r = {"reponse": demo_data.chatbot_reply(texte), "actions": [], "sources": [], "mode": "demo"}
    # texte lu : version en lettres arabes (a_dire) ; sans réponse Gemini, phrase courte en derja
    a_dire = (r.get("a_dire") or r["reponse"]) if r["mode"] == "gemini" else (
        "سامحني، ما نجمتش نجاوبك بالتفصيل توا. حطيتلك في الشاشة المعلومات اللي لقيتها على البلاد متاعك.")
    return JsonResponse({"transcription": r.get("question") or texte, "transcription_brute": texte, "stt": moteur,
                         "reply": r["reponse"], "a_dire": a_dire, "actions": r["actions"], "sources": r["sources"],
                         "mode": r["mode"], **_audio(a_dire)},
                        json_dumps_params={"ensure_ascii": False})


@require_POST
def chat_tts(request):
    """🔊 relire un message : {"text", "a_dire"?} -> {"audio": base64 | null, "audio_mime"}.
    Un texte en 3arbizi (lettres latines) est d'abord réécrit en lettres arabes pour la voix tunisienne."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = {}
    texte = str(data.get("a_dire") or data.get("text") or "")[:2000]
    if not texte.strip():
        return JsonResponse({"audio": None, "audio_mime": None})
    from services.rag.assistant import vers_lettres_arabes
    return JsonResponse(_audio(vers_lettres_arabes(texte)))
