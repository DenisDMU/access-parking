"""Règle de présence (section 5 de la spec).

- Un véhicule déjà présent (`IN`) ne peut pas entrer une seconde fois.
- Un véhicule non présent (`OUT` ou inconnu, i.e. `None`) ne peut pas sortir.
"""

from __future__ import annotations

from src.domain.value_objects.enums import PresenceStatus


def can_enter(current_status: PresenceStatus | None) -> bool:
    """Un véhicule peut entrer s'il n'est pas déjà marqué `IN`."""

    return current_status is not PresenceStatus.IN


def can_exit(current_status: PresenceStatus | None) -> bool:
    """Un véhicule ne peut sortir que s'il est actuellement `IN`."""

    return current_status is PresenceStatus.IN
