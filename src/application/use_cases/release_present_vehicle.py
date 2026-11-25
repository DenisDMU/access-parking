"""Use case `ReleasePresentVehicle` — sortie forcée par l'exploitation.

Access ne conserve aucune plaque : un véhicule resté « présent » ne peut
normalement sortir que par la borne, avec sa plaque. Or il arrive qu'un
véhicule parte sans passer par la borne (barrière ouverte à la main, panne,
véhicules de test). L'exploitant peut alors le **libérer par son identifiant
pseudonymisé**, depuis le dashboard :

1. la place est rendue à Parking (`mark_place_free`) ;
2. la présence passe à « sorti » ;
3. une demande de sortie et sa décision sont tracées, avec un motif
   explicite (audit) ;
4. l'événement `VEHICLE_EXITED` est publié, marqué `forced: true`, montant 0.

Aucun appel à Vehicles, Pricing ni Payment : rien n'est facturé. Si Parking
ne répond pas, la présence est quand même libérée côté Access (c'est le but
de l'action) et `place_freed` vaut `False` pour que l'exploitant le sache.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from src.application.use_cases.process_exit_request import _stay_minutes
from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.event_publisher_port import EventPublisherPort
from src.domain.ports.parking_service_port import ParkingServicePort
from src.domain.ports.vehicle_presence_repository_port import VehiclePresenceRepositoryPort
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    EventType,
    PresenceStatus,
    RequestStatus,
    RequestType,
)

logger = logging.getLogger(__name__)

FORCED_EXIT_REASON = "Sortie forcée par l'exploitation (sans plaque ni paiement)"


@dataclass(frozen=True)
class ReleaseResult:
    request_id: str
    vehicle_id: str
    place_id: str | None
    place_freed: bool | None  # None : aucune place connue pour ce véhicule


class ReleasePresentVehicle:
    def __init__(
        self,
        parking_port: ParkingServicePort,
        presence_repo: VehiclePresenceRepositoryPort,
        access_repo: AccessRepositoryPort,
        event_publisher: EventPublisherPort,
    ) -> None:
        self._parking_port = parking_port
        self._presence_repo = presence_repo
        self._access_repo = access_repo
        self._event_publisher = event_publisher

    def execute(self, vehicle_id: str, date: datetime) -> ReleaseResult | None:
        """`None` si ce véhicule n'est pas présent (rien n'est modifié)."""

        if self._presence_repo.get_status(vehicle_id) is not PresenceStatus.IN:
            return None

        entry_request_id = self._presence_repo.get_current_request_id(vehicle_id)
        entry_request = (
            self._access_repo.get_request(entry_request_id) if entry_request_id else None
        )
        entry_event = (
            self._access_repo.get_event_by_request(entry_request_id) if entry_request_id else None
        )
        entry_date = entry_request.date if entry_request else date
        place_id = entry_event.payload.get("placeId") if entry_event else None

        place_freed = self._parking_port.mark_place_free(place_id) if place_id else None
        self._presence_repo.set_status(vehicle_id, PresenceStatus.OUT, None)

        request_id = str(uuid4())
        self._access_repo.save_request(
            AccessRequest(
                id=request_id,
                type=RequestType.EXIT,
                date=date,
                source=DetectionSource.TERMINAL,
                status=RequestStatus.PROCESSED,
                vehicle_id=vehicle_id,
            )
        )
        self._access_repo.save_authorization(
            AccessAuthorization(
                id=str(uuid4()),
                request_id=request_id,
                result=AuthorizationResult.AUTHORIZED,
                reason=FORCED_EXIT_REASON,
            )
        )
        logger.info(
            "Sortie forcée par l'exploitation (request=%s, vehicle=%s, place=%s, rendue=%s)",
            request_id,
            vehicle_id,
            place_id,
            place_freed,
        )
        self._event_publisher.publish(
            AccessEvent(
                id=str(uuid4()),
                type=EventType.VEHICLE_EXITED,
                request_id=request_id,
                payload={
                    "vehicleId": vehicle_id,
                    "placeId": place_id,
                    "amount": "0",
                    "paymentId": None,
                    "enteredAt": entry_date.isoformat(),
                    "durationMinutes": _stay_minutes(entry_date, date),
                    "forced": True,
                },
                created_at=date,
            )
        )
        return ReleaseResult(
            request_id=request_id,
            vehicle_id=vehicle_id,
            place_id=place_id,
            place_freed=place_freed,
        )
