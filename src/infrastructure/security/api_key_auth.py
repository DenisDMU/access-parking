"""Authentification par clé API (`X-API-Key`) — section 11 de la spec, jalon 15.

Deux niveaux :

- `API_KEY` (exploitation) : accès à toutes les routes.
- `BORNE_API_KEY` (bornes client, écran public) : accès au seul passage d'un
  véhicule (`POST /access/requests`, via `verify_passage_key`). Une borne
  volée ou inspectée ne donne donc accès ni à l'historique, ni aux
  présences, ni aux événements, ni aux métriques.

- Comparaison en **temps constant** (`hmac.compare_digest`) : le temps de
  réponse ne révèle pas combien de caractères de la clé sont corrects.
- Ne jamais logger la clé API fournie, valide ou non.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.infrastructure.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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
