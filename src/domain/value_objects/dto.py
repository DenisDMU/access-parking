"""Value objects (DTO) échangés avec les ports du domaine.

Ces objets sont volontairement de simples `dataclass` immuables : ils ne
portent aucune dépendance vers `infrastructure`, conformément à la règle de
dépendance stricte de l'architecture hexagonale (section 4 de la spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domain.value_objects.enums import (
    AuthorizationResult,
    RequestStatus,
    RequestType,
    VehicleCategory,
)


@dataclass(frozen=True)
class VehicleType:
    """Caractéristiques d'un véhicule utiles à la décision d'accès.

    Ne contient jamais la plaque : uniquement les attributs nécessaires à la
    règle de compatibilité véhicule/place et à la règle d'accessibilité.
    """

    category: VehicleCategory
    is_xl: bool = False
    is_electric: bool = False
    is_handicap: bool = False


@dataclass(frozen=True)
class PlaceType:
    """Caractéristiques d'une place de parking."""

    category: VehicleCategory
    is_xl: bool = False
    is_electric: bool = False
    is_handicap: bool = False


@dataclass(frozen=True)
class VehicleInfo:
    """Réponse de `VehiclesServicePort.get_vehicle_info`.

    `vehicle_id` est l'identifiant **pseudonymisé** — la seule référence au
    véhicule qui doit ensuite circuler dans le reste du système.
    """

    vehicle_id: str
    vehicle_type: VehicleType
    disability_permit: bool = False


@dataclass(frozen=True)
class Reservation:
    """Réponse de `BookingServicePort.get_reservation`.

    `place_id` est une extension pragmatique par rapport à la spec (voir
    README, section "Écarts assumés par rapport à la spec") : le schéma SQL
    officiel ne persiste pas de colonne place/place_type dédiée, donc c'est
    Booking (mocké) qui, lorsqu'il existe une réservation, indique déjà la
    place précise réservée. Si `place_id` est `None`, le use case retombe sur
    `ParkingServicePort.request_place` pour obtenir une place du bon type.
    """

    id: str
    vehicle_id: str
    reserved_place_type: PlaceType
    start_date: datetime
    end_date: datetime
    place_id: str | None = None


@dataclass(frozen=True)
class PlaceAssignment:
    """Réponse de `ParkingServicePort.request_place`."""

    place_id: str
    place_type: PlaceType


@dataclass(frozen=True)
class PaymentResult:
    """Réponse de `PaymentServicePort.request_payment` (statut final connu)."""

    success: bool
    # Identifiant du paiement côté Payment (`payment_id`).
    transaction_reference: str | None = None


@dataclass(frozen=True)
class AICheckResult:
    """Réponse de `AIVisionPort.analyze` — ne contient jamais de plaque."""

    ai_model: str
    confidence: float
    timestamp: datetime


@dataclass(frozen=True)
class AccessFilters:
    """Filtres pour `AccessRepositoryPort.list_requests` (audit).

    Filtre exclusivement sur `vehicle_id` pseudonymisé, jamais sur la
    plaque brute.
    """

    vehicle_id: str | None = None
    type: RequestType | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True)
class EntryDecision:
    """DTO de sortie du use case `ProcessEntryRequest`."""

    request_id: str
    vehicle_id: str | None
    type: RequestType
    status: RequestStatus
    result: AuthorizationResult
    reason: str | None
    vehicle_type_check_ok: bool | None
    disability_check_ok: bool | None
    payment_amount: Decimal | None = None


@dataclass(frozen=True)
class ExitDecision:
    """DTO de sortie du use case `ProcessExitRequest`."""

    request_id: str
    vehicle_id: str | None
    type: RequestType
    status: RequestStatus
    result: AuthorizationResult
    reason: str | None
    payment_amount: Decimal | None = None
