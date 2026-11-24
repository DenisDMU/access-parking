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
