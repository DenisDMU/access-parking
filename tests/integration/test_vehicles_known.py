"""Test d'intégration — `POST /access/vehicles/known`."""

from tests.integration.conftest import AUTH_HEADERS

URL = "/api/v1/access/vehicles/known"


def test_vehicle_known_returns_pseudonymized_vehicle_id(client):
    response = client.post(URL, json={"licensePlate": "AA-111-AA"}, headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body == {"known": True, "vehicleId": "v_standard_4wheeler"}


def test_unknown_vehicle_is_not_created(client):
    response = client.post(URL, json={"licensePlate": "ZZ-999-ZZ"}, headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"known": False, "vehicleId": None}
    assert client.vehicles.created == []


def test_vehicle_known_without_api_key_is_refused(client):
    response = client.post(URL, json={"licensePlate": "AA-111-AA"})
    assert response.status_code == 401


def test_invalid_plate_is_rejected_with_422(client):
    response = client.post(URL, json={"licensePlate": "invalide"}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_plate_is_not_accepted_in_the_url(client):
    response = client.get("/api/v1/access/vehicles/AA-111-AA/known", headers=AUTH_HEADERS)
    assert response.status_code in (404, 405)
