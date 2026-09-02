"""Tests d'intégration — workflow "Entrée" (via `TestClient`)."""

from tests.integration.conftest import AUTH_HEADERS


def _entry_payload(plate: str, date: str = "2026-09-02T10:15:00Z", source: int = 3) -> dict:
    return {"plate": plate, "type": 1, "date": date, "source": source}


def test_entry_authorized_without_reservation_with_parking_assignment(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("AA-111-AA"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicleId"] == "v_standard_4wheeler"
    assert body["status"] == 2
    assert body["authorization"]["result"] == 1
    assert "plate" not in body


def test_entry_authorized_with_existing_reservation(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("GG-777-GG"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicleId"] == "v_with_reservation"
    assert body["authorization"]["result"] == 1


def test_entry_refused_vehicle_already_present(client):
    first = client.post(
        "/api/v1/access/requests", json=_entry_payload("BB-222-BB"), headers=AUTH_HEADERS
    )
    assert first.json()["authorization"]["result"] == 1

    second = client.post(
        "/api/v1/access/requests",
        json=_entry_payload("BB-222-BB", date="2026-09-02T10:20:00Z"),
        headers=AUTH_HEADERS,
    )
    assert second.status_code == 200
    body = second.json()
    assert body["authorization"]["result"] == 2
    assert "présent" in body["authorization"]["reason"]


def test_entry_confirmation_required_disabled_without_permit(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("FF-666-FF"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["authorization"]["result"] == 3
    assert body["authorization"]["disabilityCheckOk"] is False


def test_entry_unknown_vehicle(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("UN-000-KN"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicleId"] is None
    assert body["status"] == 3


def test_entry_without_api_key_is_refused(client):
    response = client.post("/api/v1/access/requests", json=_entry_payload("AA-111-AA"))
    assert response.status_code == 401


def test_invalid_plate_format_is_rejected_with_422(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("invalid"), headers=AUTH_HEADERS
    )
    assert response.status_code == 422
