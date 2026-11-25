"""Tests d'intégration — `GET /access/presences` (état du parking)."""

from tests.integration.conftest import AUTH_HEADERS


def _passage(client, plate: str, type_: int, date: str):
    return client.post(
        "/api/v1/access/requests",
        json={"licensePlate": plate, "type": type_, "date": date, "source": 3},
        headers=AUTH_HEADERS,
    )


def test_presences_requiert_la_cle_api(client):
    assert client.get("/api/v1/access/presences").status_code == 401


def test_presences_suit_entree_puis_sortie(client):
    assert client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json() == []

    entry = _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z").json()
    present = client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json()
    assert len(present) == 1
    assert present[0]["vehicleId"] == entry["vehicleId"]
    assert present[0]["entryRequestId"] == entry["requestId"]
    assert present[0]["enteredAt"].startswith("2026-09-02T10:00:00")
    assert present[0]["placeType"]["category"] == 2
    assert present[0]["reservation"] is False

    _passage(client, "AA-111-AA", 2, "2026-09-02T12:00:00Z")
    assert client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json() == []


def test_entree_refusee_napparait_pas_dans_les_presences(client):
    _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z")
    refused = _passage(client, "AA-111-AA", 1, "2026-09-02T10:05:00Z").json()
    assert refused["authorization"]["result"] == 2

    present = client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json()
    assert len(present) == 1


# --- Libérer un véhicule présent (sortie forcée par l'exploitation) ---------------

from tests.integration.conftest import BORNE_HEADERS  # noqa: E402


def _release(client, vehicle_id: str, headers=AUTH_HEADERS):
    return client.post(f"/api/v1/access/presences/{vehicle_id}/release", headers=headers)


def test_liberer_un_vehicule_present(client):
    entry = _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z").json()
    response = _release(client, entry["vehicleId"])
    assert response.status_code == 200
    body = response.json()
    assert body["vehicleId"] == entry["vehicleId"]
    assert body["placeFreed"] is True and body["placeId"]
    # Plus présent ; il peut de nouveau entrer.
    assert client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json() == []
    again = _passage(client, "AA-111-AA", 1, "2026-09-02T12:00:00Z").json()
    assert again["authorization"]["result"] == 1


def test_liberation_tracee_et_publiee_sans_paiement(client):
    entry = _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z").json()
    body = _release(client, entry["vehicleId"]).json()
    detail = client.get(f"/api/v1/access/requests/{body['requestId']}", headers=AUTH_HEADERS).json()
    assert detail["type"] == 2 and detail["authorization"]["result"] == 1
    assert "forcée par l'exploitation" in detail["authorization"]["reason"]
    assert detail["authorization"]["paymentAmount"] is None
    events = client.get("/api/v1/access/events", headers=AUTH_HEADERS).json()
    forced = [e for e in events if e["requestId"] == body["requestId"]]
    assert len(forced) == 1 and forced[0]["type"] == 2
    assert forced[0]["payload"]["forced"] is True and forced[0]["payload"]["amount"] == "0"
    assert forced[0]["payload"]["paymentId"] is None


def test_liberer_un_vehicule_absent_404_sans_effet(client):
    response = _release(client, "inconnu-123")
    assert response.status_code == 404
    assert client.get("/api/v1/access/events", headers=AUTH_HEADERS).json() == []
    # Deux fois de suite : la seconde ne fait rien.
    entry = _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z").json()
    assert _release(client, entry["vehicleId"]).status_code == 200
    assert _release(client, entry["vehicleId"]).status_code == 404


def test_liberation_reservee_a_l_exploitation(client):
    entry = _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z").json()
    assert _release(client, entry["vehicleId"], headers={}).status_code == 401
    assert _release(client, entry["vehicleId"], headers=BORNE_HEADERS).status_code == 401
    assert len(client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json()) == 1


def test_liberation_meme_si_parking_ne_repond_pas(client):
    from src.interfaces.api import deps
    from src.interfaces.api.main import app
    from tests.unit.fakes import FakeParkingPort

    entry = _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z").json()

    class Down(FakeParkingPort):
        def mark_place_free(self, place_id: str) -> bool:
            return False

    app.dependency_overrides[deps.get_parking_port] = lambda: Down()
    body = _release(client, entry["vehicleId"]).json()
    assert body["placeFreed"] is False  # à libérer chez Parking
    assert client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json() == []


def test_identifiant_invalide_refuse(client):
    assert _release(client, "a b").status_code in (404, 422)
    assert _release(client, "x" * 80).status_code == 422
