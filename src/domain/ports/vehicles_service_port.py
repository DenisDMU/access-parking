"""Port vers le service Vehicles.

Access ne reçoit jamais la plaque : c'est Vehicles qui l'identifie et
l'associe à un `code` véhicule. Access consulte uniquement la donnée
anonymisée correspondant à ce code (identifiant pseudonymisé +
caractéristiques du véhicule).
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.dto import VehicleInfo


class VehiclesServicePort(Protocol):
    def get_vehicle_info(self, vehicle_code: int) -> VehicleInfo | None:
        """Résout un code véhicule en identité pseudonymisée, ou `None` si inconnu."""
        ...
