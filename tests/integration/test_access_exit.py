"""Tests d'intégration — workflow "Sortie" (via `TestClient`)."""

from tests.integration.conftest import AUTH_HEADERS


def _payload(plaque: str, type_: int, date: str, source: int = 3) -> dict:
    return {"plaque": plaque, "type": type_, "date": date, "source": source}


def test_sortie_autorisee_pricing_et_payment_ok(client):
    entry = client.post(
        "/api/v1/access/requests",
        json=_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"),
        headers=AUTH_HEADERS,
    )
    assert entry.json()["autorisation"]["resultat"] == 1

    exit_response = client.post(
        "/api/v1/access/requests",
        json=_payload("AA-111-AA", 2, "2026-09-02T11:00:00Z", source=2),
        headers=AUTH_HEADERS,
    )
    assert exit_response.status_code == 200
    body = exit_response.json()
    assert body["autorisation"]["resultat"] == 1
    assert body["autorisation"]["montantPaiement"] is not None
    assert body["autorisation"]["montantPaiement"] > 0


def test_sortie_refusee_paiement_echoue(client):
    entry = client.post(
        "/api/v1/access/requests",
        json=_payload("HH-888-HH", 1, "2026-09-02T10:00:00Z"),
        headers=AUTH_HEADERS,
    )
    assert entry.json()["autorisation"]["resultat"] == 1

    exit_response = client.post(
        "/api/v1/access/requests",
        json=_payload("HH-888-HH", 2, "2026-09-02T11:00:00Z", source=2),
        headers=AUTH_HEADERS,
    )
    assert exit_response.status_code == 200
    body = exit_response.json()
    assert body["autorisation"]["resultat"] == 2
    assert body["autorisation"]["motif"] == "Paiement refusé"


def test_sortie_refusee_vehicule_non_present(client):
    response = client.post(
        "/api/v1/access/requests",
        json=_payload("CC-333-CC", 2, "2026-09-02T11:00:00Z", source=2),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["autorisation"]["resultat"] == 2
    assert "non présent" in body["autorisation"]["motif"]


def test_get_access_request_par_id(client):
    entry = client.post(
        "/api/v1/access/requests",
        json=_payload("DD-444-DD", 1, "2026-09-02T10:00:00Z"),
        headers=AUTH_HEADERS,
    )
    demande_id = entry.json()["demandeId"]

    detail = client.get(f"/api/v1/access/requests/{demande_id}", headers=AUTH_HEADERS)
    assert detail.status_code == 200
    body = detail.json()
    assert body["demandeId"] == demande_id
    assert body["vehiculeId"] == "v_electric"


def test_get_access_request_introuvable(client):
    response = client.get("/api/v1/access/requests/does-not-exist", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_list_access_requests_filtre_par_vehicule_id(client):
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
        "/api/v1/access/requests", params={"vehiculeId": "v_normal_4roues"}, headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["vehiculeId"] == "v_normal_4roues"
