"""Port de persistance de la présence véhicule (table technique interne).

Note (écart mineur assumé — voir README) : `get_current_request_id` a été
ajoutée en complément de `get_status` afin de pouvoir retrouver, à la
sortie, la demande d'entrée en cours (`current_request_id`) sans changer la
signature de `get_status` fixée par la spec. `list_present` (lecture seule)
alimente la vue "véhicules présents" du dashboard d'exploitation.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.entities.vehicle_presence import VehiclePresence
from src.domain.value_objects.enums import PresenceStatus


class VehiclePresenceRepositoryPort(Protocol):
    def get_status(self, vehicle_id: str) -> PresenceStatus | None:
        """`None` si le véhicule n'a jamais été vu (équivalent à OUT)."""
        ...

    def get_current_request_id(self, vehicle_id: str) -> str | None: ...

    def set_status(
        self,
        vehicle_id: str,
        status: PresenceStatus,
        request_id: str | None,
    ) -> None: ...

    def list_present(self) -> list[VehiclePresence]:
        """Véhicules actuellement `IN`, les plus récemment entrés d'abord."""
        ...
