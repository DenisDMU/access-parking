"""Entité *Événement d'accès* (objet métier officiel du cadrage).

Nommée `AccessEvent` en anglais ; correspond à l'"Événement d'accès" de la
spec FR (table `access_events`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.value_objects.enums import EventType


@dataclass
class AccessEvent:
    """Un événement produit par Access, journalisé puis diffusé (fan-out).

    `payload` utilise exclusivement `vehicleId` (pseudonymisé) — jamais la
    plaque brute (cf. section 6/11 de la spec).
    """

    id: str
    type: EventType
    request_id: str
    payload: dict
    created_at: datetime
