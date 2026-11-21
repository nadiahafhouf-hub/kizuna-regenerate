from django.shortcuts import render

from diagnostics.contract import load_sample
from services.cultures import KC


def index(request):
    """Squelette bloc 3. À faire sur bloc-3 : appel Open-Meteo (ET0 FAO), planning
    7 jours = ET0 × Kc × surface (+ lessivage si CE élevée), validation, mode auto."""
    return render(request, "irrigation/index.html", {
        "profile": load_sample(),
        "kc": sorted(KC.items()),
    })
