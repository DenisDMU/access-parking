"""Use case `ProcessEntryRequest` — workflow "Entrée" + "Réservation".

Orchestration pure : ne dépend que des ports du domaine (aucune dépendance
vers `infrastructure`/`interfaces`), conformément à la règle de dépendance
stricte de l'architecture hexagonale.

Déroulé (section 8 de la spec) :
1. Réceptionner la plaque brute (valeur volatile, locale à cette méthode).
2. Analyse IA optionnelle (photo) → `ai_check`.
3. Résolution Vehicles (seul endroit où la plaque brute est utilisée).
4. Véhicule inconnu → rejet journalisé sans plaque, `stop`.
5. Règle de présence → refus si déjà `IN`.
6. Réservation (Booking) sinon attribution de place (Parking).
7. Règle de compatibilité véhicule/place → refus si incompatible.
8. Règle d'accessibilité (PMR) → confirmation requise si justificatif manquant.
9. Sinon autorisation, occupation de la place, mise à jour de la présence.
10-13. Persistance + publication de l'événement + retour de la décision.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.ai_vision_port import AIVisionPort
from src.domain.ports.booking_service_port import BookingServicePort
from src.domain.ports.event_publisher_port import EventPublisherPort
from src.domain.ports.parking_service_port import ParkingServicePort
from src.domain.ports.vehicle_presence_repository_port import (
    VehiclePresenceRepositoryPort,
)
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.domain.rules.disability_rule import requires_disability_confirmation
from src.domain.rules.presence_rule import can_enter
from src.domain.rules.vehicle_place_compatibility_rule import is_compatible
from src.domain.value_objects.dto import EntryDecision, PlaceType
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    EventType,
    PresenceStatus,
    RequestStatus,
    RequestType,
)


def _place_type_to_payload(place_type: PlaceType) -> dict:
    return {
        "category": int(place_type.category),
        "isXl": place_type.is_xl,
        "isElectric": place_type.is_electric,
        "isHandicap": place_type.is_handicap,
    }


class ProcessEntryRequest:
    def __init__(
        self,
        vehicles_port: VehiclesServicePort,
        booking_port: BookingServicePort,
        parking_port: ParkingServicePort,
        presence_repo: VehiclePresenceRepositoryPort,
        access_repo: AccessRepositoryPort,
        event_publisher: EventPublisherPort,
        ai_vision_port: AIVisionPort,
    ) -> None:
        self._vehicles_port = vehicles_port
        self._booking_port = booking_port
        self._parking_port = parking_port
        self._presence_repo = presence_repo
        self._access_repo = access_repo
        self._event_publisher = event_publisher
        self._ai_vision_port = ai_vision_port

    def execute(
        self,
        plate: str,
        date: datetime,
        source: DetectionSource,
        photo: bytes | None = None,
    ) -> EntryDecision:
        request_id = str(uuid4())

        ai_check: dict | None = None
        if photo is not None:
            ai_result = self._ai_vision_port.analyze(photo)
            ai_check = {
                "aiModel": ai_result.ai_model,
                "confidence": ai_result.confidence,
                "timestamp": ai_result.timestamp.isoformat(),
            }

        # Seul endroit de toute la codebase où la plaque brute est utilisée.
        vehicle_info = self._vehicles_port.get_vehicle_info(plate)
        del plate  # ne doit plus jamais être référencée ci-dessous

        if vehicle_info is None:
            return self._reject_unknown_vehicle(request_id, date, source, ai_check)

        vehicle_id = vehicle_info.vehicle_id

        presence_status = self._presence_repo.get_status(vehicle_id)
        if not can_enter(presence_status):
            return self._refuse(
                request_id=request_id,
                vehicle_id=vehicle_id,
                date=date,
                source=source,
                ai_check=ai_check,
                reason="Véhicule déjà présent dans le parking",
            )

        reservation = self._booking_port.get_reservation(vehicle_id)
        is_reservation = reservation is not None
        if reservation is not None:
            place_type = reservation.reserved_place_type
            place_id = reservation.place_id
            if place_id is None:
                assignment = self._parking_port.request_place(vehicle_info.vehicle_type)
                if assignment is None:
                    return self._refuse(
                        request_id=request_id,
                        vehicle_id=vehicle_id,
                        date=date,
                        source=source,
                        ai_check=ai_check,
                        reason="Réservation trouvée mais aucune place disponible",
                    )
                place_id, place_type = assignment.place_id, assignment.place_type
        else:
            assignment = self._parking_port.request_place(vehicle_info.vehicle_type)
            if assignment is None:
                return self._refuse(
                    request_id=request_id,
                    vehicle_id=vehicle_id,
                    date=date,
                    source=source,
                    ai_check=ai_check,
                    reason="Aucune place disponible",
                )
            place_id, place_type = assignment.place_id, assignment.place_type

        compat_ok = is_compatible(vehicle_info.vehicle_type, place_type)
        if not compat_ok:
            return self._refuse(
                request_id=request_id,
                vehicle_id=vehicle_id,
                date=date,
                source=source,
                ai_check=ai_check,
                reason="Type de véhicule incompatible avec la place attribuée",
                vehicle_type_check_ok=False,
            )

        if requires_disability_confirmation(place_type, vehicle_info.disability_permit):
            request = AccessRequest(
                id=request_id,
                type=RequestType.ENTRY,
                date=date,
                source=source,
                status=RequestStatus.PROCESSED,
                vehicle_id=vehicle_id,
                ai_check=ai_check,
            )
            authorization = AccessAuthorization(
                id=str(uuid4()),
                request_id=request_id,
                result=AuthorizationResult.CONFIRMATION_REQUIRED,
                reason="Justificatif d'accessibilité (PMR) requis pour une place handicapé",
                vehicle_type_check_ok=True,
                disability_check_ok=False,
            )
            self._access_repo.save_request(request)
            self._access_repo.save_authorization(authorization)
            self._event_publisher.publish(
                AccessEvent(
                    id=str(uuid4()),
                    type=EventType.OTHER,
                    request_id=request_id,
                    payload={
                        "vehicleId": vehicle_id,
                        "reason": authorization.reason,
                        "placeId": place_id,
                        "placeType": _place_type_to_payload(place_type),
                        "reservation": is_reservation,
                    },
                    created_at=date,
                )
            )
            return EntryDecision(
                request_id=request_id,
                vehicle_id=vehicle_id,
                type=RequestType.ENTRY,
                status=request.status,
                result=authorization.result,
                reason=authorization.reason,
                vehicle_type_check_ok=True,
                disability_check_ok=False,
            )

        # Tout est valide : autorisation.
        self._parking_port.mark_place_occupied(place_id, vehicle_id)
        self._presence_repo.set_status(vehicle_id, PresenceStatus.IN, request_id)

        disability_check_ok = True if place_type.is_handicap else None

        request = AccessRequest(
            id=request_id,
            type=RequestType.ENTRY,
            date=date,
            source=source,
            status=RequestStatus.PROCESSED,
            vehicle_id=vehicle_id,
            ai_check=ai_check,
        )
        authorization = AccessAuthorization(
            id=str(uuid4()),
            request_id=request_id,
            result=AuthorizationResult.AUTHORIZED,
            reason="Accès autorisé",
            vehicle_type_check_ok=True,
            disability_check_ok=disability_check_ok,
        )
        self._access_repo.save_request(request)
        self._access_repo.save_authorization(authorization)
        self._event_publisher.publish(
            AccessEvent(
                id=str(uuid4()),
                type=EventType.VEHICLE_ENTERED,
                request_id=request_id,
                payload={
                    "vehicleId": vehicle_id,
                    "placeId": place_id,
                    "placeType": _place_type_to_payload(place_type),
                    "reservation": is_reservation,
                },
                created_at=date,
            )
        )

        return EntryDecision(
            request_id=request_id,
            vehicle_id=vehicle_id,
            type=RequestType.ENTRY,
            status=request.status,
            result=authorization.result,
            reason=authorization.reason,
            vehicle_type_check_ok=True,
            disability_check_ok=disability_check_ok,
        )

    def _reject_unknown_vehicle(
        self,
        request_id: str,
        date: datetime,
        source: DetectionSource,
        ai_check: dict | None,
    ) -> EntryDecision:
        request = AccessRequest(
            id=request_id,
            type=RequestType.ENTRY,
            date=date,
            source=source,
            status=RequestStatus.REJECTED,
            vehicle_id=None,
            ai_check=ai_check,
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
        return EntryDecision(
            request_id=request_id,
            vehicle_id=None,
            type=RequestType.ENTRY,
            status=request.status,
            result=authorization.result,
            reason=reason,
            vehicle_type_check_ok=None,
            disability_check_ok=None,
        )

    def _refuse(
        self,
        *,
        request_id: str,
        vehicle_id: str,
        date: datetime,
        source: DetectionSource,
        ai_check: dict | None,
        reason: str,
        vehicle_type_check_ok: bool | None = None,
    ) -> EntryDecision:
        request = AccessRequest(
            id=request_id,
            type=RequestType.ENTRY,
            date=date,
            source=source,
            status=RequestStatus.PROCESSED,
            vehicle_id=vehicle_id,
            ai_check=ai_check,
        )
        authorization = AccessAuthorization(
            id=str(uuid4()),
            request_id=request_id,
            result=AuthorizationResult.REFUSED,
            reason=reason,
            vehicle_type_check_ok=vehicle_type_check_ok,
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
        return EntryDecision(
            request_id=request_id,
            vehicle_id=vehicle_id,
            type=RequestType.ENTRY,
            status=request.status,
            result=authorization.result,
            reason=reason,
            vehicle_type_check_ok=vehicle_type_check_ok,
            disability_check_ok=None,
        )
