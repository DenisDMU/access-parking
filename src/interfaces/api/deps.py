"""Composition root — injection de dépendances FastAPI.

Seul endroit de la codebase où le domaine/l'application sont reliés aux
implémentations concrètes de `infrastructure`. `USE_MOCKS` est LE point de
bascule pour brancher un vrai microservice à la place d'un mock (section 3
point 2, section 14 point 5 du README) : basculez `settings.use_mocks` à
`False` et remplacez le `raise NotImplementedError` ci-dessous par
l'instanciation de votre client HTTP réel — aucune autre couche à toucher.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from src.application.use_cases.check_plate_known import CheckPlateKnown
from src.application.use_cases.get_access_request import GetAccessRequest
from src.application.use_cases.list_access_requests import ListAccessRequests
from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.application.use_cases.process_exit_request import ProcessExitRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.ai_vision_port import AIVisionPort
from src.domain.ports.booking_service_port import BookingServicePort
from src.domain.ports.event_publisher_port import EventPublisherPort
from src.domain.ports.parking_service_port import ParkingServicePort
from src.domain.ports.payment_service_port import PaymentServicePort
from src.domain.ports.pricing_service_port import PricingServicePort
from src.domain.ports.vehicle_presence_repository_port import (
    VehiclePresenceRepositoryPort,
)
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.infrastructure.ai.fake_ai_vision_adapter import FakeAIVisionAdapter
from src.infrastructure.config import get_settings
from src.infrastructure.db.repositories.sqlite_access_repository import (
    SqliteAccessRepository,
)
from src.infrastructure.db.repositories.sqlite_outbox_repository import (
    SqliteOutboxRepository,
)
from src.infrastructure.db.repositories.sqlite_vehicle_presence_repository import (
    SqliteVehiclePresenceRepository,
)
from src.infrastructure.db.session import make_engine, make_session_factory
from src.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from src.infrastructure.external.mock_booking_client import MockBookingClient
from src.infrastructure.external.mock_parking_client import MockParkingClient
from src.infrastructure.external.mock_payment_client import MockPaymentClient
from src.infrastructure.external.mock_pricing_client import MockPricingClient
from src.infrastructure.external.mock_vehicles_client import MockVehiclesClient

_settings = get_settings()
_engine = make_engine(_settings.database_url)
_SessionFactory = make_session_factory(_engine)


def get_engine():
    return _engine


def get_db_session() -> Generator[Session, None, None]:
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()


# --- Repositories -----------------------------------------------------------

def get_access_repository(
    session: Session = Depends(get_db_session),
) -> AccessRepositoryPort:
    return SqliteAccessRepository(session)


def get_presence_repository(
    session: Session = Depends(get_db_session),
) -> VehiclePresenceRepositoryPort:
    return SqliteVehiclePresenceRepository(session)


def get_outbox_repository(
    session: Session = Depends(get_db_session),
) -> SqliteOutboxRepository:
    return SqliteOutboxRepository(session)


# --- Services externes (bascule USE_MOCKS) ----------------------------------

def get_vehicles_port() -> VehiclesServicePort:
    if get_settings().use_mocks:
        return MockVehiclesClient()
    raise NotImplementedError(
        "USE_MOCKS=false : implémentez un client HTTP réel dans "
        "infrastructure/external/ respectant VehiclesServicePort (voir README)."
    )


def get_booking_port() -> BookingServicePort:
    if get_settings().use_mocks:
        return MockBookingClient()
    raise NotImplementedError(
        "USE_MOCKS=false : implémentez un client HTTP réel dans "
        "infrastructure/external/ respectant BookingServicePort (voir README)."
    )


def get_parking_port() -> ParkingServicePort:
    if get_settings().use_mocks:
        return MockParkingClient()
    raise NotImplementedError(
        "USE_MOCKS=false : implémentez un client HTTP réel dans "
        "infrastructure/external/ respectant ParkingServicePort (voir README)."
    )


def get_pricing_port() -> PricingServicePort:
    if get_settings().use_mocks:
        return MockPricingClient()
    raise NotImplementedError(
        "USE_MOCKS=false : implémentez un client HTTP réel dans "
        "infrastructure/external/ respectant PricingServicePort (voir README)."
    )


def get_payment_port() -> PaymentServicePort:
    if get_settings().use_mocks:
        return MockPaymentClient()
    raise NotImplementedError(
        "USE_MOCKS=false : implémentez un client HTTP réel dans "
        "infrastructure/external/ respectant PaymentServicePort (voir README)."
    )


def get_ai_vision_port() -> AIVisionPort:
    return FakeAIVisionAdapter(get_settings().ai_model_name)


def get_event_publisher(
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
    outbox_repo: SqliteOutboxRepository = Depends(get_outbox_repository),
) -> EventPublisherPort:
    settings = get_settings()
    return OutboxEventPublisher(
        access_repo=access_repo,
        outbox_repo=outbox_repo,
        subscriber_urls=settings.event_subscribers_urls,
        timeout_ms=settings.event_publish_timeout_ms,
    )


# --- Use cases ---------------------------------------------------------------

def get_process_entry_request_use_case(
    vehicles_port: VehiclesServicePort = Depends(get_vehicles_port),
    booking_port: BookingServicePort = Depends(get_booking_port),
    parking_port: ParkingServicePort = Depends(get_parking_port),
    presence_repo: VehiclePresenceRepositoryPort = Depends(get_presence_repository),
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
    event_publisher: EventPublisherPort = Depends(get_event_publisher),
    ai_vision_port: AIVisionPort = Depends(get_ai_vision_port),
) -> ProcessEntryRequest:
    return ProcessEntryRequest(
        vehicles_port=vehicles_port,
        booking_port=booking_port,
        parking_port=parking_port,
        presence_repo=presence_repo,
        access_repo=access_repo,
        event_publisher=event_publisher,
        ai_vision_port=ai_vision_port,
    )


def get_process_exit_request_use_case(
    vehicles_port: VehiclesServicePort = Depends(get_vehicles_port),
    parking_port: ParkingServicePort = Depends(get_parking_port),
    pricing_port: PricingServicePort = Depends(get_pricing_port),
    payment_port: PaymentServicePort = Depends(get_payment_port),
    presence_repo: VehiclePresenceRepositoryPort = Depends(get_presence_repository),
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
    event_publisher: EventPublisherPort = Depends(get_event_publisher),
) -> ProcessExitRequest:
    return ProcessExitRequest(
        vehicles_port=vehicles_port,
        parking_port=parking_port,
        pricing_port=pricing_port,
        payment_port=payment_port,
        presence_repo=presence_repo,
        access_repo=access_repo,
        event_publisher=event_publisher,
    )


def get_get_access_request_use_case(
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
) -> GetAccessRequest:
    return GetAccessRequest(access_repo)


def get_list_access_requests_use_case(
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
) -> ListAccessRequests:
    return ListAccessRequests(access_repo)


def get_check_plate_known_use_case(
    vehicles_port: VehiclesServicePort = Depends(get_vehicles_port),
) -> CheckPlateKnown:
    return CheckPlateKnown(vehicles_port)
