"""Authentification par clé API (`X-API-Key`) — section 11 de la spec, jalon 15.

Trois niveaux :

- `API_KEY` (exploitation) : accès à toutes les routes.
- `BORNE_API_KEY` (bornes client, écran public) : accès au seul passage d'un
  véhicule (`POST /access/requests`, via `verify_passage_key`) et à la
  validation PMR de la borne (`is_passage_key`). Une borne
  volée ou inspectée ne donne donc accès ni à l'historique, ni aux
  présences, ni aux événements, ni aux métriques.
- `METRICS_TOKEN` (supervision) : lecture de `GET /metrics` seulement (via
  `verify_metrics_key`), pour le Prometheus qui surveille Access. Il ne donne
  accès à aucune autre route, et la clé borne ne lit pas les métriques.

- Comparaison en **temps constant** (`hmac.compare_digest`) : le temps de
  réponse ne révèle pas combien de caractères de la clé sont corrects.
- Ne jamais logger la clé API fournie, valide ou non.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from src.infrastructure.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)


def _matches(provided: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Clé API manquante ou invalide",
    )


def verify_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """Clé d'exploitation uniquement."""

    if not api_key or not _matches(api_key, get_settings().api_key):
        raise _unauthorized()
    return api_key


def verify_passage_key(api_key: str | None = Security(_api_key_header)) -> str:
    """Clé d'exploitation ou clé borne : réservé au passage d'un véhicule."""

    settings = get_settings()
    if not api_key:
        raise _unauthorized()
    # Les deux comparaisons sont toujours faites (pas de court-circuit) :
    # le temps de réponse ne dit pas quelle clé a été essayée.
    is_admin = _matches(api_key, settings.api_key)
    is_borne = _matches(api_key, settings.borne_api_key)
    if not (is_admin or is_borne):
        raise _unauthorized()
    return api_key


def is_passage_key(api_key: str | None) -> bool:
    """Vrai si la clé fournie est celle d'exploitation ou celle des bornes.

    Pour les routes de la borne qui acceptent une clé sans l'exiger toujours
    (validation PMR : clé exigée dès que le passage public est fermé).
    """

    if not api_key:
        return False
    settings = get_settings()
    # Les deux comparaisons sont toujours faites (pas de court-circuit).
    is_admin = _matches(api_key, settings.api_key)
    is_borne = _matches(api_key, settings.borne_api_key)
    return is_admin or is_borne


def verify_metrics_key(
    api_key: str | None = Security(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    """Clé d'exploitation ou jeton de lecture des métriques : réservé à `/metrics`.

    Présenté dans `X-API-Key`, ou dans `Authorization: Bearer …` (le réglage
    `authorization` de Prometheus, toutes versions).
    """

    settings = get_settings()
    provided = api_key or (bearer.credentials if bearer else "")
    if not provided:
        raise _unauthorized()
    # Les deux comparaisons sont toujours faites (pas de court-circuit).
    is_admin = _matches(provided, settings.api_key)
    is_reader = _matches(provided, settings.metrics_token)
    if not (is_admin or is_reader):
        raise _unauthorized()
    return provided
