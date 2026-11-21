from django.shortcuts import render

from core.views import journey_context


def index(request, pid):
    return render(request, "partials/page_placeholder.html", journey_context(pid, "irrigation"))
