"""Accès au contrat LandProfile partagé entre les blocs."""
import json
from pathlib import Path

from django.conf import settings

SAMPLE_PATH = Path(settings.BASE_DIR) / "fixtures" / "land_profile.sample.json"


def load_sample() -> dict:
    """LandProfile d'exemple : permet aux blocs 2-4 de développer sans attendre le bloc 1."""
    with open(SAMPLE_PATH, encoding="utf-8") as f:
        return json.load(f)


def latest_for(parcel) -> dict:
    """Dernier LandProfile calculé pour la parcelle, sinon l'exemple."""
    profil = parcel.profils.first() if parcel is not None else None
    return profil.data if profil else load_sample()
