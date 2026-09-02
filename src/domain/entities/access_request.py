"""Entité *Demande d'accès* (objet métier officiel du cadrage).

Nommée `AccessRequest` en anglais (identifiants de code) ; correspond à la
"Demande d'accès" de la spec FR (table `access_requests`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.value_objects.enums import DetectionSource, RequestStatus, RequestType


@dataclass
class AccessRequest:
    """Une demande d'entrée ou de sortie formulée par/pour un véhicule.

    `vehicle_id` est `None` tant que le véhicule n'a pas été résolu par
    Vehicles (ou reste `None` définitivement s'il est inconnu). Il ne
    contient **jamais** la plaque brute — voir section 6/8 de la spec.
    """

    id: str
    type: RequestType
    date: datetime
    source: DetectionSource
    status: RequestStatus
    vehicle_id: str | None = None
    ai_check: dict | None = None
