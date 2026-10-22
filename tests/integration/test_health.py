"""Test d'intégration — `GET /health` (sans authentification)."""

from src import __version__
from tests.integration.conftest import AUTH_HEADERS  # noqa: F401 (réexport pour lisibilité)


def test_health_sans_api_key(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert isinstance(body["uptimeSeconds"], int)


def test_health_expose_version_et_commit(client):
    body = client.get("/health").json()
    assert body["version"] == __version__
    # Hors Render, RENDER_GIT_COMMIT n'est pas défini
    assert body["commit"] == "local"
