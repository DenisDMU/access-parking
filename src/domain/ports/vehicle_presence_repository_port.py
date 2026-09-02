"""Port de persistance de la présence véhicule (table technique interne).

Note (écart mineur assumé — voir README) : `get_current_demande_id` a été
ajoutée en complément de `get_status` afin de pouvoir retrouver, à la
sortie, la demande d'entrée en cours (`demande_id_courante`) sans changer la
signature de `get_status` fixée par la spec.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.enums import PresenceStatus


class VehiclePresenceRepositoryPort(Protocol):
    def get_status(self, vehicule_id: str) -> PresenceStatus | None:
        """`None` si le véhicule n'a jamais été vu (équivalent à OUT)."""
        ...

    def get_current_demande_id(self, vehicule_id: str) -> str | None: ...

    def set_status(
        self,
        vehicule_id: str,
        status: PresenceStatus,
        demande_id: str | None,
    ) -> None: ...
