from django.http import JsonResponse
from django.shortcuts import render

from .contract import load_sample
from .geo import land_profile_to_geojson


def index(request):
    return render(request, "diagnostics/index.html", {"profile": load_sample()})


def geojson(request):
    """Calque GeoJSON coloré. Pour l'instant à partir de l'exemple ; le bloc 1 branchera
    le LandProfile calculé."""
    return JsonResponse(land_profile_to_geojson(load_sample()))
