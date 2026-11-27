"""Tests unitaires — un appel sortant qui échoue n'écrit jamais l'adresse
appelée (revue de sécurité du 27/11).

Le message d'une erreur httpx recopie l'adresse entière : avec des
identifiants dans l'adresse d'un service, ou un jeton dans celle d'un abonné,
ils finissaient dans le journal. Seuls le code HTTP ou le type de l'erreur
sont écrits.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from src.domain.entities.access_event import AccessEvent
from src.domain.ports.parking_service_port import ParkingUnavailableError
from src.domain.value_objects.enums import EventType
from src.infrastructure.external.http_parking_client import HttpParkingClient
from src.infrastructure.external.http_payment_client import HttpPaymentClient
from src.infrastructure.external.outbox_event_publisher import OutboxEventPublisher
from src.infrastructure.external.outgoing_http import describe_error
from src.infrastructure.external.rabbitmq_event_publisher import RabbitMQEventPublisher
from tests.unit.fakes import FakeAccessRepo

_SECRET = "motdepasse-de-test"
_PARKING = f"https://agent:{_SECRET}@parking.test"


class _FakeOutboxRepo:
    def record_publication(self, event_id: str) -> None:
        pass


def _event() -> AccessEvent:
    return AccessEvent(
        id="evt-1",
        type=EventType.VEHICLE_ENTERED,
        request_id="request-1",
        payload={"vehicleId": "v1"},
        created_at=datetime.now(UTC),
    )


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"connexion refusée vers {request.url}", request=request)


def _failing(status: int = 503) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _r: httpx.Response(status))


def test_describe_error_code_http_ou_type_jamais_le_message():
    request = httpx.Request("GET", f"{_PARKING}/parking/occupation")
    status_error = httpx.HTTPStatusError(
        f"503 pour {request.url}", request=request, response=httpx.Response(503, request=request)
    )
    assert describe_error(status_error) == "HTTP 503"
    assert describe_error(httpx.ConnectError(f"refusé vers {request.url}")) == "ConnectError"
    assert describe_error(ValueError(_SECRET)) == "ValueError"


@pytest.mark.parametrize("transport", [_failing(), httpx.MockTransport(_down)])
def test_parking_en_panne_ni_le_journal_ni_l_erreur_ne_portent_l_adresse(transport, caplog):
    client = HttpParkingClient(_PARKING, api_key="cle-de-test", transport=transport)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ParkingUnavailableError) as erreur:
            client.get_occupation()
        assert client.mark_place_occupied("STANDARD:walkin", "v1", hold_id="12") is False
        assert client.mark_place_free("STANDARD:walkin") is False
    assert "Parking indisponible" in caplog.text
    for text in (caplog.text, str(erreur.value)):
        assert _SECRET not in text
        assert "parking.test" not in text


@pytest.mark.parametrize("transport", [_failing(), httpx.MockTransport(_down)])
def test_payment_en_panne_le_journal_ne_porte_pas_l_adresse(transport, caplog):
    client = HttpPaymentClient(
        f"https://agent:{_SECRET}@payment.test", transport=transport, sleep=lambda _s: None
    )
    with caplog.at_level(logging.DEBUG):
        assert client.request_payment("stay-1", Decimal("4.50")) is None
    assert "Service Payment indisponible" in caplog.text
    assert _SECRET not in caplog.text


def test_abonne_en_panne_le_journal_ne_porte_que_son_hote(caplog):
    publisher = OutboxEventPublisher(
        access_repo=FakeAccessRepo(),
        outbox_repo=_FakeOutboxRepo(),
        subscriber_urls=[f"https://hooks.test/access?token={_SECRET}"],
        timeout_ms=500,
        http_client=httpx.Client(transport=_failing(500)),
    )
    with caplog.at_level(logging.DEBUG):
        publisher.publish(_event())
    assert "hooks.test" in caplog.text
    assert "HTTP 500" in caplog.text
    assert _SECRET not in caplog.text


def test_bus_injoignable_le_journal_ne_porte_pas_son_mot_de_passe(caplog):
    publisher = RabbitMQEventPublisher(
        access_repo=FakeAccessRepo(),
        outbox_repo=_FakeOutboxRepo(),
        amqp_url=f"amqp://agent:{_SECRET}@127.0.0.1:59999/%2F?connection_attempts=1",
    )
    with caplog.at_level(logging.WARNING, logger="src"):
        publisher.publish(_event())
    assert "Échec de publication RabbitMQ" in caplog.text
    assert _SECRET not in caplog.text


def test_adresse_du_bus_mal_formee_ni_500_ni_morceau_du_mot_de_passe(caplog):
    # Un « / » non encodé dans le mot de passe : pika lève ValueError et son
    # message recopie le début du mot de passe.
    publisher = RabbitMQEventPublisher(
        access_repo=FakeAccessRepo(),
        outbox_repo=_FakeOutboxRepo(),
        amqp_url=f"amqps://agent:{_SECRET}/suite@bus.example/vhost",
    )
    with caplog.at_level(logging.WARNING, logger="src"):
        publisher.publish(_event())  # ne lève pas
    assert "Échec de publication RabbitMQ" in caplog.text
    assert _SECRET not in caplog.text
