"""Use case `ProcessEntryRequest` — workflow "Entrée" + "Réservation".

Orchestration pure : ne dépend que des ports du domaine (aucune dépendance
vers `infrastructure`/`interfaces`), conformément à la règle de dépendance
stricte de l'architecture hexagonale.

Déroulé (section 8 de la spec) :
1. Réceptionner la plaque lue par la borne (elle ne quitte pas cette
   méthode : seul l'identifiant pseudonymisé est conservé).
2. Analyse IA optionnelle (photo) → `ai_check`.
3. Identification par Vehicles, qui retrouve le véhicule ou le crée
   (règle 3.2) → identifiant pseudonymisé + type de véhicule.
4. Vehicles indisponible → rejet journalisé, `stop`.
5. Règle de présence → refus si déjà `IN`.
6. Réservation (Booking) sinon attribution de place (Parking).
7. Règle de compatibilité véhicule/place → refus si incompatible.
8. Règle d'accessibilité (PMR) → confirmation requise si justificatif manquant.
9. Sinon confirmation de la place auprès de Parking (refus si elle échoue),
   autorisation, mise à jour de la présence.
10-13. Persistance + publication de l'événement + retour de la décision.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.ai_vision_port import AIVisionPort
from src.domain.ports.booking_service_port import BookingServicePort
from src.domain.ports.event_publisher_port import EventPublisherPort
from src.domain.ports.parking_service_port import (
    ParkingCategoryUnknownError,
    ParkingServicePort,
    ParkingUnavailableError,
)
from src.domain.ports.vehicle_presence_repository_port import (
    VehiclePresenceRepositoryPort,
)
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.domain.rules.disability_rule import requires_disability_confirmation
from src.domain.rules.presence_rule import can_enter
from src.domain.rules.vehicle_place_compatibility_rule import is_compatible
from src.domain.value_objects.dto import (
    EntryDecision,
    PlaceAssignment,
    PlaceType,
    Reservation,
    VehicleType,
)
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    EventType,
    PresenceStatus,
    RequestStatus,
    RequestType,
)

# Logs métier : une ligne par décision, toujours avec l'id de la demande et
# l'identifiant pseudonymisé du véhicule (jamais de plaque, jamais de code
# Vehicles). Le correlation ID est ajouté automatiquement par le logging.
logger = logging.getLogger(__name__)


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

        ai_check = self._analyze_photo(photo)
        vehicle_info = self._vehicles_port.identify_vehicle(plate)
        del plate  # RGPD : la plaque ne sert qu'à interroger Vehicles

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
        assignment, refusal = self._assign_place(vehicle_info.vehicle_type, reservation)
        if assignment is None:
            return self._refuse(
                request_id=request_id,
                vehicle_id=vehicle_id,
                date=date,
                source=source,
                ai_check=ai_check,
                reason=refusal,
            )
        place_id, place_type, hold_id = (
            assignment.place_id,
            assignment.place_type,
            assignment.hold_id,
        )

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
            logger.info(
                "Entrée en attente de confirmation PMR (request=%s, vehicle=%s, place=%s)",
                request_id,
                vehicle_id,
                place_id,
            )
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

        # Tout est valide : on confirme la place auprès de Parking. Sans
        # confirmation (place expirée, déjà utilisée, Parking injoignable), la
        # barrière reste fermée : sinon le véhicule entrerait sans être compté.
        if not self._parking_port.mark_place_occupied(place_id, vehicle_id, hold_id):
            return self._refuse(
                request_id=request_id,
                vehicle_id=vehicle_id,
                date=date,
                source=source,
                ai_check=ai_check,
                reason="Place non confirmée par Parking, réessayez",
            )

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
        # La présence pointe vers la demande d'entrée (clé étrangère) : elle
        # n'est enregistrée qu'une fois la demande en base.
        self._presence_repo.set_status(vehicle_id, PresenceStatus.IN, request_id)
        logger.info(
            "Entrée autorisée (request=%s, vehicle=%s, place=%s, réservation=%s)",
            request_id,
            vehicle_id,
            place_id,
            is_reservation,
        )
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
            place_type=place_type,
            place_label=assignment.label,
            reservation=is_reservation,
        )

    def _analyze_photo(self, photo: bytes | None) -> dict | None:
        """Analyse IA optionnelle de la photo (jamais de plaque en clair)."""

        if photo is None:
            return None
        ai_result = self._ai_vision_port.analyze(photo)
        return {
            "aiModel": ai_result.ai_model,
            "confidence": ai_result.confidence,
            "timestamp": ai_result.timestamp.isoformat(),
        }

    def _assign_place(
        self, vehicle_type: VehicleType, reservation: Reservation | None
    ) -> tuple[PlaceAssignment | None, str | None]:
        """Place pour ce passage : `(place, None)` ou `(None, motif du refus)`.

        Avec une réservation qui fixe déjà la place, on la reprend telle
        quelle ; sinon on demande une place à Parking, dans le pool
        « booking » s'il y a une réservation, « walk-in » sinon.
        """

        if reservation is not None and reservation.place_id is not None:
            return (
                PlaceAssignment(
                    place_id=reservation.place_id, place_type=reservation.reserved_place_type
                ),
                None,
            )
        return self._request_place(vehicle_type, is_reservation=reservation is not None)

    def _request_place(
        self, vehicle_type: VehicleType, is_reservation: bool
    ) -> tuple[PlaceAssignment | None, str | None]:
        """Demande une place à Parking : `(place, None)` ou `(None, motif du refus)`.

        Distingue un parking complet d'un service Parking injoignable : le
        motif affiché au conducteur et compté dans les métriques est différent.
        """

        try:
            assignment = self._parking_port.request_place(
                vehicle_type, is_reservation=is_reservation
            )
        except ParkingUnavailableError:
            return None, "Service Parking indisponible, réessayez plus tard"
        except ParkingCategoryUnknownError as exc:
            # Parking a renommé ou supprimé une catégorie : ni une panne, ni
            # un parking complet. Motif précis pour l'exploitant.
            return None, f"Catégorie de place {exc.category} inconnue du service Parking"
        if assignment is None:
            if is_reservation:
                return None, "Réservation trouvée mais aucune place disponible"
            return None, "Aucune place disponible"
        return assignment, None

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
        reason = "Véhicule non identifié par Vehicles — procédure alternative requise"
        authorization = AccessAuthorization(
            id=str(uuid4()),
            request_id=request_id,
            result=AuthorizationResult.CONFIRMATION_REQUIRED,
            reason=reason,
        )
        self._access_repo.save_request(request)
        self._access_repo.save_authorization(authorization)
        logger.warning(
            "Entrée rejetée : véhicule non identifié par Vehicles (request=%s)", request_id
        )
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
        logger.info("Entrée refusée (request=%s, vehicle=%s) : %s", request_id, vehicle_id, reason)
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
