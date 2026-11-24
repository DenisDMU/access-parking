"""Tests d'intégration — workflow "Entrée" (via `TestClient`)."""

from tests.integration.conftest import AUTH_HEADERS


def _entry_payload(plate: str, date: str = "2026-09-02T10:15:00Z", source: int = 3) -> dict:
    return {"licensePlate": plate, "type": 1, "date": date, "source": source}


def test_entry_authorized_without_reservation_with_parking_assignment(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("AA-111-AA"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicleId"] == "v_standard_4wheeler"
    assert body["status"] == 2
    assert body["authorization"]["result"] == 1


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


def test_entry_unknown_plate_is_created_by_vehicles_then_authorized(client):
    """Règle 3.2 : Vehicles retrouve ou crée le véhicule, l'entrée continue."""

    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("ZZ-999-ZZ"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicleId"] == "v_created_1"
    assert body["authorization"]["result"] == 1
    assert client.vehicles.created == ["ZZ-999-ZZ"]


def test_entry_when_vehicles_is_down_requires_an_agent(client):
    client.vehicles.available = False
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("AA-111-AA"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicleId"] is None
    assert body["status"] == 3
    assert body["authorization"]["result"] == 3


def test_entry_plate_is_normalized_before_calling_vehicles(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("aa 111 aa"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["vehicleId"] == "v_standard_4wheeler"
    assert client.vehicles.calls == ["AA-111-AA"]


def test_entry_without_api_key_is_refused(client):
    response = client.post("/api/v1/access/requests", json=_entry_payload("AA-111-AA"))
    assert response.status_code == 401


def test_invalid_plate_is_rejected_with_422_without_echoing_it(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("AB#123"), headers=AUTH_HEADERS
    )
    assert response.status_code == 422
    assert "AB#123" not in response.text
    assert client.vehicles.calls == []


def test_plaque_etrangere_acceptee_et_normalisee_sans_separateurs(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("b-mw 1234"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["authorization"]["result"] == 1
    assert client.vehicles.calls == ["BMW1234"]
    assert client.vehicles.created == ["BMW1234"]


def test_ancien_format_francais_accepte(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("123 ABC 75"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    assert client.vehicles.calls == ["123ABC75"]


def test_meme_plaque_etrangere_saisie_autrement_retrouve_le_meme_vehicule(client):
    """Entrée « B-MW 1234 », sortie « bmw1234 » : même véhicule chez Vehicles."""

    entry = client.post(
        "/api/v1/access/requests", json=_entry_payload("B-MW 1234"), headers=AUTH_HEADERS
    ).json()
    exit_ = client.post(
        "/api/v1/access/requests",
        json={**_entry_payload("bmw1234", date="2026-09-02T12:15:00Z"), "type": 2},
        headers=AUTH_HEADERS,
    ).json()
    assert exit_["vehicleId"] == entry["vehicleId"]
    assert exit_["authorization"]["result"] == 1
