"""Limiter partagé (slowapi) — module séparé pour éviter tout import
circulaire entre `main.py` (qui l'attache à `app.state`) et les routers (qui
l'utilisent comme décorateur)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

limiter = Limiter(key_func=get_remote_address)


def client_ip(request: Request) -> str:
    """Adresse du client derrière le proxy de Render.

    Sans cela, toutes les requêtes semblent venir du proxy et partagent la
    même limite. On prend la DERNIÈRE adresse de `X-Forwarded-For` : celle
    ajoutée par le proxy de Render (les précédentes peuvent être inventées
    par le client pour contourner la limite).
    """

    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    return hops[-1] if hops else get_remote_address(request)
