"""Port vers le service Parking."""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.dto import PlaceAssignment, VehicleType


class ParkingServicePort(Protocol):
    def request_place(self, vehicle_type: VehicleType) -> PlaceAssignment | None:
        """Demande l'attribution d'une place adaptée, ou `None` si aucune disponible."""
        ...

    def mark_place_occupied(self, place_id: str, vehicle_id: str) -> bool:
        """Passe la place en état occupé."""
        ...

    def mark_place_free(self, place_id: str) -> bool:
        """Libère la place."""
        ...
