"""Limiter partagé (slowapi) — module séparé pour éviter tout import
circulaire entre `main.py` (qui l'attache à `app.state`) et les routers (qui
l'utilisent comme décorateur)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
