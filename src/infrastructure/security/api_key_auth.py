"""Authentification par clé API (`X-API-Key`) — section 11 de la spec, jalon 15.

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


def verify_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    settings = get_settings()
    if not api_key or not hmac.compare_digest(
        api_key.encode("utf-8"), settings.api_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé API manquante ou invalide",
        )
    return api_key
