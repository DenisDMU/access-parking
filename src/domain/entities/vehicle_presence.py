"""Entité technique *VehiclePresence*, interne à Access (cf. section 3.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.value_objects.enums import PresenceStatus


@dataclass
class VehiclePresence:
    """Cache d'état dérivé du propre historique de décisions d'Access.

    Permet d'appliquer la règle "un véhicule déjà présent ne peut pas entrer
    une seconde fois" sans posséder de donnée métier d'un autre service.
    """

    vehicule_id: str
    statut: PresenceStatus
    updated_at: datetime
    demande_id_courante: str | None = None
