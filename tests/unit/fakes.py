"""Doubles de test (fakes) pour tous les ports du domaine — utilisés par les
tests unitaires des use cases (section 13 : "tous les ports mockés")."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.domain.entities.autorisation_acces import AutorisationAcces
from src.domain.entities.demande_acces import DemandeAcces
from src.domain.entities.evenement_acces import EvenementAcces
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
from src.domain.value_objects.enums import PresenceStatus


class FakeVehiclesPort:
    def __init__(self, registry: dict[str, VehicleInfo] | None = None) -> None:
        self.registry = registry or {}
        self.calls: list[str] = []

    def get_vehicle_info(self, plaque_brute: str) -> VehicleInfo | None:
        self.calls.append(plaque_brute)
        return self.registry.get(plaque_brute)


class FakeBookingPort:
    def __init__(self, reservations: dict[str, Reservation] | None = None) -> None:
        self.reservations = reservations or {}

    def get_reservation(self, vehicule_id: str) -> Reservation | None:
        return self.reservations.get(vehicule_id)


class FakeParkingPort:
    def __init__(self, assignment: PlaceAssignment | None = None, has_place: bool = True) -> None:
        self._assignment = assignment
        self._has_place = has_place
        self.occupied: dict[str, str] = {}
        self.freed: list[str] = []

    def request_place(self, type_vehicule: VehicleType) -> PlaceAssignment | None:
        if not self._has_place:
            return None
        if self._assignment is not None:
            return self._assignment
        return PlaceAssignment(
            place_id="P-TEST-1",
            place_type=PlaceType(
                category=type_vehicule.category,
                is_xl=type_vehicule.is_xl,
                is_electric=type_vehicule.is_electric,
                is_handicap=type_vehicule.is_handicap,
            ),
        )

    def mark_place_occupied(self, place_id: str, vehicule_id: str) -> bool:
        self.occupied[place_id] = vehicule_id
        return True

    def mark_place_free(self, place_id: str) -> bool:
        self.freed.append(place_id)
        return True


class FakePricingPort:
    def __init__(self, montant: Decimal = Decimal("5.00")) -> None:
        self.montant = montant
        self.calls: list[tuple] = []

    def calculate_price(self, vehicule_id, date_entree, date_sortie, type_place) -> Decimal:
        self.calls.append((vehicule_id, date_entree, date_sortie, type_place))
        return self.montant


class FakePaymentPort:
    def __init__(self, succes: bool = True) -> None:
        self.succes = succes
        self.calls: list[tuple] = []

    def request_payment(self, vehicule_id: str, montant: Decimal) -> PaymentResult:
        self.calls.append((vehicule_id, montant))
        return PaymentResult(succes=self.succes, reference_transaction="TX-FAKE" if self.succes else None)


class FakeAIVisionPort:
    def analyze(self, photo: bytes | None) -> AICheckResult:
        return AICheckResult(model_ai="fake-test", confidence=1.0 if photo else 0.0, timestamp=datetime(2026, 1, 1))


@dataclass
class _PresenceRecord:
    statut: PresenceStatus
    demande_id_courante: str | None


class FakePresenceRepo:
    def __init__(self) -> None:
        self._store: dict[str, _PresenceRecord] = {}

    def get_status(self, vehicule_id: str) -> PresenceStatus | None:
        record = self._store.get(vehicule_id)
        return record.statut if record else None

    def get_current_demande_id(self, vehicule_id: str) -> str | None:
        record = self._store.get(vehicule_id)
        return record.demande_id_courante if record else None

    def set_status(self, vehicule_id: str, status: PresenceStatus, demande_id: str | None) -> None:
        self._store[vehicule_id] = _PresenceRecord(statut=status, demande_id_courante=demande_id)

    def seed(self, vehicule_id: str, status: PresenceStatus, demande_id: str | None = None) -> None:
        self.set_status(vehicule_id, status, demande_id)


@dataclass
class FakeAccessRepo:
    demandes: dict[str, DemandeAcces] = field(default_factory=dict)
    autorisations: dict[str, AutorisationAcces] = field(default_factory=dict)
    evenements: dict[str, EvenementAcces] = field(default_factory=dict)

    def save_demande(self, demande: DemandeAcces) -> None:
        self.demandes[demande.id] = demande

    def save_autorisation(self, autorisation: AutorisationAcces) -> None:
        self.autorisations[autorisation.demande_id] = autorisation

    def save_evenement(self, evenement: EvenementAcces) -> None:
        self.evenements[evenement.demande_id] = evenement

    def get_demande(self, demande_id: str) -> DemandeAcces | None:
        return self.demandes.get(demande_id)

    def list_demandes(self, filters: AccessFilters) -> list[DemandeAcces]:
        results = list(self.demandes.values())
        if filters.vehicule_id is not None:
            results = [d for d in results if d.vehicule_id == filters.vehicule_id]
        if filters.type is not None:
            results = [d for d in results if d.type == filters.type]
        return results

    def get_autorisation_by_demande(self, demande_id: str) -> AutorisationAcces | None:
        return self.autorisations.get(demande_id)

    def get_evenement_by_demande(self, demande_id: str) -> EvenementAcces | None:
        return self.evenements.get(demande_id)

    def list_evenements(self, limit: int = 100, offset: int = 0) -> list[EvenementAcces]:
        return list(self.evenements.values())[offset : offset + limit]


class FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[EvenementAcces] = []

    def publish(self, evenement: EvenementAcces) -> None:
        self.published.append(evenement)
