"""Test d'intégration — `GET /access/vehicles/{vehicle_code}/known`."""

from tests.integration.conftest import AUTH_HEADERS


def test_vehicle_known_returns_pseudonymized_vehicle_id(client):
    response = client.get("/api/v1/access/vehicles/1/known", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["known"] is True
    assert body["vehicleId"] == "v_standard_4wheeler"


def test_unknown_vehicle(client):
    response = client.get("/api/v1/access/vehicles/999/known", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["known"] is False
    assert body["vehicleId"] is None


def test_vehicle_known_without_api_key_is_refused(client):
    response = client.get("/api/v1/access/vehicles/1/known")
    assert response.status_code == 401


def test_invalid_vehicle_code_is_rejected_with_422(client):
    response = client.get("/api/v1/access/vehicles/invalid/known", headers=AUTH_HEADERS)
    assert response.status_code == 422
