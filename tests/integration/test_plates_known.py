"""Test d'intégration — `GET /access/plates/{plate}/known`."""

from tests.integration.conftest import AUTH_HEADERS


def test_plate_known_returns_pseudonymized_vehicle_id(client):
    response = client.get("/api/v1/access/plates/AA-111-AA/known", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["known"] is True
    assert body["vehicleId"] == "v_standard_4wheeler"
    assert "plate" not in body


def test_unknown_plate(client):
    response = client.get("/api/v1/access/plates/ZZ-999-ZZ/known", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["known"] is False
    assert body["vehicleId"] is None


def test_plate_known_without_api_key_is_refused(client):
    response = client.get("/api/v1/access/plates/AA-111-AA/known")
    assert response.status_code == 401


def test_invalid_plate_format_is_rejected_with_422(client):
    response = client.get("/api/v1/access/plates/invalid/known", headers=AUTH_HEADERS)
    assert response.status_code == 422
