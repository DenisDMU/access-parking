"""Test d'intégration — `GET /access/plates/{plaque}/known`."""

from tests.integration.conftest import AUTH_HEADERS


def test_plate_known_retourne_vehicule_id_pseudonymise(client):
    response = client.get("/api/v1/access/plates/AA-111-AA/known", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["known"] is True
    assert body["vehiculeId"] == "v_normal_4roues"
    assert "plaque" not in body


def test_plate_inconnue(client):
    response = client.get("/api/v1/access/plates/ZZ-999-ZZ/known", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["known"] is False
    assert body["vehiculeId"] is None


def test_plate_known_sans_api_key_refuse(client):
    response = client.get("/api/v1/access/plates/AA-111-AA/known")
    assert response.status_code == 401


def test_plate_format_invalide_rejetee_en_422(client):
    response = client.get("/api/v1/access/plates/invalid/known", headers=AUTH_HEADERS)
    assert response.status_code == 422
