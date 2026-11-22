from .strings import get_strings

RTL_LANGS = {"ar"}


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
        "chat_config": {"suggestions": T["chat"].get("suggestions_list") or chatbot_config()["suggestions"],
                        "welcome": T["chat"]["welcome"],
                        "pid": pid},
    }
