"""Test d'intégration — `GET /metrics` (Prometheus, clé API requise)."""

from tests.integration.conftest import AUTH_HEADERS


def test_metrics_sans_api_key_refuse(client):
    response = client.get("/metrics")
    assert response.status_code == 401


def test_metrics_avec_api_key(client):
    client.get("/api/v1/access/events", headers=AUTH_HEADERS)
    response = client.get("/metrics", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert "http_requests_total" in response.text
