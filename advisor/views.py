from django.shortcuts import render

from diagnostics.contract import load_sample
from services.cultures import cultures_compatibles


def index(request):
    """Squelette bloc 2 : affiche les zones de l'exemple et les cultures compatibles
    (terre nue). Le pop-up nue/plantée, l'upload photo et le score sont à faire sur bloc-2."""
    profile = load_sample()
    zones = []
    for z in profile["zones"]:
        ce_max = max((c["CE_dS_m"] for c in profile["cases"]
                      if [c["ligne"], c["col"]] in z["cases"]), default=0)
        zones.append({**z, "ce_max": ce_max,
                      "cultures": cultures_compatibles(z["couleur"], ce_max)})
    return render(request, "advisor/index.html", {"profile": profile, "zones": zones})
