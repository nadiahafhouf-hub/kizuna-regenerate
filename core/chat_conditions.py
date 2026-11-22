"""Réponses du jour à partir de la météo et du planning de la parcelle."""
import re
import unicodedata
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from services.demo_data import land_profile

from .chat_controls import choix_parcelles


def conditions_du_jour(question, pid):
    normalized = unicodedata.normalize("NFKD", question.casefold())
    text = "".join(c for c in normalized if not unicodedata.combining(c))
    today = re.search(r"\b(l[yi]oum|el youm|aujourd.hui|today)\b", text)
    temperature = today and re.search(r"\b(temperature|thermometre|degres)\b", text)
    pompe = re.search(r"\b(pompe|pmpe?|pompage|pump)\b", text) and (
        today or re.search(r"\b(quand|heures?|horaires?|creneaux?|wa9tech|wakteh|wa9teh|waktach|when)\b", text))
    zone_rouge = re.search(r"\bzones? rouges?\b", text) and re.search(r"\b(ou|montre|affiche|localise|where|show)\b", text)
    if not temperature and not pompe and not zone_rouge:
        return None

    result = {"reply": "Pour quelle parcelle ? Choisissez son nom ci-dessous, ou dites son code.",
              "actions": [], "sources": [], "mode": "local"}
    if not pid:
        result["actions"] = choix_parcelles(question)
        return result

    if zone_rouge:
        url = reverse("diagnostics:index", args=[pid]) + "?chat_focus=red-zone"
        zones = [z["id"] for z in land_profile(pid).get("zones", []) if z.get("couleur") == "ROUGE"]
        result["actions"] = [{"id": "diagnostic", "label": "Voir la carte du diagnostic", "url": url}]
        if zones:
            result.update(reply=f"Zones rouges sur la carte de {pid} : {', '.join(zones)}.", navigate=url)
        else:
            result.update(reply=f"Le diagnostic de {pid} ne contient aucune zone rouge.", reaction="concern")
        return result

    from irrigation.models import IrrigationEvent, IrrigationPlan

    jour = timezone.localdate()
    url = reverse("irrigation:index", args=[pid])
    if pompe:
        url += "?" + urlencode({"chat_focus": "pump", "date": jour.isoformat()})
        if re.search(r"\b(montre|affiche|ouvre|show)\b", text):
            result["navigate"] = url
    result["actions"] = [{"id": "irrigation", "label": "Voir le planning d’irrigation", "url": url}]
    plan = IrrigationPlan.objects.filter(parcel__parcelle_id=pid).exclude(planning={}).first()
    lignes = [f"Parcelle {pid} — {jour:%d/%m/%Y}"]
    if temperature:
        from advisor.services.climat import climat_de_secours
        from irrigation.services.meteo import prevision_7_jours

        profil = land_profile(pid)
        lat, lon = profil["origine"]["lat"], profil["origine"]["lon"]
        climat = climat_de_secours(lat, lon, profil.get("region"))
        meteo = prevision_7_jours(lat, lon, climat, jour, timeout=3, cache_dir=settings.BASE_DIR / "cache")
        prevision = next((j for j in meteo["jours"] if j["date"] == jour.isoformat()), {})
        minimum, maximum = prevision.get("tmin_c"), prevision.get("tmax_c")
        if minimum is None or maximum is None:
            lignes.append("La température prévue aujourd’hui est indisponible.")
        else:
            lignes.append(f"Température prévue aujourd’hui : de {minimum} à {maximum} °C (Open-Meteo).")

    if pompe:
        jours_plan = plan.planning.get("jours", []) if plan and isinstance(plan.planning, dict) else []
        if not any(j["date"] == jour.isoformat() for j in jours_plan):
            lignes.append("Le planning ne couvre pas aujourd’hui. Ouvrez Irrigation pour consulter ou actualiser le plan.")
            result["reaction"] = "concern"
        else:
            heures = plan.programme.filter(date=jour, type=IrrigationEvent.Type.POMPAGE,
                                           statut=IrrigationEvent.Statut.PREVU).values_list("heure", flat=True).distinct()
            horaires = ", ".join(dict.fromkeys(h.strftime("%H:%M") for h in heures))
            if horaires:
                lignes.append(f"Créneaux de pompage prévus dans le planning : {horaires} (heure locale).")
                if plan.statut != IrrigationPlan.Statut.AUTO:
                    lignes.append("Le mode automatique est désactivé.")
            else:
                lignes.append("Il ne reste aucun créneau de pompage prévu aujourd’hui.")
                result["reaction"] = "concern"
    result["reply"] = "\n".join(lignes)
    return result
