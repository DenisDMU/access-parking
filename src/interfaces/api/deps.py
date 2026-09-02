"""Composition root — injection de dépendances FastAPI.

Seul endroit de la codebase où le domaine/l'application sont reliés aux
implémentations concrètes de `infrastructure`. Chaque service externe a sa
propre bascule mock/réel (`VEHICLES_USE_MOCK`, `BOOKING_USE_MOCK`, etc., avec
`USE_MOCKS` comme valeur par défaut globale si aucune n'est définie — voir
`infrastructure/config.py`) : passez celle d'un service à `false` dès que
son équipe est prête, sans attendre les 4 autres. Chaque `get_*_port()`
ci-dessous instancie alors automatiquement le client HTTP correspondant dans
`infrastructure/external/http_*_client.py`. Ces clients sont des SQUELETTES
(routes/champs à confirmer avec chaque équipe, voir les TODO dans chaque
fichier) — aucune autre couche à toucher une fois finalisés.
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
from src.infrastructure.external.outbox_event_publisher import OutboxEventPublisher
from src.infrastructure.external.rabbitmq_event_publisher import RabbitMQEventPublisher
from src.infrastructure.external.http_booking_client import HttpBookingClient
from src.infrastructure.external.http_parking_client import HttpParkingClient
from src.infrastructure.external.http_payment_client import HttpPaymentClient
from src.infrastructure.external.http_pricing_client import HttpPricingClient
from src.infrastructure.external.http_vehicles_client import HttpVehiclesClient
from src.infrastructure.external.mock_booking_client import MockBookingClient
from src.infrastructure.external.mock_payment_client import MockPaymentClient
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
    settings = get_settings()
    if settings.vehicles_use_mock:
        return MockVehiclesClient()
    # ⚠️ Squelette : routes/champs à confirmer avec l'équipe Vehicles avant
    # utilisation réelle — voir les TODO dans http_vehicles_client.py.
    return HttpVehiclesClient(settings.vehicles_service_url)


def get_booking_port() -> BookingServicePort:
    settings = get_settings()
    if settings.booking_use_mock:
        return MockBookingClient()
    # ⚠️ Squelette : routes/champs à confirmer avec l'équipe Booking avant
    # utilisation réelle — voir les TODO dans http_booking_client.py.
    return HttpBookingClient(settings.booking_service_url)


def get_parking_port() -> ParkingServicePort:
    # Pas de bascule mock ici : Parking est branché sur le vrai service de
    # l'équipe (mock_parking_client.py supprimé, voir README section 5/16).
    # Les tests automatisés remplacent ce provider par un FakeParkingPort
    # via app.dependency_overrides (tests/integration/conftest.py).
    settings = get_settings()
    return HttpParkingClient(settings.parking_service_url)


def get_pricing_port() -> PricingServicePort:
    # Pas de bascule mock ici : Pricing est branché sur le vrai service de
    # l'équipe (mock_pricing_client.py supprimé, voir README section 5/16).
    # Les tests automatisés remplacent ce provider par un FakePricingPort
    # via app.dependency_overrides (tests/integration/conftest.py).
    settings = get_settings()
    return HttpPricingClient(settings.pricing_service_url)


def get_payment_port() -> PaymentServicePort:
    settings = get_settings()
    if settings.payment_use_mock:
        return MockPaymentClient()
    # ⚠️ Squelette : routes/champs à confirmer avec l'équipe Payment avant
    # utilisation réelle — voir les TODO dans http_payment_client.py.
    return HttpPaymentClient(settings.payment_service_url)


def get_ai_vision_port() -> AIVisionPort:
    return FakeAIVisionAdapter(get_settings().ai_model_name)


def get_event_publisher(
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
    outbox_repo: SqliteOutboxRepository = Depends(get_outbox_repository),
) -> EventPublisherPort:
    settings = get_settings()
    if settings.event_publisher == "rabbitmq":
        return RabbitMQEventPublisher(
            access_repo=access_repo,
            outbox_repo=outbox_repo,
            amqp_url=settings.rabbitmq_url,
            exchange_name=settings.rabbitmq_exchange,
        )
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
