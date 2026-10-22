"""Tests unitaires — `http_payment_client.py` contre un faux serveur Payment
(`httpx.MockTransport`), sans appel réseau au vrai service."""

import json
from decimal import Decimal

import httpx

from src.infrastructure.external.http_payment_client import HttpPaymentClient, _to_cents

_BASE_URL = "https://payment.test"


def _payment(status: str, payment_id: str = "pay-1") -> dict:
    return {"payment_id": payment_id, "status": status}


def _client(handler, **kwargs) -> HttpPaymentClient:
    return HttpPaymentClient(
        _BASE_URL,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,  # pas d'attente réelle pendant le polling
        **kwargs,
    )


def test_to_cents():
    assert _to_cents(Decimal("4.60")) == 460
    assert _to_cents(Decimal("12.5")) == 1250
    assert _to_cents(Decimal("1.005")) == 101  # arrondi commercial


def test_payload_respects_payment_contract():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = json.loads(request.content)
        sent["headers"] = request.headers
        return httpx.Response(202, json=_payment("ACCEPTED"))

    _client(handler).request_payment("entry-42", Decimal("4.60"))

    assert sent["body"] == {
        "idempotency_key": "access:entry-42:exit",
        "amount": 460,
        "currency": "EUR",
        "reference": {"type": "PARKING_EXIT", "id": "entry-42"},
        "source_service": "access",
    }
    assert "x-api-key" not in sent["headers"]  # pas de clé configurée → pas d'en-tête


def test_api_key_header_sent_when_configured():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key"))
        return httpx.Response(202, json=_payment("PENDING")) if request.method == "POST" else httpx.Response(
            200, json=_payment("ACCEPTED")
        )

    _client(handler, api_key="secret").request_payment("entry-42", Decimal("4.60"))

    assert seen == ["secret", "secret"]  # POST + GET de polling


def test_polls_until_accepted():
    statuses = iter(["PENDING", "PENDING", "ACCEPTED"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json=_payment("PENDING"))
        assert request.url.path == "/payments/pay-1"
        return httpx.Response(200, json=_payment(next(statuses)))

    result = _client(handler).request_payment("entry-42", Decimal("4.60"))

    assert result is not None
    assert result.success is True
    assert result.transaction_reference == "pay-1"


def test_refused_is_a_definitive_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202 if request.method == "POST" else 200, json=_payment("REFUSED"))

    result = _client(handler).request_payment("entry-42", Decimal("4.60"))

    assert result is not None
    assert result.success is False


def test_idempotent_replay_200_is_a_normal_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payment("ACCEPTED"))

    result = _client(handler).request_payment("entry-42", Decimal("4.60"))

    assert result is not None
    assert result.success is True


def test_still_pending_after_timeout_is_undetermined():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202 if request.method == "POST" else 200, json=_payment("PENDING"))

    result = _client(handler, poll_timeout_s=0).request_payment("entry-42", Decimal("4.60"))

    assert result is None  # ni succès ni refus : la sortie pourra être rejouée


def test_server_error_is_undetermined():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert _client(handler).request_payment("entry-42", Decimal("4.60")) is None


def test_unexpected_response_is_undetermined():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"unexpected": True})

    assert _client(handler).request_payment("entry-42", Decimal("4.60")) is None
