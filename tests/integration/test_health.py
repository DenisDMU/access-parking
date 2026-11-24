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
    # Moteur seulement (jamais l'URL ni ses identifiants)
    assert body["databaseEngine"] in ("sqlite", "postgresql")


def test_health_expose_version_et_commit(client):
    body = client.get("/health").json()
    assert body["version"] == __version__
    # Hors Render, RENDER_GIT_COMMIT n'est pas défini
    assert body["commit"] == "local"


def test_health_indique_si_booking_est_reel_ou_simule(client):
    # Les tests simulent Booking (BOOKING_USE_MOCK=true dans conftest).
    assert client.get("/health").json()["booking"] == "simulé"
