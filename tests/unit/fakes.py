"""Doubles de test (fakes) pour tous les ports du domaine — utilisés par les
tests unitaires des use cases (section 13 : "tous les ports mockés")."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.entities.vehicle_presence import VehiclePresence
from src.domain.ports.parking_service_port import ParkingUnavailableError
from src.domain.value_objects.dto import (
    AccessFilters,
    AICheckResult,
    PaymentResult,
    PlaceAssignment,
    PlaceType,
    Reservation,
    VehicleInfo,
    VehicleType,
)
from src.domain.value_objects.enums import PresenceStatus, VehicleCategory

# Registre déterministe de codes véhicule "connus" (ex-mock Vehicles), pensé
# pour exercer chaque branche des règles métier dans les tests d'intégration.
# `v_with_reservation` est l'identifiant attendu par le mock Booking.
DEMO_VEHICLES: dict[int, VehicleInfo] = {
    1: VehicleInfo(
        vehicle_id="v_standard_4wheeler",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER),
    ),
    2: VehicleInfo(
        vehicle_id="v_2wheeler",
        vehicle_type=VehicleType(category=VehicleCategory.TWO_WHEELER),
    ),
    3: VehicleInfo(
        vehicle_id="v_xl",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_xl=True),
    ),
    4: VehicleInfo(
        vehicle_id="v_electric",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_electric=True),
    ),
    5: VehicleInfo(
        vehicle_id="v_disabled_ok",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
        disability_permit=True,
    ),
    6: VehicleInfo(
        vehicle_id="v_disabled_no_permit",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
        disability_permit=False,
    ),
    7: VehicleInfo(
        vehicle_id="v_with_reservation",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER),
    ),
    8: VehicleInfo(
        vehicle_id="v_standard_4wheeler_bis",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER),
    ),
}


class FakeVehiclesPort:
    def __init__(self, registry: dict[int, VehicleInfo] | None = None) -> None:
        self.registry = registry or {}
        self.calls: list[int] = []

    def get_vehicle_info(self, vehicle_code: int) -> VehicleInfo | None:
        self.calls.append(vehicle_code)
        return self.registry.get(vehicle_code)


class FakeBookingPort:
    def __init__(self, reservations: dict[str, Reservation] | None = None) -> None:
        self.reservations = reservations or {}

    def get_reservation(self, vehicle_id: str) -> Reservation | None:
        return self.reservations.get(vehicle_id)


class FakeParkingPort:
    def __init__(
        self,
        assignment: PlaceAssignment | None = None,
        has_place: bool = True,
        unavailable: bool = False,
    ) -> None:
        self._assignment = assignment
        self._has_place = has_place
        self._unavailable = unavailable  # simule Parking injoignable
        self.occupied: dict[str, str] = {}
        self.freed: list[str] = []
        self.calls: list[tuple] = []

    def request_place(
        self, vehicle_type: VehicleType, is_reservation: bool = False
    ) -> PlaceAssignment | None:
        self.calls.append((vehicle_type, is_reservation))
        if self._unavailable:
            raise ParkingUnavailableError("parking injoignable (test)")
        if not self._has_place:
            return None
        if self._assignment is not None:
            return self._assignment
        return PlaceAssignment(
            place_id="P-TEST-1",
            place_type=PlaceType(
                category=vehicle_type.category,
                is_xl=vehicle_type.is_xl,
                is_electric=vehicle_type.is_electric,
                is_handicap=vehicle_type.is_handicap,
            ),
        )

    def mark_place_occupied(self, place_id: str, vehicle_id: str) -> bool:
        self.occupied[place_id] = vehicle_id
        return True

    def mark_place_free(self, place_id: str) -> bool:
        self.freed.append(place_id)
        return True


class FakePricingPort:
    def __init__(self, amount: Decimal = Decimal("5.00")) -> None:
        self.amount = amount
        self.calls: list[tuple] = []

    def calculate_price(
        self, vehicle_id, entry_date, exit_date, place_type, is_reservation=False
    ) -> Decimal:
        self.calls.append((vehicle_id, entry_date, exit_date, place_type, is_reservation))
        return self.amount


class FakePaymentPort:
    """`success=None` simule un résultat indéterminé (Payment injoignable ou
    paiement encore en attente après le délai de polling)."""

    def __init__(self, success: bool | None = True) -> None:
        self.success = success
        self.calls: list[tuple] = []

    def request_payment(self, stay_id: str, amount: Decimal) -> PaymentResult | None:
        self.calls.append((stay_id, amount))
        if self.success is None:
            return None
        return PaymentResult(success=self.success, transaction_reference="PAY-FAKE")


class FakeAIVisionPort:
    def analyze(self, photo: bytes | None) -> AICheckResult:
        return AICheckResult(
            ai_model="fake-test", confidence=1.0 if photo else 0.0, timestamp=datetime(2026, 1, 1)
        )


@dataclass
class _PresenceRecord:
    status: PresenceStatus
    current_request_id: str | None


class FakePresenceRepo:
    def __init__(self) -> None:
        self._store: dict[str, _PresenceRecord] = {}

    def get_status(self, vehicle_id: str) -> PresenceStatus | None:
        record = self._store.get(vehicle_id)
        return record.status if record else None

    def get_current_request_id(self, vehicle_id: str) -> str | None:
        record = self._store.get(vehicle_id)
        return record.current_request_id if record else None

    def set_status(self, vehicle_id: str, status: PresenceStatus, request_id: str | None) -> None:
        self._store[vehicle_id] = _PresenceRecord(status=status, current_request_id=request_id)

    def seed(self, vehicle_id: str, status: PresenceStatus, request_id: str | None = None) -> None:
        self.set_status(vehicle_id, status, request_id)

    def list_present(self) -> list[VehiclePresence]:
        return [
            VehiclePresence(
                vehicle_id=vehicle_id,
                status=record.status,
                updated_at=datetime.now(UTC),
                current_request_id=record.current_request_id,
            )
            for vehicle_id, record in self._store.items()
            if record.status is PresenceStatus.IN
        ]


@dataclass
class FakeAccessRepo:
    requests: dict[str, AccessRequest] = field(default_factory=dict)
    authorizations: dict[str, AccessAuthorization] = field(default_factory=dict)
    events: dict[str, AccessEvent] = field(default_factory=dict)

    def save_request(self, request: AccessRequest) -> None:
        self.requests[request.id] = request

    def save_authorization(self, authorization: AccessAuthorization) -> None:
        self.authorizations[authorization.request_id] = authorization

    def save_event(self, event: AccessEvent) -> None:
        self.events[event.request_id] = event

    def get_request(self, request_id: str) -> AccessRequest | None:
        return self.requests.get(request_id)

    def list_requests(self, filters: AccessFilters) -> list[AccessRequest]:
        results = list(self.requests.values())
        if filters.vehicle_id is not None:
            results = [r for r in results if r.vehicle_id == filters.vehicle_id]
        if filters.type is not None:
            results = [r for r in results if r.type == filters.type]
        results.sort(key=lambda r: r.date, reverse=True)
        if filters.limit is not None:
            results = results[: filters.limit]
        return results

    def get_authorization_by_request(self, request_id: str) -> AccessAuthorization | None:
        return self.authorizations.get(request_id)

    def get_event_by_request(self, request_id: str) -> AccessEvent | None:
        return self.events.get(request_id)

    def list_events(self, limit: int = 100, offset: int = 0) -> list[AccessEvent]:
        return list(self.events.values())[offset : offset + limit]


class FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[AccessEvent] = []

    def publish(self, event: AccessEvent) -> None:
        self.published.append(event)
