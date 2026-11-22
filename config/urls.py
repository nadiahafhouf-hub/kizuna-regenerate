from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from diagnostics import views as diagnostics_views
from energy import views as energy_views
from passport import views as passport_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    # Bloc 1 : l'agriculteur crée sa parcelle (dimensions + coin nord-ouest)
    path("parcels/new/", diagnostics_views.new_parcel, name="new_parcel"),
    # Parcours par parcelle : 1 Diagnostic → 2 Crops → 3 Irrigation → 4 Passport
    path("p/<str:pid>/diagnostic/", include("diagnostics.urls")),
    path("p/<str:pid>/crops/", include("advisor.urls")),
    path("p/<str:pid>/irrigation/", include("irrigation.urls")),
    path("p/<str:pid>/solar/", include("energy.urls")),
    path("p/<str:pid>/passport/", include("passport.urls")),
    # ESP32 : mesures de production photovoltaïque
    path("api/energy/<str:pid>/readings/", energy_views.api_mesures, name="energy_api"),
    # Page publique de vérification (cible du QR code)
    path("verify/<str:passport_id>/", passport_views.verify, name="verify"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
