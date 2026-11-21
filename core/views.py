from django.shortcuts import render

from .models import Parcel, PollutionSource

BLOCS = [
    {"num": 1, "nom": "Diagnostic", "url": "diagnostics:index",
     "desc": "Capteurs CE, pH, Cd, Pb → grille 10 m → IDW → zones colorées."},
    {"num": 2, "nom": "Conseiller cultures", "url": "advisor:index",
     "desc": "Terre nue : recommandations. Terre plantée : photo + score d'optimalité."},
    {"num": 3, "nom": "Irrigation", "url": "irrigation:index",
     "desc": "Planning 7 jours (ET0 Open-Meteo), vanne simulée, pompe solaire."},
    {"num": 4, "nom": "Passeport", "url": "passport:index",
     "desc": "PDF + QR, chaîne de hash, page /verify, assistant RAG."},
]


def home(request):
    return render(request, "core/home.html", {
        "blocs": BLOCS,
        "parcelles": Parcel.objects.all()[:20],
        "sources": PollutionSource.objects.filter(actif=True)[:20],
    })
