"""Use case `ProcessExitRequest` — workflow "Sortie".

Déroulé (section 8 de la spec) :
1. Résolution Vehicles (seul endroit où la plaque brute est utilisée).
2. Création de la demande d'accès (EXIT).
3. Règle de présence → refus si le véhicule n'est pas `IN`.
4. Récupération du stationnement en cours (demande d'entrée associée).
5. Calcul du prix (Pricing).
6. Paiement (Payment) → refus si échec.
7. Autorisation, libération de la place.
8. Mise à jour de la présence (`OUT`).
9-11. Persistance + publication de l'événement + retour de la décision.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.parking_service_port import ParkingServicePort
from src.domain.ports.payment_service_port import PaymentServicePort
from src.domain.ports.pricing_service_port import PricingServicePort
from src.domain.ports.vehicle_presence_repository_port import (
    VehiclePresenceRepositoryPort,
)
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.domain.rules.presence_rule import can_exit
from src.domain.value_objects.dto import ExitDecision, PlaceType
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    EventType,
    PresenceStatus,
    RequestStatus,
    RequestType,
    VehicleCategory,
)


def _place_type_from_payload(payload: dict | None) -> PlaceType:
    """Reconstruit le `PlaceType` attribué à l'entrée depuis le payload de
    l'événement `VEHICLE_ENTERED` (le schéma SQL officiel ne persiste pas de
    colonne place/place_type dédiée — voir README, section "Écarts assumés
    par rapport à la spec")."""

    data = (payload or {}).get("placeType") or {}
    return PlaceType(
        category=VehicleCategory(data.get("category", VehicleCategory.FOUR_WHEELER)),
        is_xl=bool(data.get("isXl", False)),
        is_electric=bool(data.get("isElectric", False)),
        is_handicap=bool(data.get("isHandicap", False)),
    )


