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

# Chatbot (bloc 4) : base vectorielle Qdrant. Par défaut en mode embarqué (dossier local, sans serveur) ;
# QDRANT_URL (+ QDRANT_API_KEY) pour utiliser un serveur Qdrant (Docker ou Qdrant Cloud).
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_PATH = os.getenv("QDRANT_PATH") or str(BASE_DIR / "qdrant_data")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
# Offre gratuite souvent saturée (503) : le chatbot passe aussitôt au modèle suivant
GEMINI_MODELES_SECOURS = [m.strip() for m in os.getenv("GEMINI_MODELES_SECOURS",
                                                       "gemini-3.5-flash,gemini-3.1-flash-lite").split(",") if m.strip()]
# Chatbot vocal : modèle le plus rapide en priorité (~4 s mesuré sur l'offre gratuite)
GEMINI_MODEL_VOIX = os.getenv("GEMINI_MODEL_VOIX", "gemini-3.5-flash")

# Chatbot vocal en tounsi : Azure Speech (ressource « Speech » du portail Azure, offre gratuite F0).
# Reconnaissance ar-TN ; voix tunisiennes ar-TN-ReemNeural (femme) ou ar-TN-HediNeural (homme).
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "")   # ex. westeurope
AZURE_TTS_VOICE = os.getenv("AZURE_TTS_VOICE", "ar-TN-HediNeural")   # voix du chatbot (Azure ou edge-tts)
AZURE_STT_LANGUAGE = os.getenv("AZURE_STT_LANGUAGE", "ar-TN")
# Sans clé Azure : mêmes voix tunisiennes GRATUITES via edge-tts (aucun compte, aucune carte)
VOIX_EDGE_TTS = env_bool("VOIX_EDGE_TTS", True)
# Vrai accent tunisien : modèle « Lahgtna » entraîné sur la derja (Space Hugging Face AVOiD/derja-tts, GPU gratuit).
# Il imite la voix d'un enregistrement de référence (VOIX_REFERENCE + son texte exact) ; vide = généré une fois
# avec la voix edge-tts ci-dessus. Lent ou indisponible -> voix edge-tts en secours.
VOIX_LAHGTNA = env_bool("VOIX_LAHGTNA", True)
VOIX_LAHGTNA_SPACE = os.getenv("VOIX_LAHGTNA_SPACE", "AVOiD/derja-tts")
VOIX_LAHGTNA_DELAI_S = int(os.getenv("VOIX_LAHGTNA_DELAI_S", "45"))
# Jeton Hugging Face GRATUIT (compte sans carte, huggingface.co/settings/tokens, type « Read ») : sans lui,
# le quota GPU anonyme du Space est vite épuisé (« ZeroGPU runs limit ») et la voix Hedi prend le relais.
HF_TOKEN = os.getenv("HF_TOKEN", "")
VOIX_REFERENCE = os.getenv("VOIX_REFERENCE", "")
VOIX_REFERENCE_TEXTE = os.getenv("VOIX_REFERENCE_TEXTE", "")
# Texte du chatbot : « arabizi » (tounsi en lettres latines) ou « meme » (même écriture que l'agriculteur)
CHAT_ECRITURE = os.getenv("CHAT_ECRITURE", "arabizi")
# Écoute gratuite hors ligne : Whisper entraîné sur le tounsi (faster-whisper). Identifiant Hugging Face
# (téléchargé une fois, ~250 Mo) ou dossier local ; vide = désactivé.
WHISPER_DERJA_MODEL = os.getenv("WHISPER_DERJA_MODEL", "TheBiggyBang/whisper-small-tunisian-derja-ct2")

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
    "energy",        # volet photovoltaïque (dimensionnement + nettoyage des panneaux)
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
