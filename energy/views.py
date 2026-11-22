import json
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.strings import get_strings
from core.views import journey_context

from .models import Alerte, ConfigSolaire, MesurePV, Nettoyage
from .services.projet import analyse

FIX = Path(settings.BASE_DIR) / "fixtures" / "energy"


def _metriques(nom):
    f = FIX / nom
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def index(request, pid):
    ctx = journey_context(pid, "solar")
    cfg, _ = ConfigSolaire.objects.get_or_create(parcelle_id=pid)
    if request.method == "POST":
        try:
            cfg.profondeur_m = max(1.0, min(300.0, float(request.POST.get("profondeur_m", cfg.profondeur_m))))
            cfg.panneau_wc = max(100, min(800, int(float(request.POST.get("panneau_wc", cfg.panneau_wc)))))
        except ValueError:
            pass
        plantes = {}
        for k, v in request.POST.items():
            if k.startswith("plants_") and v.strip():
                try:
                    plantes[k[7:]] = max(0, int(float(v)))
                except ValueError:
                    pass
        cfg.plantes = plantes
        cfg.save()
        return redirect("energy:index", pid)
    a = analyse(pid, cfg)
    etat = a["etat"]
    texte_action = None
    if etat:
        r, T = etat["recommandation"], get_strings()["solar"]["action"]
        cle = r["action"] if (r["action"] != "RIEN" or r["date_conseillee"]) else "RIEN_SANS_DATE"
        texte_action = T[cle].format(storm=(r.get("tempete") or {}).get("date", ""),
                                     rain=(r.get("pluie") or {}).get("date", ""), date=r.get("date_conseillee") or "")
    ctx.update({
        "cfg": cfg, "a": a, "dim": a["dim"], "etat": etat, "texte_action": texte_action,
        "current_ko": get_strings()["solar"]["current_ko"].format(
            pct=(a["actuelle"] or {}).get("couverture_pointe_pct", "")),
        "alertes": Alerte.objects.filter(parcelle_id=pid)[:6],
        "ia1": _metriques("ia1_metriques.json"), "ia2": _metriques("ia2_metriques.json"),
        "chart": {"mensuel": a["dim"]["mensuel"], "jours": (etat or {}).get("jours", []),
                  "nettoyage": (etat or {}).get("dernier_nettoyage")},
        "cleaned": request.GET.get("cleaned") == "1",
    })
    return render(request, "energy/solar.html", ctx)


@require_POST
def nettoye(request, pid):
    Nettoyage.objects.get_or_create(parcelle_id=pid, date=date.today())
    Alerte.objects.filter(parcelle_id=pid, type__in=["NETTOYER", "PREVOIR"], lue=False).update(lue=True)
    return redirect(f"{request.path.rsplit('clean/', 1)[0]}?cleaned=1")


@require_POST
def alertes_lues(request, pid):
    Alerte.objects.filter(parcelle_id=pid, lue=False).update(lue=True)
    return redirect("energy:index", pid)


@csrf_exempt
@require_POST
def api_mesures(request, pid):
    """ESP32 → JSON {"mesures": [{"t": "2026-11-22T12:00:00", "w": 412.5, "poa": 830, "t_air": 24.1}, …]}.
    (Pas d'authentification dans le prototype : à ajouter avant un vrai déploiement.)"""
    try:
        data = json.loads(request.body or b"{}")
        n = 0
        for m in data.get("mesures", [])[:5000]:
            t = datetime.fromisoformat(str(m["t"]))
            if timezone.is_naive(t):
                t = timezone.make_aware(t)
            MesurePV.objects.update_or_create(parcelle_id=pid, horodatage=t, defaults={
                "puissance_w": float(m["w"]), "poa_w_m2": m.get("poa"), "t_air_c": m.get("t_air")})
            n += 1
    except (ValueError, KeyError, TypeError) as e:
        return JsonResponse({"ok": False, "erreur": str(e)}, status=400)
    return JsonResponse({"ok": True, "enregistrees": n})
