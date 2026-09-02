"""Tests d'intégration — workflow "Entrée" (via `TestClient`)."""

from tests.integration.conftest import AUTH_HEADERS


def _entry_payload(plaque: str, date: str = "2026-09-02T10:15:00Z", source: int = 3) -> dict:
    return {"plaque": plaque, "type": 1, "date": date, "source": source}


def test_entree_autorisee_sans_reservation_avec_attribution_parking(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("AA-111-AA"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehiculeId"] == "v_normal_4roues"
    assert body["statut"] == 2
    assert body["autorisation"]["resultat"] == 1
    assert "plaque" not in body


def test_entree_autorisee_avec_reservation_existante(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("GG-777-GG"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehiculeId"] == "v_with_reservation"
    assert body["autorisation"]["resultat"] == 1


def test_entree_refusee_vehicule_deja_present(client):
    first = client.post(
        "/api/v1/access/requests", json=_entry_payload("BB-222-BB"), headers=AUTH_HEADERS
    )
    assert first.json()["autorisation"]["resultat"] == 1

    second = client.post(
        "/api/v1/access/requests",
        json=_entry_payload("BB-222-BB", date="2026-09-02T10:20:00Z"),
        headers=AUTH_HEADERS,
    )
    assert second.status_code == 200
    body = second.json()
    assert body["autorisation"]["resultat"] == 2
    assert "présent" in body["autorisation"]["motif"]


def test_entree_confirmation_requise_pmr_sans_justificatif(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("FF-666-FF"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["autorisation"]["resultat"] == 3
    assert body["autorisation"]["controlePmrOk"] is False


def test_entree_vehicule_inconnu(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("UN-000-KN"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehiculeId"] is None
    assert body["statut"] == 3


def test_entree_sans_api_key_refusee(client):
    response = client.post("/api/v1/access/requests", json=_entry_payload("AA-111-AA"))
    assert response.status_code == 401


def test_plaque_format_invalide_rejetee_en_422(client):
    response = client.post(
        "/api/v1/access/requests", json=_entry_payload("invalide"), headers=AUTH_HEADERS
    )
    assert response.status_code == 422
