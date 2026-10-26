"""Identidade local: recortes da mesma ilustração oficial, sem filtros de cor."""
import base64
from functools import lru_cache
from .data import ASSETS


@lru_cache(maxsize=8)
def asset_uri(name):
    path = ASSETS / name
    mime = {".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png"}[path.suffix]
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def brand_html(sidebar=False):
    return (
        f'<div class="brand {"brand-sidebar" if sidebar else "brand-header"}">'
        f'<img src="{asset_uri("lampiadim_avatar.svg")}" alt="Lampiadim, gênio azul com chapéu de cangaço e óculos" width="58" height="58">'
        '<div class="brand-type"><div class="wordmark">lampiadim<span>.</span></div>'
        '<div class="brand-sub">Inteligência eleitoral brasileira</div></div></div>'
    )
