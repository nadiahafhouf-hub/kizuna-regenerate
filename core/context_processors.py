from .strings import get_strings

RTL_LANGS = {"ar"}

# Page experte -> page Farmer équivalente (même parcelle)
FARMER_PAGES = {"diagnostics": "soil", "advisor": "plants", "irrigation": "water",
                "energy": "sun", "passport": "certificate"}


def _farmer_url(request):
    from django.urls import reverse
    rm = getattr(request, "resolver_match", None)
    try:
        pid = rm and rm.kwargs.get("pid")
        if pid and rm.namespace in FARMER_PAGES:
            return reverse(f"farmer:{FARMER_PAGES[rm.namespace]}", args=[pid])
        return reverse("farmer:home")
    except Exception:
        return "/farm/"


def ui(request):
    """Injecte les textes de l'interface (T), la langue, le sens d'écriture et la
    configuration du chatbot (présent sur toutes les pages)."""
    from services.demo_data import chatbot_config

    lang = request.session.get("lang", "en") if hasattr(request, "session") else "en"
    T = get_strings(lang)
    # La parcelle de la page fournit le contexte du chatbot.
    match = getattr(request, "resolver_match", None)
    pid = match.kwargs.get("pid") if match else None
    return {
        "T": T,
        "LANG": lang,
        "DIR": "rtl" if lang in RTL_LANGS else "ltr",
        "FARMER_URL": _farmer_url(request),
        "chat_config": {"suggestions": T["chat"].get("suggestions_list") or chatbot_config()["suggestions"],
                        "welcome": T["chat"]["welcome"],
                        "pid": pid,
                        # chatbot vocal (tounsi) : parler / relire un message
                        "voiceUrl": "/chat/voice/", "ttsUrl": "/chat/tts/"},
    }
