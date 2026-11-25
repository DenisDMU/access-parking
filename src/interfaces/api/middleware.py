"""Middleware HTTP transverse : correlation ID + log d'accès.

Pour chaque requête :

1. reprend l'en-tête `X-Correlation-ID` s'il est fourni et bien formé
   (identifiant technique opaque : lettres, chiffres, `.`, `_`, `-`, 64
   caractères max — tout le reste est ignoré pour éviter l'injection dans
   les logs), sinon en génère un (UUID4) ;
2. le rend disponible à tous les logs de la requête (`[cid=...]`) ;
3. le renvoie dans l'en-tête de réponse `X-Correlation-ID` ;
4. écrit une ligne de log d'accès : méthode, route, code HTTP, durée.

Niveau du log d'accès, pour garder des logs lisibles en production :
- INFO : toute écriture (`POST /access/requests` = un passage à la borne) ;
- WARNING : toute réponse en erreur (4xx/5xx) ;
- DEBUG : lectures réussies (`GET`, dont le polling du dashboard toutes les
  3 s), `/health`, `/metrics` et `/static/*` — visibles avec `LOG_LEVEL=DEBUG`.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import Request, Response

from src.infrastructure.logging_config import correlation_id_var

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# La promenade multijoueur envoie une position plusieurs fois par seconde et
# par visiteur, et Prometheus lit `/metrics` toutes les 15 s : ils noieraient
# le journal. Une lecture refusée (401) reste loggée en avertissement.
_QUIET_PREFIXES = ("/health", "/metrics", "/static", "/favicon.ico", "/api/v1/borne/promenade")

logger = logging.getLogger("access.http")


def resolve_correlation_id(raw: str | None) -> str:
    if raw and _VALID_CORRELATION_ID.match(raw):
        return raw
    return str(uuid.uuid4())


def _access_log_level(method: str, path: str, status_code: int) -> int:
    if status_code >= 400:
        return logging.WARNING
    if path.startswith(_QUIET_PREFIXES) or method in ("GET", "HEAD", "OPTIONS"):
        return logging.DEBUG
    return logging.INFO


async def correlation_id_middleware(request: Request, call_next) -> Response:
    correlation_id = resolve_correlation_id(request.headers.get(CORRELATION_HEADER))
    correlation_id_var.set(correlation_id)
    started = time.perf_counter()
    path = request.url.path

    try:
        response = await call_next(request)
    except Exception:
        # L'erreur elle-même est loggée (avec sa stack) par le handler global
        # de main.py, qui renvoie un 500 générique portant ce même cid.
        logger.warning(
            "%s %s -> 500 (%.0f ms)",
            request.method,
            path,
            (time.perf_counter() - started) * 1000,
        )
        raise

    response.headers[CORRELATION_HEADER] = correlation_id
    logger.log(
        _access_log_level(request.method, path, response.status_code),
        "%s %s -> %s (%.0f ms)",
        request.method,
        path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


# En-têtes de sécurité HTTP (jalon 15) — ajoutés à toutes les réponses.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",  # pas d'interprétation d'un JSON en HTML/JS
    "X-Frame-Options": "DENY",  # dashboard non intégrable dans une iframe (clickjacking)
    "Referrer-Policy": "no-referrer",
}


async def security_headers_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/api/"):
        # Données d'accès : jamais mises en cache par un navigateur ou un proxy.
        response.headers.setdefault("Cache-Control", "no-store")
    if request.headers.get("x-forwarded-proto") == "https":
        # Derrière le proxy HTTPS de Render : impose HTTPS au navigateur.
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response
