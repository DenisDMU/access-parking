"""Entité *Autorisation d'accès* (objet métier officiel du cadrage).

Nommée `AccessAuthorization` en anglais ; correspond à l'"Autorisation
d'accès" de la spec FR (table `access_authorizations`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.value_objects.enums import AuthorizationResult


@dataclass
class AccessAuthorization:
    """Décision rendue pour une demande d'accès donnée."""

    id: str
    request_id: str
    result: AuthorizationResult
    reason: str | None = None
    authorization_service_ok: bool | None = None
    vehicle_type_check_ok: bool | None = None
    disability_check_ok: bool | None = None
    payment_amount: Decimal | None = None
