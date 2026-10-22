"""Tests d'intégration — workflow "Sortie" (via `TestClient`)."""

from src.interfaces.api import deps
from src.interfaces.api.main import app
from tests.integration.conftest import AUTH_HEADERS
from tests.unit.fakes import FakePaymentPort


def _payload(plate: str, type_: int, date: str, source: int = 3) -> dict:
    return {"plate": plate, "type": type_, "date": date, "source": source}


def test_exit_authorized_pricing_and_payment_ok(client):
    entry = client.post(
        "/api/v1/access/requests",
        json=_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"),
        headers=AUTH_HEADERS,
    )
    assert entry.json()["authorization"]["result"] == 1

    exit_response = client.post(
        "/api/v1/access/requests",
        json=_payload("AA-111-AA", 2, "2026-09-02T11:00:00Z", source=2),
        headers=AUTH_HEADERS,
    )
    assert exit_response.status_code == 200
    body = exit_response.json()
    assert body["authorization"]["result"] == 1
    assert body["authorization"]["paymentAmount"] is not None
    assert body["authorization"]["paymentAmount"] > 0


def test_exit_refused_payment_failed(client):
    app.dependency_overrides[deps.get_payment_port] = lambda: FakePaymentPort(success=False)
    entry = client.post(
        "/api/v1/access/requests",
        json=_payload("HH-888-HH", 1, "2026-09-02T10:00:00Z"),
        headers=AUTH_HEADERS,
    )
    assert entry.json()["authorization"]["result"] == 1

    exit_response = client.post(
        "/api/v1/access/requests",
        json=_payload("HH-888-HH", 2, "2026-09-02T11:00:00Z", source=2),
        headers=AUTH_HEADERS,
    )
    assert exit_response.status_code == 200
    body = exit_response.json()
    assert body["authorization"]["result"] == 2
    assert body["authorization"]["reason"] == "Paiement refusé"


def test_exit_refused_vehicle_not_present(client):
    response = client.post(
        "/api/v1/access/requests",
        json=_payload("CC-333-CC", 2, "2026-09-02T11:00:00Z", source=2),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["authorization"]["result"] == 2
    assert "non présent" in body["authorization"]["reason"]


def test_get_access_request_by_id(client):
    entry = client.post(
        "/api/v1/access/requests",
        json=_payload("DD-444-DD", 1, "2026-09-02T10:00:00Z"),
        headers=AUTH_HEADERS,
    )
    request_id = entry.json()["requestId"]

    detail = client.get(f"/api/v1/access/requests/{request_id}", headers=AUTH_HEADERS)
    assert detail.status_code == 200
    body = detail.json()
    assert body["requestId"] == request_id
    assert body["vehicleId"] == "v_electric"


def test_get_access_request_not_found(client):
    response = client.get("/api/v1/access/requests/does-not-exist", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_list_access_requests_filters_by_vehicle_id(client):
    client.post(
        "/api/v1/access/requests",
        json=_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"),
        headers=AUTH_HEADERS,
    )
    client.post(
        "/api/v1/access/requests",
        json=_payload("BB-222-BB", 1, "2026-09-02T10:05:00Z"),
        headers=AUTH_HEADERS,
    )

    response = client.get(
        "/api/v1/access/requests", params={"vehicleId": "v_standard_4wheeler"}, headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["vehicleId"] == "v_standard_4wheeler"
