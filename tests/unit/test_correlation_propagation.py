"""Tests unitaires — propagation du correlation ID et métriques des appels
sortants (jalons 12 et 13)."""

import json

import httpx
import pika
from prometheus_client import REGISTRY

from src.infrastructure.external.http_booking_client import HttpBookingClient
from src.infrastructure.external.http_vehicles_client import HttpVehiclesClient
from src.infrastructure.external.outgoing_http import outgoing_client
from src.infrastructure.external.rabbitmq_event_publisher import RabbitMQEventPublisher
from src.infrastructure.logging_config import correlation_id_var
from tests.unit.fakes import FakeAccessRepo
from tests.unit.test_rabbitmq_event_publisher import _FakeOutboxRepo, _make_event


def _sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_le_correlation_id_courant_est_transmis_au_service_appele():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["cid"] = request.headers.get("X-Correlation-ID")
        return httpx.Response(200, json={})

    token = correlation_id_var.set("cid-propagation-1")
    try:
        with outgoing_client("test", timeout=1, transport=httpx.MockTransport(handler)) as c:
            c.get("http://service.test/ping")
    finally:
        correlation_id_var.reset(token)

    assert seen["cid"] == "cid-propagation-1"


def test_pas_den_tete_hors_requete():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["cid"] = request.headers.get("X-Correlation-ID")
        return httpx.Response(200)

    with outgoing_client("test", timeout=1, transport=httpx.MockTransport(handler)) as c:
        c.get("http://service.test/ping")

    assert seen["cid"] is None


def test_client_vehicles_propage_le_correlation_id_et_compte_lappel():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["cid"] = request.headers.get("X-Correlation-ID")
        return httpx.Response(200, json={"pseudoId": "p1", "code": 1})

    before = _sample("access_outgoing_requests_total", service="vehicles", outcome="2xx")
    token = correlation_id_var.set("cid-vehicles")
    try:
        info = HttpVehiclesClient("http://vehicles.test", transport=httpx.MockTransport(handler))
        assert info.get_vehicle_info(1).vehicle_id == "p1"
    finally:
        correlation_id_var.reset(token)

    assert seen["cid"] == "cid-vehicles"
    after = _sample("access_outgoing_requests_total", service="vehicles", outcome="2xx")
    assert after == before + 1


def test_echec_reseau_compte_comme_erreur():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    before = _sample("access_outgoing_requests_total", service="vehicles", outcome="error")
    client = HttpVehiclesClient("http://vehicles.test", transport=httpx.MockTransport(handler))
    assert client.get_vehicle_info(1) is None
    after = _sample("access_outgoing_requests_total", service="vehicles", outcome="error")
    assert after == before + 1


def test_booking_indisponible_ne_plante_pas():
    """Correctif : une panne Booking donnait une 500 ; elle est maintenant
    traitée comme « pas de réservation »."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    client = HttpBookingClient("http://booking.test", transport=httpx.MockTransport(handler))
    assert client.get_reservation("v1") is None


def test_booking_reponse_5xx_ne_plante_pas():
    client = HttpBookingClient(
        "http://booking.test", transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    assert client.get_reservation("v1") is None


def test_evenement_rabbitmq_porte_le_correlation_id(monkeypatch):
    published = {}

    class _Channel:
        def exchange_declare(self, **kwargs):
            pass

        def basic_publish(self, **kwargs):
            published.update(kwargs)

    class _Connection:
        def __init__(self, params):
            pass

        def channel(self):
            return _Channel()

        def close(self):
            pass

    monkeypatch.setattr(pika, "BlockingConnection", _Connection)
    publisher = RabbitMQEventPublisher(
        access_repo=FakeAccessRepo(),
        outbox_repo=_FakeOutboxRepo(),
        amqp_url="amqp://guest:guest@broker.test:5672/%2F",
    )

    before = _sample(
        "access_events_published_total",
        channel="rabbitmq",
        event_type="vehicle_entered",
        outcome="ok",
    )
    token = correlation_id_var.set("cid-bus")
    try:
        publisher.publish(_make_event())
    finally:
        correlation_id_var.reset(token)

    assert published["routing_key"] == "access.entry"
    assert published["properties"].correlation_id == "cid-bus"
    assert published["properties"].headers == {"X-Correlation-ID": "cid-bus"}
    assert json.loads(published["body"])["correlationId"] == "cid-bus"
    after = _sample(
        "access_events_published_total",
        channel="rabbitmq",
        event_type="vehicle_entered",
        outcome="ok",
    )
    assert after == before + 1
