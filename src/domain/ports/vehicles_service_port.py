"""Port vers le service Vehicles.

⚠️ Seul port qui reçoit la plaque en clair, et uniquement pour résolution.
Le use case appelant ne doit conserver AUCUNE référence à la plaque brute
après cet appel (cf. section 6/7/11 de la spec).
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.dto import VehicleInfo


class VehiclesServicePort(Protocol):
    def get_vehicle_info(self, raw_plate: str) -> VehicleInfo | None:
        """Résout une plaque brute en identité pseudonymisée, ou `None` si inconnue."""
        ...
