from django.shortcuts import get_object_or_404, render

from .models import Passport


def index(request):
    """Squelette bloc 4. À faire sur bloc-4 : création du passeport depuis un LandProfile,
    PDF + QR (services/passport_generator.py), chatbot RAG (services/rag/)."""
    return render(request, "passport/index.html", {
        "passeports": Passport.objects.select_related("parcel").order_by("-id")[:20],
    })


def verify(request, passport_id):
    """Page publique ciblée par le QR code : recalcule le hash et vérifie la chaîne."""
    passeport = get_object_or_404(Passport.objects.select_related("parcel"), pk=passport_id)
    return render(request, "passport/verify.html", {
        "passeport": passeport,
        "valide": passeport.is_valid(),
    })
