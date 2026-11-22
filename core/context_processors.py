from .strings import get_strings

RTL_LANGS = {"ar"}


def ui(request):
    """Injecte les textes de l'interface (T), la langue, le sens d'écriture et la
    configuration du chatbot (présent sur toutes les pages)."""
    from services.demo_data import chatbot_config

    lang = request.session.get("lang", "en") if hasattr(request, "session") else "en"
    T = get_strings(lang)
    return {
        "T": T,
        "LANG": lang,
        "DIR": "rtl" if lang in RTL_LANGS else "ltr",
        "chat_config": {"suggestions": T["chat"].get("suggestions_list") or chatbot_config()["suggestions"],
                        "welcome": T["chat"]["welcome"],
                        # parcelle de la page : le chatbot répond avec SES données (bloc 1 à 4 + solaire)
                        "pid": (getattr(request, "resolver_match", None) and
                                request.resolver_match.kwargs.get("pid")) or None},
    }
