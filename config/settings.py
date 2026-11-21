"""Paramètres Django — Kizuna Regenerate.

Les secrets (clé Django, clés API) sont lus depuis le fichier .env à la racine,
qui n'est JAMAIS commité. Voir .env.example.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# Clés API (vides = mode dégradé / règles locales)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# Bloc 3 : reseau goutte-a-goutte (services/irrigation_engine)
# Google Maps : cle serveur (Map Tiles API, image analysee) et cle navigateur (Maps JavaScript API,
# carte dynamique ; a restreindre par referent HTTP). Une seule cle suffit en developpement.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_MAPS_BROWSER_KEY = os.getenv("GOOGLE_MAPS_BROWSER_KEY", "") or GOOGLE_MAPS_API_KEY
# Image analysee : google (si cle) | esri (sans cle) | mapbox (MAPBOX_TOKEN) | URL XYZ personnalisee
SATELLITE_FOURNISSEUR = os.getenv("SATELLITE_FOURNISSEUR") or ("google" if GOOGLE_MAPS_API_KEY else "esri")
SATELLITE_TILE_URL = os.getenv("SATELLITE_TILE_URL") or None
SATELLITE_ZOOM = int(os.getenv("SATELLITE_ZOOM") or (20 if SATELLITE_FOURNISSEUR == "google" else 19))
SATELLITE_ATTRIBUTION = os.getenv("SATELLITE_ATTRIBUTION") or None
# Detection des plantes par IA (Gemini Vision, GEMINI_API_KEY) ; sinon detection classique (OpenCV)
DETECTION_IA = env_bool("DETECTION_IA", True)

# photos de drone / telephone : gardees en memoire jusqu'a 20 Mo (pas de fichier temporaire)
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Apps du projet (1 app = 1 bloc)
    "core",
    "diagnostics",   # bloc 1
    "advisor",       # bloc 2
    "irrigation",    # bloc 3
    "passport",      # bloc 4
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.ui",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"  # interface en anglais (textes dans core/strings.py)
TIME_ZONE = "Africa/Tunis"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
