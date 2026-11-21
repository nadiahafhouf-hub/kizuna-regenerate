import base64

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from core.views import journey_context
from services import demo_data
from services.passport_generator import generate_passport_pdf, generate_qr_for_url

EVENT_ICONS = {"DIAGNOSTIC": "scan-search", "PLANTING": "sprout", "IRRIGATION": "droplets", "ANALYSIS": "flask-conical"}


def _verify_url(request, passport_id):
    return request.build_absolute_uri(reverse("verify", args=[passport_id]))


def index(request, pid):
    ctx = journey_context(pid, "passport")
    pp = demo_data.passport(pid)
    verify_url = _verify_url(request, pp["id"])
    qr = base64.b64encode(generate_qr_for_url(verify_url)).decode("ascii")
    for ev in pp["events"]:
        ev["icon"] = EVENT_ICONS.get(ev["type"], "circle")
    ctx.update({
        "pp": pp,
        "qr_data_uri": f"data:image/png;base64,{qr}",
        "verify_url": verify_url,
        "tampered_url": reverse("verify", args=[pp["id"] + "-T"]),
    })
    return render(request, "passport/passport.html", ctx)


def pdf(request, pid):
    """PDF du passeport (services/passport_generator.py, repris de l'ancien projet)."""
    pp = demo_data.passport(pid)
    qr = generate_qr_for_url(_verify_url(request, pp["id"]))
    content = generate_passport_pdf(pp["id"], demo_data.passport_pdf_input(pid), pp["parcel"]["farmer"], qr)
    resp = HttpResponse(content, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="soil-passport-{pp["id"]}.pdf"'
    return resp


def verify(request, passport_id):
    """Page publique (cible du QR) lisible par un acheteur non technicien."""
    pp = demo_data.passport_by_id(passport_id)
    for ev in pp["events"]:
        ev["icon"] = EVENT_ICONS.get(ev["type"], "circle")
    return render(request, "passport/verify.html", {"pp": pp})
