"""Petits outils de templates partagés : {% load ui %}."""
from django import template

from core.strings import get_labels, get_strings

register = template.Library()

# Apparence des zones : TOUJOURS icône + libellé, jamais la couleur seule.
ZONE_UI = {
    "ROUGE": {"icon": "octagon-alert", "solid": "bg-zred text-white",
              "soft": "bg-zred-bg text-zred ring-1 ring-inset ring-zred/25", "hex": "#B83227"},
    "ORANGE": {"icon": "triangle-alert", "solid": "bg-zorange text-white",
               "soft": "bg-zorange-bg text-zorange ring-1 ring-inset ring-zorange/25", "hex": "#B85C0E"},
    "VERT": {"icon": "circle-check", "solid": "bg-zgreen text-white",
             "soft": "bg-zgreen-bg text-zgreen ring-1 ring-inset ring-zgreen/25", "hex": "#23774A"},
}


@register.filter
def get(mapping, key):
    """{{ dict|get:key }} — accès dynamique à une clé."""
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""


@register.filter
def label(value):
    """Valeur du contrat (française) → libellé affiché."""
    return get_labels().get(value, value)


@register.filter
def short_hash(value, n=8):
    return f"{str(value)[:int(n)]}…" if value else ""


@register.filter
def num(value, decimals=0):
    """1234.5 → « 1,235 » (ou décimales)."""
    try:
        return f"{float(value):,.{int(decimals)}f}"
    except (TypeError, ValueError):
        return value


@register.filter
def zone_ui(color, attr):
    return ZONE_UI.get(color, ZONE_UI["VERT"]).get(attr, "")


@register.inclusion_tag("components/zone_badge.html")
def zone_badge(color, variant="soft", size="md", long=False):
    """{% zone_badge "ROUGE" %} · variant soft|solid · size sm|md|lg · long=True → « Red · Contaminated »."""
    z = get_strings()["zone"].get(color, {})
    return {"color": color, "ui": ZONE_UI.get(color, ZONE_UI["VERT"]), "variant": variant,
            "size": size, "label": z.get("label", color), "long": z.get("long", "") if long else ""}