class ProcessExitRequest:
    def __init__(
        self,
        vehicles_port: VehiclesServicePort,
        parking_port: ParkingServicePort,
        pricing_port: PricingServicePort,
        payment_port: PaymentServicePort,
        presence_repo: VehiclePresenceRepositoryPort,
        access_repo: AccessRepositoryPort,
        event_publisher,
    ) -> None:
        self._vehicles_port = vehicles_port
        self._parking_port = parking_port
        self._pricing_port = pricing_port
        self._payment_port = payment_port
        self._presence_repo = presence_repo
        self._access_repo = access_repo
        self._event_publisher = event_publisher

    def execute(
        self,
        plate: str,
        date: datetime,
        source: DetectionSource,
    ) -> ExitDecision:
        request_id = str(uuid4())

        # Seul endroit de toute la codebase où la plaque brute est utilisée.
        vehicle_info = self._vehicles_port.get_vehicle_info(plate)
        del plate  # ne doit plus jamais être référencée ci-dessous

        if vehicle_info is None:
            return self._reject_unknown_vehicle(request_id, date, source)

        vehicle_id = vehicle_info.vehicle_id

        presence_status = self._presence_repo.get_status(vehicle_id)
        if not can_exit(presence_status):
            return self._refuse(
                request_id=request_id,
                vehicle_id=vehicle_id,
                date=date,
                source=source,
                reason="Véhicule non présent dans le parking",
            )

        current_request_id = self._presence_repo.get_current_request_id(vehicle_id)
        entry_request = (
            self._access_repo.get_request(current_request_id)
            if current_request_id
            else None
        )
        entry_event = (
            self._access_repo.get_event_by_request(current_request_id)
            if current_request_id
            else None
        )
        entry_date = entry_request.date if entry_request else date
        place_id = entry_event.payload.get("placeId") if entry_event else None
        place_type = _place_type_from_payload(entry_event.payload if entry_event else None)
        is_reservation = bool(entry_event.payload.get("reservation", False)) if entry_event else False

        amount = self._pricing_port.calculate_price(
            vehicle_id, entry_date, date, place_type, is_reservation
        )

        payment_result = self._payment_port.request_payment(vehicle_id, amount)
        if not payment_result.success:
            return self._refuse(
                request_id=request_id,
                vehicle_id=vehicle_id,
                date=date,
                source=source,
                reason="Paiement refusé",
                amount=amount,
            )

        if place_id:
            self._parking_port.mark_place_free(place_id)
        self._presence_repo.set_status(vehicle_id, PresenceStatus.OUT, None)

        request = AccessRequest(
            id=request_id,
            type=RequestType.EXIT,
            date=date,
            source=source,
            status=RequestStatus.PROCESSED,
            vehicle_id=vehicle_id,
        )
        authorization = AccessAuthorization(
            id=str(uuid4()),
            request_id=request_id,
            result=AuthorizationResult.AUTHORIZED,
            reason="Sortie autorisée",
            payment_amount=amount,
        )
        self._access_repo.save_request(request)
        self._access_repo.save_authorization(authorization)
        self._event_publisher.publish(
            AccessEvent(
                id=str(uuid4()),
                type=EventType.VEHICLE_EXITED,
                request_id=request_id,
                payload={
                    "vehicleId": vehicle_id,
                    "placeId": place_id,
                    "amount": str(amount),
                },
                created_at=date,
            )
        )

        return ExitDecision(
            request_id=request_id,
            vehicle_id=vehicle_id,
            type=RequestType.EXIT,
            status=request.status,
            result=authorization.result,
            reason=authorization.reason,
            payment_amount=amount,
        )

    def _reject_unknown_vehicle(
        self, request_id: str, date: datetime, source: DetectionSource
    ) -> ExitDecision:
        request = AccessRequest(
            id=request_id,
            type=RequestType.EXIT,
            date=date,
            source=source,
            status=RequestStatus.REJECTED,
            vehicle_id=None,
        )
        reason = "Véhicule inconnu de Vehicles — procédure alternative requise"
        authorization = AccessAuthorization(
            id=str(uuid4()),
            request_id=request_id,
            result=AuthorizationResult.CONFIRMATION_REQUIRED,
            reason=reason,
        )
        self._access_repo.save_request(request)
        self._access_repo.save_authorization(authorization)
        self._event_publisher.publish(
            AccessEvent(
                id=str(uuid4()),
                type=EventType.ACCESS_REFUSED,
                request_id=request_id,
                payload={"vehicleId": None, "reason": reason},
                created_at=date,
            )
        )
        return ExitDecision(
            request_id=request_id,
            vehicle_id=None,
            type=RequestType.EXIT,
            status=request.status,
            result=authorization.result,
            reason=reason,
        )

    def _refuse(
        self,
        *,
        request_id: str,
        vehicle_id: str,
        date: datetime,
        source: DetectionSource,
        reason: str,
        amount=None,
    ) -> ExitDecision:
        request = AccessRequest(
            id=request_id,
            type=RequestType.EXIT,
            date=date,
            source=source,
            status=RequestStatus.PROCESSED,
            vehicle_id=vehicle_id,
        )
        authorization = AccessAuthorization(
            id=str(uuid4()),
            request_id=request_id,
            result=AuthorizationResult.REFUSED,
            reason=reason,
            payment_amount=amount,
        )
        self._access_repo.save_request(request)
        self._access_repo.save_authorization(authorization)
        self._event_publisher.publish(
            AccessEvent(
                id=str(uuid4()),
                type=EventType.ACCESS_REFUSED,
                request_id=request_id,
                payload={"vehicleId": vehicle_id, "reason": reason},
                created_at=date,
            )
        )
        return ExitDecision(
            request_id=request_id,
            vehicle_id=vehicle_id,
            type=RequestType.EXIT,
            status=request.status,
            result=authorization.result,
            reason=reason,
            payment_amount=amount,
        )
