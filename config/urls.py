from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from passport import views as passport_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("diagnostics/", include("diagnostics.urls")),
    path("advisor/", include("advisor.urls")),
    path("irrigation/", include("irrigation.urls")),
    path("passport/", include("passport.urls")),
    # Page publique de vérification (cible du QR code)
    path("verify/<int:passport_id>/", passport_views.verify, name="verify"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
