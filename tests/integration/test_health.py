"""Test d'intégration — `GET /health` (sans authentification)."""

from tests.integration.conftest import AUTH_HEADERS  # noqa: F401 (réexport pour lisibilité)


def test_health_sans_api_key(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert isinstance(body["uptimeSeconds"], int)
