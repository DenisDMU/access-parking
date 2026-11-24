"""Composition root — injection de dépendances FastAPI.

Seul endroit de la codebase où le domaine/l'application sont reliés aux
implémentations concrètes de `infrastructure`. Les 5 services de l'équipe
(Vehicles, Booking, Parking, Pricing, Payment) sont branchés en réel. Booking
garde une bascule (`BOOKING_USE_MOCK=true`) pour les tests et le
développement hors ligne.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from src.application.use_cases.check_vehicle_known import CheckVehicleKnown
from src.application.use_cases.confirm_disability_by_agent import ConfirmDisabilityByAgent
from src.application.use_cases.get_access_request import GetAccessRequest
from src.application.use_cases.get_parking_overview import GetParkingOverview
from src.application.use_cases.list_access_requests import ListAccessRequests
from src.application.use_cases.list_present_vehicles import ListPresentVehicles
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
from src.infrastructure.db.repositories.sql_access_repository import (
    SqlAccessRepository,
)
from src.infrastructure.db.repositories.sql_outbox_repository import (
    SqlOutboxRepository,
)
from src.infrastructure.db.repositories.sql_vehicle_presence_repository import (
    SqlVehiclePresenceRepository,
)
from src.infrastructure.db.session import make_engine, make_session_factory
from src.infrastructure.external.http_booking_client import HttpBookingClient
from src.infrastructure.external.http_parking_client import HttpParkingClient
from src.infrastructure.external.http_payment_client import HttpPaymentClient
from src.infrastructure.external.http_pricing_client import HttpPricingClient
from src.infrastructure.external.http_vehicles_client import HttpVehiclesClient
from src.infrastructure.external.mock_booking_client import MockBookingClient
from src.infrastructure.external.outbox_event_publisher import OutboxEventPublisher
from src.infrastructure.external.rabbitmq_event_publisher import RabbitMQEventPublisher

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


def count_present_vehicles() -> int:
    """Pour la jauge Prometheus `access_vehicles_present` (hors requête HTTP)."""

    session = _SessionFactory()
    try:
        return SqlVehiclePresenceRepository(session).count_present()
    finally:
        session.close()


def get_access_repository(
    session: Session = Depends(get_db_session),
) -> AccessRepositoryPort:
    return SqlAccessRepository(session)


def get_presence_repository(
    session: Session = Depends(get_db_session),
) -> VehiclePresenceRepositoryPort:
    return SqlVehiclePresenceRepository(session)


def get_outbox_repository(
    session: Session = Depends(get_db_session),
) -> SqlOutboxRepository:
    return SqlOutboxRepository(session)


# --- Services externes ------------------------------------------------------


def get_vehicles_port() -> VehiclesServicePort:
    # Pas de bascule mock ici : Vehicles est branché sur le vrai service de
    # l'équipe (mock_vehicles_client.py supprimé, voir README section 5/16).
    # Les tests automatisés remplacent ce provider par un FakeVehiclesPort
    # via app.dependency_overrides (tests/integration/conftest.py).
    settings = get_settings()
    return HttpVehiclesClient(
        settings.vehicles_service_url,
        api_key=settings.vehicles_api_key,
        lookup_path=settings.vehicles_lookup_path,
        identify_path=settings.vehicles_identify_path,
    )


def get_booking_port() -> BookingServicePort:
    settings = get_settings()
    if settings.booking_use_mock:
        return MockBookingClient()
    return HttpBookingClient(settings.booking_service_url, api_key=settings.booking_api_key)


def get_parking_port() -> ParkingServicePort:
    # Pas de bascule mock ici : Parking est branché sur le vrai service de
    # l'équipe (mock_parking_client.py supprimé, voir README section 5/16).
    # Les tests automatisés remplacent ce provider par un FakeParkingPort
    # via app.dependency_overrides (tests/integration/conftest.py).
    settings = get_settings()
    return HttpParkingClient(settings.parking_service_url, api_key=settings.parking_api_key)


def get_pricing_port() -> PricingServicePort:
    # Pas de bascule mock ici : Pricing est branché sur le vrai service de
    # l'équipe (mock_pricing_client.py supprimé, voir README section 5/16).
    # Les tests automatisés remplacent ce provider par un FakePricingPort
    # via app.dependency_overrides (tests/integration/conftest.py).
    settings = get_settings()
    return HttpPricingClient(settings.pricing_service_url, api_key=settings.pricing_api_key)


def get_payment_port() -> PaymentServicePort:
    # Pas de bascule mock ici : Payment est branché sur le vrai service de
    # l'équipe (mock_payment_client.py supprimé, voir README section 5/16).
    # Les tests automatisés remplacent ce provider par un FakePaymentPort
    # via app.dependency_overrides (tests/integration/conftest.py).
    settings = get_settings()
    return HttpPaymentClient(settings.payment_service_url, api_key=settings.payment_api_key)


def get_ai_vision_port() -> AIVisionPort:
    return FakeAIVisionAdapter(get_settings().ai_model_name)


def get_event_publisher(
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
    outbox_repo: SqlOutboxRepository = Depends(get_outbox_repository),
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


def get_list_present_vehicles_use_case(
    presence_repo: VehiclePresenceRepositoryPort = Depends(get_presence_repository),
    access_repo: AccessRepositoryPort = Depends(get_access_repository),
) -> ListPresentVehicles:
    return ListPresentVehicles(presence_repo, access_repo)


def get_parking_overview_use_case(
    parking_port: ParkingServicePort = Depends(get_parking_port),
) -> GetParkingOverview:
    return GetParkingOverview(parking_port)


def get_check_vehicle_known_use_case(
    vehicles_port: VehiclesServicePort = Depends(get_vehicles_port),
) -> CheckVehicleKnown:
    return CheckVehicleKnown(vehicles_port)


def get_confirm_disability_use_case(
    vehicles_port: VehiclesServicePort = Depends(get_vehicles_port),
    entry_use_case: ProcessEntryRequest = Depends(get_process_entry_request_use_case),
) -> ConfirmDisabilityByAgent:
    return ConfirmDisabilityByAgent(vehicles_port=vehicles_port, entry_use_case=entry_use_case)
