"""Commandes de l’interface reconnues localement par le chatbot."""
import re
import unicodedata

from django.http import Http404
from django.urls import reverse

from services import demo_data

STEP_URLS = {
    "diagnostic": "diagnostics:index",
    "crops": "advisor:index",
    "irrigation": "irrigation:index",
    "solar": "energy:index",
    "passport": "passport:index",
}

DESTINATIONS = {
    "dashboard": ("core:home", "Dashboard"),
    "new_parcel": ("new_parcel", "New parcel"),
}

ALIASES = {
    "dashboard": ("accueil", "tableau de bord", "dashboard", "home"),
    "new_parcel": ("nouvelle parcelle", "new parcel"),
    "diagnostic": ("diagnostic", "diagnostic du sol", "soil diagnostic"),
    "crops": ("culture", "cultures", "crops", "recommandations", "zraye3"),
    "irrigation": ("irrigation", "planning", "planning d irrigation", "sa9i"),
    "solar": ("solaire", "panneaux solaires", "energie solaire", "solar"),
    "passport": ("passeport", "passeport du sol", "passport", "soil passport"),
}
COMMANDS = {alias: key for key, aliases in ALIASES.items() for alias in aliases}
NAVIGATION = re.compile(r"^(?:ouvr(?:e[z]?|ir)|affich(?:e[z]?|er)|montre(?: moi)?|va (?:sur|a|au|aux|dans)|open|show(?: me)?|go to|7ell) (?:(?:le|la|les|l|el|the) )?(.+)$")
SIMULATION = {"simule la journee suivante", "simuler la journee suivante", "simule le jour suivant",
              "simuler le jour suivant", "simulate next day", "simulate the next day"}
PARCEL_TARGET = re.compile(r"(?:(?:parcelle|parcel) |(.+?) (?:pour|de|sur) (?:(?:la )?parcelle )?)([a-z]+(?: [a-z])*) ([0-9]+(?: [0-9]+)*)")
DIGITS = dict(zip("zero un deux trois quatre cinq six sept huit neuf".split(), "0123456789"))
FRENCH_LABELS = {"dashboard": "le tableau de bord", "new_parcel": "la création de parcelle",
                 "diagnostic": "le diagnostic", "crops": "les cultures", "irrigation": "l’irrigation",
                 "solar": "le solaire", "passport": "le passeport"}


def step_action(key, pid, strings):
    label = next(step["label"] for step in strings["steps"] if step["key"] == key)
    return {"id": key, "label": label, "url": reverse(STEP_URLS[key], args=[pid])}


def destination(key):
    route, label = DESTINATIONS[key]
    return {"id": key, "label": label, "url": reverse(route)}


def choix_parcelles(question):
    return [{"id": parcel["id"], "label": f'{parcel["id"]} · {parcel["name"]}',
             "kind": "parcel", "question": question} for parcel in demo_data._parcel_records()]


def command(question, pid, strings, voice=False):
    normalized = unicodedata.normalize("NFKD", question.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    text = " ".join(re.findall(r"[a-z0-9]+", normalized))
    text = re.sub(r"(?: s il te plait| s il vous plait)$", "", text)
    text = re.sub(r"^(?:peux tu|pourrais tu|tu peux) ", "", text)
    simulate = text in SIMULATION
    match = NAVIGATION.fullmatch(text)
    target = match[1] if match else text if question.lstrip().startswith("/") else None
    if target:
        target = re.sub(r"^page (?:de |d )?", "", target)
    key = COMMANDS.get(target)
    parcel_words = (target or "").split()
    for index in range(len(parcel_words) - 1, -1, -1):
        word = parcel_words[index]
        if word not in DIGITS and not word.isdigit():
            break
        parcel_words[index] = DIGITS.get(word, word)
    parcel = PARCEL_TARGET.fullmatch(" ".join(parcel_words))
    named_parcel = None
    if parcel:
        page, region, number = parcel.groups()
        key = COMMANDS.get(page, "diagnostic") if page is None else COMMANDS.get(page)
        named_parcel = f"{region.replace(' ', '').upper()}-{number.replace(' ', '').zfill(3)}"
        pid = named_parcel
    if not key and not simulate:
        return None

    actions = []
    labels = strings["chat"]
    navigate = None
    if key in DESTINATIONS:
        actions = [destination(key)]
        navigate = actions[0]["url"]
    else:
        try:
            has_profile = bool(pid and demo_data.has_profile(pid))
        except Http404:
            pid = None
            has_profile = False
        if not pid:
            actions = choix_parcelles(question) if not named_parcel else [destination("dashboard")]
            if not actions:
                actions = [destination("dashboard")]
            reply = (f"Je ne trouve pas la parcelle {named_parcel}." if named_parcel else
                     "Pour quelle parcelle ? Choisissez son nom ci-dessous, ou dites son code.")
        elif simulate and not has_profile:
            actions = [step_action("diagnostic", pid, strings)]
            reply = "Terminez le diagnostic de cette parcelle avant de simuler l’irrigation." if voice else labels["control_need_diagnostic"]
        elif simulate:
            actions = [{"id": "simulate_day", "kind": "simulate", "label": labels["control_confirm"],
                        "url": reverse("irrigation:simuler", args=[pid])}]
            reply = (f"Confirmez-vous la simulation du jour suivant pour {pid} ? Dites « confirme » ou « annule »."
                     if voice else labels["control_confirm_prompt"].format(pid=pid))
        else:
            actions = [step_action(key, pid, strings)]
            navigate = actions[0]["url"]
    if navigate:
        reply = f"J’ouvre {FRENCH_LABELS[key]}." if voice else labels["control_open"].format(label=actions[0]["label"])
    return {"reply": reply, "actions": actions, "sources": [], "mode": "control", "navigate": navigate}
