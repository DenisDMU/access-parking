"""Use case `ListPresentVehicles` — état courant du parking vu par Access.

Vue d'exploitation (dashboard, jalon "UI") : quels véhicules sont
actuellement entrés, depuis quand, sur quelle place. Tout est reconstruit à
partir des propres données d'Access (présence `IN` + demande d'entrée +
payload de l'événement `VEHICLE_ENTERED`), sans appeler d'autre service.
"""

from __future__ import annotations

from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.vehicle_presence_repository_port import (
    VehiclePresenceRepositoryPort,
)
from src.domain.value_objects.dto import PlaceType, PresentVehicle
from src.domain.value_objects.enums import VehicleCategory


def _place_type_from_payload(data: dict | None) -> PlaceType | None:
    if not data:
        return None
    return PlaceType(
        category=VehicleCategory(data.get("category", VehicleCategory.FOUR_WHEELER)),
        is_xl=bool(data.get("isXl", False)),
        is_electric=bool(data.get("isElectric", False)),
        is_handicap=bool(data.get("isHandicap", False)),
    )


class ListPresentVehicles:
    def __init__(
        self,
        presence_repo: VehiclePresenceRepositoryPort,
        access_repo: AccessRepositoryPort,
    ) -> None:
        self._presence_repo = presence_repo
        self._access_repo = access_repo

    def execute(self) -> list[PresentVehicle]:
        result: list[PresentVehicle] = []
        for presence in self._presence_repo.list_present():
            request_id = presence.current_request_id
            entry_request = self._access_repo.get_request(request_id) if request_id else None
            entry_event = self._access_repo.get_event_by_request(request_id) if request_id else None
            payload = entry_event.payload if entry_event else {}
            result.append(
                PresentVehicle(
                    vehicle_id=presence.vehicle_id,
                    entry_request_id=request_id,
                    entered_at=entry_request.date if entry_request else None,
                    place_id=payload.get("placeId"),
                    place_type=_place_type_from_payload(payload.get("placeType")),
                    is_reservation=bool(payload.get("reservation", False)),
                )
            )
        # Plus récemment entrés d'abord ; véhicules sans date connue à la fin.
        result.sort(key=lambda v: (v.entered_at is not None, v.entered_at), reverse=True)
        return result
